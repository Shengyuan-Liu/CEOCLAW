# CLI 交互界面 (CEOClawCLI)

**源文件**: `cli.py`

## 概述

`cli.py` 是 CEOClaw 的**用户入口**,基于 **Rich** 库实现的终端交互界面。它负责:

1. **系统装配**:初始化 AgentScope、LLM 模型、记忆管理器、IntentionAgent、OrchestrationAgent、熔断器
2. **主循环**:读取用户输入,分发到内置命令或自然语言查询流水线
3. **流水线编排**:构建上下文消息(长期记忆摘要 + 短期对话 + 当前输入)→ 意图识别 → 调度执行 → 结果展示
4. **韧性保护**:每次 LLM 调用外包一层 `retry_with_backoff`,每次调用前检查 `CircuitBreaker`
5. **结果渲染**:按 agent 类型(research/marketing/product/sales/monitoring/web)做**人性化格式化输出**

有两种运行模式:
- **交互模式**: `python cli.py` — 进入主循环
- **健康检查模式**: `python cli.py health` — 不进入 CLI,只做一次 LLM 可达性检测后退出

---

## 入口函数

### `main()`

```python
def main():
    if len(sys.argv) > 1 and sys.argv[1].strip().lower() == "health":
        exit(run_health_check_standalone())
    cli = CEOClawCLI()
    asyncio.run(cli.run())
```

- 只认一个子命令 `health`,其他参数全忽略
- 交互模式用 `asyncio.run` 启动 async 主循环

### `run_health_check_standalone() -> int`

独立健康检查,供脚本/监控脚本用。

- 内部调 `init_agentscope()` + `utils.llm_resilience.run_health_check`
- 成功 → `print("OK")`,返回 0
- 失败 → `print(f"FAIL: {msg}")`,返回 1

这个函数**不**实例化 `CEOClawCLI`,意味着:
- 不创建 MemoryManager(不会写磁盘)
- 不加载 skill agent
- 启动极快(~1s),适合做 liveness/readiness 探针

---

## 类: `CEOClawCLI`

### `__init__(self)`

只做属性初始化,**不**做任何 I/O 或异步操作。真正的装配在 `initialize_system()`。

**初始状态**:
- `self.console`: `rich.console.Console` 实例
- `self.user_id`, `self.session_id`, `self.memory_manager`, `self.orchestrator`, `self.intention_agent`, `self.model`: `None`
- `self._agent_cache`: `{}` — 传给 `LazyAgentRegistry` 的共享缓存
- `self.circuit_breaker`: `None` — 在 `initialize_system` 中按配置实例化

---

### `async initialize_system(self)` — 系统装配

这是整个 CLI 的核心装配点,决定了多 agent 系统的连接拓扑。

**步骤**:

1. **交互获取用户 ID**: `Prompt.ask("用户ID", default="default_user")`。会阻塞等待输入——不适合无人值守运行。
2. **生成 session_id**: `str(uuid.uuid4())[:8]`——只保留 UUID 前 8 位,够辨识一次会话。
3. **`init_agentscope()`**: 来自 `config_agentscope`,初始化 AgentScope 运行时。
4. **构造 LLM 模型**:
   ```python
   OpenAIChatModel(
       model_name=LLM_CONFIG["model_name"],
       api_key=LLM_CONFIG["api_key"],
       client_kwargs={"base_url": ..., "timeout": ...},
       temperature=LLM_CONFIG.get("temperature", 0.7),
       max_tokens=LLM_CONFIG.get("max_tokens", 2000),
   )
   ```
   `timeout` 从 `SYSTEM_CONFIG["timeout"]` 读取(默认 60s),交给 OpenAI SDK 底层。
