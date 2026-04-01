#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
CEOClaw 创业助手 - CLI 交互界面
使用 Rich 库实现美观的终端交互
"""
import asyncio
import sys
import os
from typing import Optional

# 添加项目根目录到路径
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.layout import Layout
from rich.live import Live
from rich.text import Text
import json

# 导入系统组件
from agentscope.model import OpenAIChatModel
from config_agentscope import init_agentscope
from config import LLM_CONFIG, SYSTEM_CONFIG, RESILIENCE_CONFIG
from context.memory_manager import MemoryManager
from utils.circuit_breaker import CircuitBreaker, CircuitOpenError
from utils.llm_resilience import retry_with_backoff, run_health_check as check_llm_health
from agents.intention_agent import IntentionAgent
from agents.orchestration_agent import OrchestrationAgent


class CEOClawCLI:
    """CEOClaw 创业助手 CLI"""

    def __init__(self):
        """初始化 CLI"""
        self.console = Console()
        self.user_id = None
        self.session_id = None
        self.memory_manager = None
        self.orchestrator = None
        self.intention_agent = None
        self.model = None
        self._agent_cache = {}  # 智能体缓存
        self.circuit_breaker = None  # 在 initialize_system 中从 RESILIENCE_CONFIG ���始化

    def print_banner(self):
        """打印欢迎横幅"""
        self.console.print("\n[bold cyan]🦅 CEOClaw 创业助手[/bold cyan] - AI Startup Founder Agent\n", style="bold")

    def print_help(self):
        """打印帮助信息"""
        table = Table(title="命令列表", show_header=True, header_style="bold magenta")
        table.add_column("命令", style="cyan", width=20)
        table.add_column("说明", style="white")

        table.add_row("help", "显示此帮助信息")
        table.add_row("status", "查看当前状态和记忆")
        table.add_row("health", "检查 LLM 服务是否可用")
        table.add_row("clear", "清空当前任务（保留长期记忆）")
        table.add_row("history", "查看历史决策记录")
        table.add_row("preferences", "查看项目偏好设置")
        table.add_row("exit", "退出程序")
        table.add_row("", "")
        table.add_row("[自然语言]", "直接输入您的需求，如：")
        table.add_row("", "  - 帮我调研一下AI教育市场")
        table.add_row("", "  - 制定一个SaaS产品的营销策略")
        table.add_row("", "  - 做一个产品规划方案")

        self.console.print(table)

    async def initialize_system(self):
        """初始化系统 - 使用懒加载优化启动速度"""
        # 获取用户信息
        self.user_id = Prompt.ask(
            "用户ID",
            default="default_user"
        )

        # 生成会话ID
        import uuid
        self.session_id = str(uuid.uuid4())[:8]

        with self.console.status("初始化中...", spinner="dots"):
            # 初始化AgentScope
            init_agentscope()

            # 初始化模型
            timeout_sec = SYSTEM_CONFIG.get("timeout", 60)
            self.model = OpenAIChatModel(
                model_name=LLM_CONFIG["model_name"],
                api_key=LLM_CONFIG["api_key"],
                client_kwargs={
                    "base_url": LLM_CONFIG["base_url"],
                    "timeout": float(timeout_sec),
                },
                temperature=LLM_CONFIG.get("temperature", 0.7),
                max_tokens=LLM_CONFIG.get("max_tokens", 2000),
            )

            # 初始化记忆管理器（传入LLM模型用于总结）
            self.memory_manager = MemoryManager(
                user_id=self.user_id,
                session_id=self.session_id,
                llm_model=self.model
            )

            # 初始化意图识别智能体（必须预加载）
            self.intention_agent = IntentionAgent(
                name="IntentionAgent",
                model=self.model
            )

            # 使用懒加载注册器（智能体在首次使用时才加载）
            from agents.lazy_agent_registry import LazyAgentRegistry
            self._agent_cache = {}
            lazy_registry = LazyAgentRegistry(
                model=self.model,
                cache=self._agent_cache,
                memory_manager=self.memory_manager
            )

            # 初始化协调器
            self.orchestrator = OrchestrationAgent(
                name="OrchestrationAgent",
                agent_registry=lazy_registry,
                memory_manager=self.memory_manager
            )

            # 熔断器（连接与可用性）
            rc = RESILIENCE_CONFIG
            self.circuit_breaker = CircuitBreaker(
                failure_threshold=rc.get("circuit_failure_threshold", 5),
                recovery_timeout_sec=rc.get("circuit_recovery_timeout_sec", 60.0),
                half_open_successes=rc.get("circuit_half_open_successes", 2),
            )

        self.console.print(f"✓ 就绪 (用户: {self.user_id}) - 输入 help 查看帮助\n", style="green")

    async def process_query(self, user_input: str):
        """
        处理用户查询（原逻辑保留；仅在入口加熔断检查、对 LLM 调用加重试）
        """
        import time
        start_time = time.time()

        # ---------- 熔断检查 ----------
        if self.circuit_breaker:
            try:
                self.circuit_breaker.raise_if_open()
            except CircuitOpenError:
                self.console.print(
                    "\n[bold yellow]⚠ 服务暂时不可用，请稍后再试。[/bold yellow]\n",
                    style="dim"
                )
                return

        rc = RESILIENCE_CONFIG
        max_retries = rc.get("max_retries", 3)

        with self.console.status("思考中...", spinner="dots"):
            from agentscope.message import Msg

            # 1. 获取长期记忆摘要与上下文
            long_term_summary = await self._get_long_term_summary(user_input)
            recent_context = self.memory_manager.short_term.get_recent_context(n_turns=5)
            context_messages = []
            if long_term_summary:
                context_messages.append(Msg(name="system", content=long_term_summary, role="system"))
            for msg in recent_context:
                context_messages.append(Msg(name=msg["role"], content=msg["content"], role=msg["role"]))
            context_messages.append(Msg(name="user", content=user_input, role="user"))

            # 2. 意图识别（加重试）
            intention_result = None
            try:
                intention_result = await retry_with_backoff(
                    lambda: self.intention_agent.reply(context_messages),
                    max_retries=max_retries,
                    base_delay_sec=rc.get("retry_base_delay_sec", 1.0),
                    max_delay_sec=rc.get("retry_max_delay_sec", 30.0),
                )
                if self.circuit_breaker:
                    self.circuit_breaker.record_success()
            except CircuitOpenError:
                raise
            except Exception as e:
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure()
                raise

            # 3. 解析意图识别结果
            try:
                intention_data = json.loads(intention_result.content)
            except json.JSONDecodeError:
                self.console.print("❌ 无法理解您的需求，请重新描述", style="bold red")
                return

        # 4. 添加用户输入到短期记忆
        self.memory_manager.add_message("user", user_input)

        # 5. 调度智能体
        orchestration_result = None
        try:
            orchestration_result = await retry_with_backoff(
                lambda: self.orchestrator.reply(intention_result),
                max_retries=max_retries,
                base_delay_sec=rc.get("retry_base_delay_sec", 1.0),
                max_delay_sec=rc.get("retry_max_delay_sec", 30.0),
            )
            if self.circuit_breaker:
                self.circuit_breaker.record_success()
        except CircuitOpenError:
            raise
        except Exception as e:
            if self.circuit_breaker:
                self.circuit_breaker.record_failure()
            raise

        # 6. 解析执行结果
        try:
            result_data = json.loads(orchestration_result.content)
        except json.JSONDecodeError:
            result_data = {"error": "解析结果失败"}

        # 7. 显示调用的智能体与最终结果
        self._display_agents_called(result_data)
        self.console.print()
        self._display_results(result_data)
        self.memory_manager.add_message("assistant", json.dumps(result_data, ensure_ascii=False))

    def _display_agents_called(self, result_data: dict):
        """显示调用的智能体列表"""
        results = result_data.get("results", [])
        if not results:
            return

        agents_called = []
        for result in results:
            agent_name = result.get("agent_name", "")
            status = result.get("status", "")

            display_name = self._get_agent_display_name(agent_name)

            if status == "success":
                agents_called.append(f"{display_name} ✓")
            elif status == "error":
                agents_called.append(f"{display_name} ✗")
            else:
                agents_called.append(f"{display_name} ?")

        if agents_called:
            self.console.print()
            self.console.print(f"🤖 调用智能体: {', '.join(agents_called)}", style="dim")

    def _display_results(self, result_data: dict):
        """显示执行结果 - 确保永远有回复"""
        self.console.print()

        results = result_data.get("results", [])

        if not results:
            status = result_data.get("status", "unknown")
            if status == "no_agents":
                self.console.print("✓ 好的，我已记录下来。", style="green")
                self.console.print("\n💡 您可以继续补充信息，或者尝试：", style="dim")
                self.console.print("  • 市场调研：「帮我调研一下AI教育市场」", style="dim")
                self.console.print("  • 产品规划：「做一个SaaS产品方案」", style="dim")
                self.console.print("  • 营销策略：「制定营销推广计划」", style="dim")
            else:
                self.console.print("未能获取有效结果，请重新描述您的需求。", style="yellow")
        else:
            has_output = self._generate_human_response(results)

            if not has_output:
                self.console.print("✓ 已处理您的请求。", style="green")

        self.console.print()

    async def _get_long_term_summary(self, user_input: str = "") -> str:
        """
        生成长期记忆摘要，用于传递给IntentionAgent

        Args:
            user_input: 用户输入，用于筛选相关历史

        Returns:
            格式化的长期记忆摘要
        """
        summary_parts = []

        # 1. 项目偏好信息（始终加载）
        prefs = self.memory_manager.long_term.get_preference()
        if prefs:
            pref_lines = ["【项目背景信息】（来自长期记忆，可用于推断上下文）"]

            for pref_key, pref_value in prefs.items():
                if pref_value:
                    if isinstance(pref_value, list):
                        pref_lines.append(f"• {pref_key}: {', '.join(pref_value)}")
                    else:
                        pref_lines.append(f"• {pref_key}: {pref_value}")

            if len(pref_lines) > 1:
                summary_parts.extend(pref_lines)

        # 2. 使用LLM总结历史聊天记录
        chat_summary = await self.memory_manager.get_long_term_summary_async(max_messages=50)
        if chat_summary:
            summary_parts.append("\n【历史会话总结】")
            summary_parts.append(chat_summary)

        # 3. 智能筛选相关历史决策
        all_records = self.memory_manager.long_term.get_project_history(limit=None)
        if all_records:
            records_to_show = all_records[-3:]  # 最近3条决策记录

            if records_to_show:
                summary_parts.append("\n【历史决策记录】")
                for i, record in enumerate(records_to_show[:3], 1):
                    action_type = record.get("action_type", "未知")
                    description = record.get("description", "")
                    timestamp = record.get("timestamp", "")
                    summary_parts.append(
                        f"{i}. [{timestamp}] {action_type}: {description}"
                    )

        return "\n".join(summary_parts) if summary_parts else ""

    def _generate_human_response(self, results: list) -> bool:
        """根据结果生成人性化的回复"""
        has_output = False

        for result in results:
            agent_name = result.get("agent_name", "")
            status = result.get("status", "")
            data = result.get("data", {})
            current_agent_shown = False

            # 处理失败的智能体
            if status == "error":
                error_msg = data.get("error", "未知错误")
                agent_display_name = self._get_agent_display_name(agent_name)
                self.console.print(f"❌ {agent_display_name}执行失败: {error_msg}", style="red")
                has_output = True
                continue

            if status != "success":
                continue

            # --- 特定 Agent 处理 ---

            # 调研结果
            if agent_name == "research":
                findings = data.get("findings") or data.get("results", {}).get("summary", "")
                sources = data.get("results", {}).get("sources", [])

                if findings:
                    self.console.print(f"\n{findings}")
                    current_agent_shown = True

                if sources:
                    self.console.print("\n[bold]参考来源[/bold]")
                    for i, source in enumerate(sources[:3], 1):
                        url = source.get("url", "") if isinstance(source, dict) else str(source)
                        self.console.print(f"  {i}. {url}", style="dim")
                    current_agent_shown = True

            # 营销策略
            elif agent_name == "marketing":
                strategy = data.get("strategy")
                if not strategy and "data" in data and isinstance(data["data"], dict):
                    strategy = data["data"].get("strategy")

                if strategy and isinstance(strategy, dict):
                    title = strategy.get('title', '营销策略')
                    self.console.print(f"\n📢 [bold cyan]{title}[/bold cyan]")
                    if strategy.get("target_audience"):
                        self.console.print(f"目标受众: {strategy['target_audience']}")
                    if strategy.get("channels"):
                        self.console.print(f"推荐渠道: {', '.join(strategy['channels'])}")
                    if strategy.get("content_strategy"):
                        self.console.print(f"内容策略: {strategy['content_strategy']}")
                    if strategy.get("timeline"):
                        self.console.print(f"执行时间: {strategy['timeline']}")
                    if strategy.get("budget_estimate"):
                        self.console.print(f"预算估算: {strategy['budget_estimate']}")
                    current_agent_shown = True

                action_items = data.get("action_items", [])
                if action_items:
                    self.console.print("\n[bold]行动计划[/bold]")
                    for item in action_items:
                        action = item.get("action", "")
                        priority = item.get("priority", "")
                        self.console.print(f"  • [{priority}] {action}")
                    current_agent_shown = True

            # 产品规划
            elif agent_name == "product":
                plan = data.get("product_plan")
                if not plan and "data" in data and isinstance(data["data"], dict):
                    plan = data["data"].get("product_plan")

                if plan and isinstance(plan, dict):
                    name = plan.get('name', '产品规划')
                    self.console.print(f"\n🚀 [bold cyan]{name}[/bold cyan]")
                    if plan.get("vision"):
                        self.console.print(f"愿景: {plan['vision']}")
                    if plan.get("target_users"):
                        self.console.print(f"目标用户: {plan['target_users']}")
                    if plan.get("core_value"):
                        self.console.print(f"核心价值: {plan['core_value']}")

                    features = plan.get("features", [])
                    if features:
                        self.console.print("\n[bold]功能列表[/bold]")
                        for feat in features:
                            p = feat.get("priority", "")
                            n = feat.get("name", "")
                            d = feat.get("description", "")
                            self.console.print(f"  • [{p}] {n}: {d}")

                    roadmap = plan.get("roadmap", [])
                    if roadmap:
                        self.console.print("\n[bold]路线图[/bold]")
                        for phase in roadmap:
                            ph = phase.get("phase", "")
                            tl = phase.get("timeline", "")
                            self.console.print(f"  {ph} ({tl})")
                            for d in phase.get("deliverables", []):
                                self.console.print(f"    - {d}")

                    current_agent_shown = True

            # 销售
            elif agent_name == "sales":
                prospects = data.get("prospects")
                outreach = data.get("outreach_plan")

                if prospects and isinstance(prospects, dict):
                    profile = prospects.get("target_profile", "")
                    if profile:
                        self.console.print(f"\n🎯 目标客户: {profile}")
                    channels = prospects.get("channels", [])
                    if channels:
                        self.console.print(f"获客渠道: {', '.join(channels)}")
                    current_agent_shown = True

                if outreach and isinstance(outreach, dict):
                    pitch = outreach.get("pitch", "")
                    if pitch:
                        self.console.print(f"\n[bold]电梯演讲[/bold]")
                        self.console.print(f"  {pitch}")
                    current_agent_shown = True

            # 监控分析
            elif agent_name == "monitoring":
                answer = data.get("answer") or data.get("analysis", "")
                if answer:
                    self.console.print(f"\n{answer}")
                    current_agent_shown = True

            # Web部署
            elif agent_name == "web":
                lovable_url = data.get("lovable_url", "")
                deployment = data.get("deployment")

                if lovable_url:
                    self.console.print(f"\n✓ [bold green]落地页已准备就绪[/bold green]")
                    self.console.print(f"\n🔗 [bold blue]点击链接自动生成落地页:[/bold blue]")
                    self.console.print(f"   {lovable_url}\n")
                    current_agent_shown = True

                if deployment and isinstance(deployment, dict):
                    method = deployment.get("method", "")
                    instructions = deployment.get("instructions", "")
                    if method:
                        self.console.print(f"部署方式: {method}")
                    if instructions:
                        self.console.print(f"说明: {instructions}")
                    current_agent_shown = True

            # --- 通用兜底 ---
            if not current_agent_shown:
                common_keys = ["answer", "content", "result", "message", "summary", "text", "description", "findings"]
                fallback_content = ""

                for k in common_keys:
                    if k in data and isinstance(data[k], str) and data[k].strip():
                        fallback_content = data[k]
                        break

                if not fallback_content and "data" in data and isinstance(data["data"], dict):
                    for k in common_keys:
                        if k in data["data"] and isinstance(data["data"][k], str) and data["data"][k].strip():
                            fallback_content = data["data"][k]
                            break

                if fallback_content:
                    self.console.print(f"\n{fallback_content}")
                    current_agent_shown = True
                else:
                    agent_display_name = self._get_agent_display_name(agent_name)
                    self.console.print(f"✓ {agent_display_name}已完成", style="green")
                    current_agent_shown = True

            if current_agent_shown:
                has_output = True

        return has_output

    def _get_agent_display_name(self, agent_name: str) -> str:
        """获取智能体的显示名称"""
        agent_display_names = {
            "research": "市场调研",
            "marketing": "营销策略",
            "product": "产品规划",
            "sales": "销售执行",
            "monitoring": "绩效监控",
            "web": "Web部署",
        }
        return agent_display_names.get(agent_name, agent_name)

    def show_status(self):
        """显示当前状态"""
        full_context = self.memory_manager.get_full_context()
        short_term_stats = full_context["short_term"]["statistics"]
        long_term_stats = full_context["long_term"]["statistics"]

        memory_table = Table(title="记忆状态", show_header=True, header_style="bold magenta")
        memory_table.add_column("类型", style="cyan")
        memory_table.add_column("状态", style="white")

        memory_table.add_row(
            "短期记忆",
            f"{short_term_stats['total_messages']} 条消息"
        )
        memory_table.add_row(
            "长期记忆",
            f"{long_term_stats['total_projects']} 次项目决策"
        )
        memory_table.add_row(
            "已加载智能体",
            f"{len(self._agent_cache)} 个"
        )

        self.console.print(memory_table)
        self.console.print()

        # 历史对话
        recent_messages = self.memory_manager.short_term.get_recent_context(n_turns=5)
        if recent_messages:
            dialogue_table = Table(title="最近对话 (最多5轮)", show_header=True, header_style="bold cyan")
            dialogue_table.add_column("角色", style="cyan", width=8)
            dialogue_table.add_column("内容", style="white", width=60)
            dialogue_table.add_column("时间", style="dim", width=12)

            for msg in recent_messages:
                role_name = "👤 用户" if msg["role"] == "user" else "🤖 助手"
                content = msg["content"]

                if len(content) > 100:
                    content = content[:100] + "..."

                timestamp = msg.get("timestamp", "")
                if timestamp:
                    from datetime import datetime
                    try:
                        dt = datetime.fromisoformat(timestamp)
                        time_str = dt.strftime("%H:%M:%S")
                    except:
                        time_str = ""
                else:
                    time_str = ""

                dialogue_table.add_row(role_name, content, time_str)

            self.console.print(dialogue_table)
            self.console.print()

    async def run_health_check(self):
        """在会话内执行健康检查并显示熔断器状态"""
        if self.circuit_breaker:
            status = self.circuit_breaker.get_status()
            self.console.print(f"[bold]熔断器[/bold]: {status['state']}", style="cyan")
        ok, msg = await check_llm_health(
            base_url=LLM_CONFIG["base_url"],
            api_key=LLM_CONFIG["api_key"],
            model_name=LLM_CONFIG["model_name"],
            timeout_sec=RESILIENCE_CONFIG.get("health_check_timeout_sec", 10.0),
        )
        if ok:
            self.console.print("LLM 服务: [green]正常[/green]", style="bold")
        else:
            self.console.print(f"LLM 服务: [red]不可用[/red] - {msg}", style="bold")
        self.console.print()

    def show_history(self):
        """显示历史决策记录"""
        history = self.memory_manager.long_term.get_project_history(10)

        if not history:
            self.console.print("暂无历史决策记录", style="yellow")
            return

        table = Table(title="历史决策记录", show_header=True, header_style="bold magenta")
        table.add_column("ID", style="cyan")
        table.add_column("类型", style="white")
        table.add_column("描述", style="white")
        table.add_column("时间", style="dim")

        for record in history:
            table.add_row(
                record.get("record_id", ""),
                record.get("action_type", ""),
                record.get("description", "")[:60],
                record.get("timestamp", "")[:19]
            )

        self.console.print(table)

    def show_preferences(self):
        """显示项目偏好"""
        prefs = self.memory_manager.long_term.get_preference()

        table = Table(title="项目偏好", show_header=True, header_style="bold magenta")
        table.add_column("类型", style="cyan")
        table.add_column("值", style="white")

        for key, value in prefs.items():
            if value:
                table.add_row(key, str(value))

        self.console.print(table)

    async def run(self):
        """运行 CLI"""
        # 打印横幅
        self.print_banner()

        # 初始化系统
        await self.initialize_system()

        # 主循环
        while True:
            try:
                # 获取用户输入
                user_input = Prompt.ask("\n[cyan]>[/cyan]")

                if not user_input.strip():
                    continue

                # 处理命令
                command = user_input.strip().lower()

                if command == "exit":
                    self.memory_manager.end_session()
                    self.console.print("再见！", style="cyan")
                    break
                elif command == "help":
                    self.print_help()
                elif command == "status":
                    self.show_status()
                elif command == "health":
                    await self.run_health_check()
                elif command == "clear":
                    self.memory_manager.short_term.clear()
                    self.console.print("✓ 已清空短期记忆", style="green")
                elif command == "history":
                    self.show_history()
                elif command == "preferences":
                    self.show_preferences()
                else:
                    # 处理自然语言查询
                    await self.process_query(user_input)

            except KeyboardInterrupt:
                self.console.print("\n使用 'exit' 退出", style="dim")
            except CircuitOpenError:
                self.console.print("\n[bold yellow]⚠ 服务暂时不可用，请稍后再试。[/bold yellow]", style="dim")
            except Exception as e:
                self.console.print(f"\n错误: {e}", style="red")


def run_health_check_standalone() -> int:
    """
    独立执行健康检查（用于 `python cli.py health`）。
    不进入交互式 CLI，只检测 LLM 是否可达。
    Returns:
        0 成功，1 失败（便于脚本/监控）
    """
    import asyncio
    init_agentscope()
    ok, msg = asyncio.run(check_llm_health(
        base_url=LLM_CONFIG["base_url"],
        api_key=LLM_CONFIG["api_key"],
        model_name=LLM_CONFIG["model_name"],
        timeout_sec=RESILIENCE_CONFIG.get("health_check_timeout_sec", 10.0),
    ))
    if ok:
        print("OK")
        return 0
    print(f"FAIL: {msg}")
    return 1


def main():
    """主函数"""
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "health":
        exit(run_health_check_standalone())
    cli = CEOClawCLI()
    asyncio.run(cli.run())


if __name__ == "__main__":
    main()