5. **`MemoryManager`**: 传入 `user_id` + `session_id` + LLM 模型(用于历史摘要)。
6. **`IntentionAgent`**: 预先实例化,每次查询都会用到,不能懒加载。
7. **`LazyAgentRegistry`**: 传入 `model` + `_agent_cache` + `memory_manager`。六个 skill agent 都在**首次被 OrchestrationAgent 查询**时才会实例化并缓存。
8. **`OrchestrationAgent`**: 持有 `lazy_registry`(注意:它其实是 `LazyAgentRegistry` 实例,不是普通 dict,但 OrchestrationAgent 只用 `__contains__` 和 `__getitem__` 访问,兼容)。
9. **`CircuitBreaker`**: 从 `RESILIENCE_CONFIG` 读 `circuit_failure_threshold`/`circuit_recovery_timeout_sec`/`circuit_half_open_successes`,缺省值由 `CircuitBreaker` 自己提供。

所有步骤包在 `self.console.status("初始化中...", spinner="dots")` 里,让用户看到 spinner。

**设计要点**:
- **懒加载 skill agent**: 除 IntentionAgent 外,其他 6 个 agent 首次使用才加载,显著加速冷启动。
- **`_agent_cache` 是共享状态**: CLI 自己也持有一份 `self._agent_cache`,用于 `status` 命令显示"已加载智能体数量"。
- **交互式输入不可脚本化**: `Prompt.ask` 会阻塞 stdin,若想自动化需要提前 pipe 输入。

---

### `async run(self)` — 主循环

**结构**:

```python
self.print_banner()
await self.initialize_system()
while True:
    try:
        user_input = Prompt.ask("\n[cyan]>[/cyan]")
        if not user_input.strip():
            continue
        command = user_input.strip().lower()
        if command == "exit":  ...
        elif command == "help":   ...
        elif command == "status": ...
        elif command == "health": ...
        elif command == "clear":  ...
        elif command == "history":...
        elif command == "preferences": ...
        else:
            await self.process_query(user_input)
    except KeyboardInterrupt:   # Ctrl+C
        self.console.print("\n使用 'exit' 退出", style="dim")
    except CircuitOpenError:    # 熔断打开
        self.console.print("[⚠ 服务暂时不可用,请稍后再试]")
    except Exception as e:      # 其他异常兜底
        self.console.print(f"\n错误: {e}", style="red")
```

**关键性质**:
- **异常不退出**: 所有异常都在循环内捕获,仅 `exit` 命令会 break。
- **KeyboardInterrupt 被吞**: `Ctrl+C` 只会打印提示,不退出。想退出必须输入 `exit`。
- **命令大小写不敏感**: 用 `.lower()` 统一处理。
- **空输入忽略**: 直接 continue。

---

## 内置命令

### `help` — `print_help()`

用 Rich `Table` 渲染命令列表。纯展示,无状态。

### `status` — `show_status()`

展示"记忆状态"和"最近对话 5 轮"两张表:

- **记忆状态**: 短期消息数 / 长期项目决策数 / 已加载智能体数(`len(self._agent_cache)`)
- **最近对话**: 从 `memory_manager.short_term.get_recent_context(n_turns=5)` 读取,内容超过 100 字符截断加 `...`,时间戳按 `HH:MM:SS` 显示

### `health` — `async run_health_check()`

会话内健康检查,**比 `cli.py health` 多显示熔断器状态**。

- 先读 `self.circuit_breaker.get_status()` 打印 state
- 再调 `check_llm_health` 做冒烟测试
- 成功 → `LLM 服务: 正常`;失败 → `LLM 服务: 不可用 - {msg}`

### `clear` — 清空短期记忆

```python
self.memory_manager.short_term.clear()
```

**不动长期记忆**——`history`、`preferences` 仍保留。命令名有点误导(clear 通常意味"全清"),但帮助信息里明确说"保留长期记忆"。

### `history` — `show_history()`

显示最近 10 条项目决策记录(表格形式),字段:record_id / action_type / description(截断 60 字) / timestamp(截断到秒)。

### `preferences` — `show_preferences()`

从 `long_term.get_preference()` 读,过滤掉空值,表格展示。

### `exit` — 退出

- 调 `self.memory_manager.end_session()`(持久化/收尾)
- `break` 退主循环

---

## 查询主流程: `async process_query(user_input)`

这是 CLI 把用户自然语言输入变成 agent 输出的完整流水线。

### 流程图

```
用户输入
  │
  ├─ 1. 熔断器检查 → OPEN 则降级退出
  │
  ├─ 2. 构建上下文消息 (Msg 列表)
  │     ├─ _get_long_term_summary()  → system message(项目偏好+历史摘要+最近3条决策)
  │     ├─ short_term.get_recent_context(5)   → user/assistant 历史
  │     └─ 当前用户输入                         → user message
  │
  ├─ 3. IntentionAgent.reply(context_messages)
  │     └─ 外包 retry_with_backoff
  │     └─ 成功/失败 → circuit_breaker.record_*
  │
  ├─ 4. JSON 解析意图结果;失败 → 打印错误退出
  │
  ├─ 5. 短期记忆追加 user message
  │
  ├─ 6. OrchestrationAgent.reply(intention_result)
  │     └─ 外包 retry_with_backoff
  │     └─ 成功/失败 → circuit_breaker.record_*
  │
  ├─ 7. JSON 解析调度结果
  │
  ├─ 8. _display_agents_called()   → "🤖 调用智能体: 市场调研 ✓, 产品规划 ✓"
  │
  ├─ 9. _display_results()         → 按 agent 类型做人性化渲染
  │
  └─ 10. 短期记忆追加 assistant message(JSON 字符串形式)
```

### 关键细节

#### 熔断器检查(入口)

```python
try:
    self.circuit_breaker.raise_if_open()
except CircuitOpenError:
    self.console.print("⚠ 服务暂时不可用,请稍后再试。")
    return
```

这里的 `CircuitOpenError` 被**就地吞掉**——`process_query` 内部直接 return,不向上传递。而 `run()` 里的 `except CircuitOpenError` 则是为了捕获嵌套调用中的熔断(比如 intention/orchestration 内部调用的熔断)。

#### 两次 LLM 调用的韧性保护

**意图识别**:
```python
intention_result = await retry_with_backoff(
    lambda: self.intention_agent.reply(context_messages),
    max_retries=max_retries,
    base_delay_sec=rc.get("retry_base_delay_sec", 1.0),
    max_delay_sec=rc.get("retry_max_delay_sec", 30.0),
)
```

**调度执行** 用同样的包装。每次成功都 `record_success()`,每次失败都 `record_failure()`——这是 CircuitBreaker 的状态信号源。

注意:**`process_query` 里只有这两个 LLM 调用点被显式保护**。skill agent 内部可能会发更多 LLM 调用(比如 MarketingAgent 的 JSON 修复、WebAgent 的 prompt 生成),那些调用不走 `retry_with_backoff`,只依赖 LLM SDK 自己的重试。

#### JSON 解析失败的两种处理

- **意图结果 JSON 失败**: 打印 `"❌ 无法理解您的需求,请重新描述"` 并 return——对话被中断,用户需要重新输入。
- **调度结果 JSON 失败**: `result_data = {"error": "解析结果失败"}`——**不中断**,继续走展示流程,让用户看到错误消息。

这反映了对两个 agent 的不同信任度:意图识别是入口,错了没法继续;调度结果就算解析挂了,也该给用户一个明确的回复。

#### 短期记忆的时序

```python
# 意图识别之后,调度之前
self.memory_manager.add_message("user", user_input)
# 调度和渲染之后
self.memory_manager.add_message("assistant", json.dumps(result_data, ...))
```

这个顺序很微妙:**user message 在意图识别后才写入**。原因是意图识别本身需要上下文,但此时"当前输入"还不算"历史"——它被 `context_messages.append(Msg(..., "user"))` 手动加到了意图识别的 prompt 里。记忆里存的是"处理过的对话",不是"正在进行的对话"。

---

### `async _get_long_term_summary(user_input="") -> str`

为 IntentionAgent 构造系统级长期记忆摘要。输出是一个 **多段合并的字符串**,注入为 system role message。

**三段结构**:

1. **项目背景信息**: `long_term.get_preference()` 的所有非空字段。list 类型用 `, ` 连接。
2. **历史会话总结**: `memory_manager.get_long_term_summary_async(max_messages=50)` — 异步调用 LLM 对最近 50 条消息做 summary。
3. **历史决策记录**: `long_term.get_project_history()` 的**最近 3 条**,格式 `N. [timestamp] action_type: description`。

三段都可能为空,空段不会出现在最终字符串中;全空则返回 `""`。

**设计要点**:
- **`user_input` 参数没被使用**: 函数签名有这个参数,文档字符串说"用于筛选相关历史",但代码里没用到。未来可能做"按 user_input 相关性召回历史"。
- **每次查询都调一次 LLM 摘要**: 这是第 **三** 次 LLM 调用(意图识别 + 调度中的 skill agent 之外的另一次)。对话一长,延迟会明显。
- **最近 3 条记录硬编码**: 不是从 RESILIENCE_CONFIG 读。

---

## 结果渲染

### `_display_agents_called(result_data)` — 被调用的 agent 清单

一行摘要,例如:`🤖 调用智能体: 市场调研 ✓, 产品规划 ✓, 营销策略 ✗`

- ✓ = success,✗ = error,? = 其他
- 用 `_get_agent_display_name` 把 `research`/`marketing`/... 翻译成中文展示名

### `_display_results(result_data)` — 主渲染入口

三种分支:
- **`no_agents` 状态**(意图识别认为不需要任何 agent): 打印"好的,我已记录下来。" + 三个示例提示
- **有 results**: 调 `_generate_human_response`;若它说没生成任何输出,兜底打印 `"✓ 已处理您的请求。"`
- **其他**: `"未能获取有效结果,请重新描述您的需求。"`

### `_generate_human_response(results) -> bool` — 按 agent 类型渲染

这是**整个 CLI 里最长的方法**(175 行),本质是个大 if/elif:

| agent_name | 渲染内容 |
|---|---|
| `research` | `findings` 正文 + 前 3 个 `sources` 的 URL |
| `marketing` | `strategy`(标题、目标受众、渠道、内容、时间、预算) + `action_items`(带优先级) |
| `product` | `product_plan`(愿景、目标用户、核心价值) + `features`(带优先级) + `roadmap`(阶段+交付物) |
| `sales` | `prospects.target_profile` + `prospects.channels` + `outreach.pitch` |
| `monitoring` | `answer` 或 `analysis` 正文 |
| `web` | `lovable_url`(高亮蓝色) + `deployment` 信息 |

**两层数据访问兜底**:大部分分支都有 `data.get("strategy") or data["data"].get("strategy")` 这种双重读取,因为 skill agent 的返回结构偶尔会被额外嵌套一层 `data`(OrchestrationAgent 包装时的副作用)。

**通用兜底**:如果特定分支没生成任何内容,按顺序试 `answer` / `content` / `result` / `message` / `summary` / `text` / `description` / `findings` 这 8 个常见键;都没有就打印 `"✓ {display_name}已完成"`——**保证永远有回复**。

### `_get_agent_display_name(agent_name) -> str`

硬编码字典映射:

```python
{
    "research": "市场调研",
    "marketing": "营销策略",
    "product": "产品规划",
    "sales": "销售执行",
    "monitoring": "绩效监控",
    "web": "Web部署",
}
```

未知 agent 名直接返回原名,不抛异常。

---

## 模块依赖图

```
cli.py
 ├─ rich.*               (UI)
 ├─ agentscope.model     (LLM)
 ├─ config_agentscope    (init_agentscope)
 ├─ config               (LLM_CONFIG / SYSTEM_CONFIG / RESILIENCE_CONFIG)
 ├─ context.memory_manager       (MemoryManager)
 ├─ utils.circuit_breaker        (CircuitBreaker / CircuitOpenError)
 ├─ utils.llm_resilience         (retry_with_backoff / run_health_check)
 ├─ agents.intention_agent       (IntentionAgent)
 ├─ agents.orchestration_agent   (OrchestrationAgent)
 └─ agents.lazy_agent_registry   (LazyAgentRegistry) ← 只在 initialize_system 里导入
```

`LazyAgentRegistry` 是**函数内局部导入**(不在顶部),避免 CLI 启动时触发 skill 目录扫描。

---

## 典型一次查询的延迟构成

以"为AI教育产品做调研并规划功能"为例:

| 阶段 | 耗时 | 备注 |
|---|---|---|
| 读取长期记忆 + 历史摘要 LLM 调用 | ~2-4s | 可优化:缓存摘要 |
| IntentionAgent LLM 调用 | ~2-3s | 必经,含 JSON 输出 |
| ResearchAgent Tavily API + 摘要 LLM | ~5-8s | Tavily 深度搜索最慢 |
| ProductAgent LLM 调用 | ~3-5s | 含 P1 结果整合 |
| 渲染 | <100ms | Rich 极快 |
| **总计** | **12-20s** | |

若触发 JSON 修复,每次再加 ~2-3s。若触发重试,加 1-7s 等待。

---

## 设计要点

- **永远有回复**: `_display_results` 和 `_generate_human_response` 的兜底链是刻意设计的,哪怕 agent 挂了、JSON 解析挂了、数据为空,都会打印一个明确的信息,不会让用户看到空白屏幕。
- **Async all the way**: `run()`、`initialize_system()`、`process_query()`、`_get_long_term_summary()`、`run_health_check()` 都是 async。Rich 的 `status()` 和 `print()` 本身是同步的,但在 async 环境里也能正常用(它们不阻塞事件循环足够长的时间)。
- **主循环吞所有异常**: 这是 CLI 的默认稳定性策略——单次查询失败不影响下次。代价是某些严重错误(比如 API key 失效)也会被"降级"成一行红字,用户可能看不出要换 key。
- **短期记忆的写入时机**: user 和 assistant 消息是在流水线中段/末端才写入,而不是一收到输入就写。这让意图识别的 system context 不会把"当前输入"当"历史"处理。
- **熔断器与重试的协作边界**: `process_query` 把每次 LLM 调用外包给 `retry_with_backoff`,并在 success/failure 时更新熔断器。但注意:`retry_with_backoff` 内部多次失败只会算**一次** `record_failure()`(因为是最外层的 except 在捕获)。所以"失败计数 = 查询次数",不是"失败计数 = LLM 调用次数"。
- **`LazyAgentRegistry` 被当 dict 用**: OrchestrationAgent 期望 `Dict[str, AgentBase]`,但这里传的是 `LazyAgentRegistry` 实例。Python 的鸭子类型让它工作——只要实现了 `__contains__` 和 `__getitem__`。
- **`health` 子命令不加载任何重组件**: 单独的 `run_health_check_standalone()` 路径只调 `init_agentscope` + `check_llm_health`,不创建 CLI 实例,不初始化 MemoryManager,不扫描 skills 目录。这让它能作为 Docker HEALTHCHECK 或 K8s probe 使用。
- **Rich 的 `status()` 不嵌套**: `initialize_system` 和 `process_query` 都用了 `with console.status(...)`。如果两个 status 嵌套(比如未来在 initialize 里加一个查询),Rich 会出现渲染冲突——目前没有,但需要注意。
- **主循环没有 outputs 的批量刷新**: 每个 `console.print` 都是即时输出。对 agent 结果流式展示不友好,如果未来要做 token-by-token streaming,整个渲染架构需要重写。
