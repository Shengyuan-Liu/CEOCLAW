"""
意图识别智能体 IntentionRecognitionAgent（CEO Agent 的意图识别层）
职责：准确识别用户的创业相关意图，并进行智能体调度

核心功能：
1. 多意图识别和分类：融合上下文对模糊意图进行消歧
2. 智能体调度决策：基于预定义的触发条件和业务规则，根据识别结果决定调用哪些子智能体
3. Query改写：标准化用户口语化的query输入，补全上下文信息，提取和重组关键信息
4. 显示推理：输出的两段式结构（推理过程 + JSON决策），提升意图识别准确度

架构：
- 使用单一LLM（用户配置的模型）
- 输入：用户query（自然语言）
- 输出：推理过程生成（包含reasoning+原因） + 多意图识别（原因） + 智能Query改写 + 构建结构化决策
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List
import json
import logging
from utils.skill_loader import SkillLoader
from utils.json_parser import extract_json_from_async_response, robust_json_parse

logger = logging.getLogger(__name__)


class IntentionAgent(AgentBase):
    """意图识别智能体（CEO Agent 的意图识别层）"""

    def __init__(self, name: str = "IntentionRecognitionAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        self.conversation_history = []
        self.skill_loader = SkillLoader()

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        """
        意图识别主流程
        1. 推理过程生成
        2. 多意图识别
        3. 智能Query改写
        4. 构建结构化决策
        """
        if x is None:
            return Msg(name=self.name, content=json.dumps({}), role="assistant")

        # 获取用户查询
        if isinstance(x, list):
            user_query = x[-1].content if x else ""
            # 提取历史对话，保留角色信息
            self.conversation_history = []
            for msg in x[:-1]:
                if hasattr(msg, 'content') and hasattr(msg, 'role'):
                    if msg.role == "system":
                        self.conversation_history.append(f"[系统记忆]\n{msg.content}")
                    else:
                        role_name = "用户" if msg.role == "user" else "助手"
                        content = msg.content[:800] if len(msg.content) > 800 else msg.content
                        if len(msg.content) > 800:
                            content += "..."
                        self.conversation_history.append(f"{role_name}: {content}")
        else:
            user_query = x.content

        # 构建上下文
        context_parts = []
        system_memory = None
        dialogue_history = []

        for item in self.conversation_history:
            if item.startswith("[系统记忆]"):
                system_memory = item
            else:
                dialogue_history.append(item)

        if system_memory:
            context_parts.append(system_memory)
        if dialogue_history:
            context_parts.extend(dialogue_history)

        context_str = "\n".join(context_parts) if context_parts else "无历史对话"

        # 获取当前时间
        from datetime import datetime
        current_time = datetime.now().strftime("%Y年%m月%d日 %H:%M")
        weekday = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][datetime.now().weekday()]

        # 动态获取 Skills 描述
        skill_mapping = {
            "research": "research",
            "marketing": "marketing",
            "product": "product",
            "sales": "sales",
            "monitoring": "monitoring",
            "web": "web"
        }

        dynamic_skills_prompt = self.skill_loader.get_skill_prompt(skill_mapping)

        # 构建意图识别Prompt
        prompt = f"""你是一个高级意图识别专家（CEO Agent 的意图识别层）。请分析用户查询，识别创业相关意图并输出结构化的决策。

【当前时间】
{current_time} {weekday}

【用户Query】
{user_query}

【对话历史上下文】
{context_str}

【可调度的子智能体 (Skills)】
{dynamic_skills_prompt}

【重要 - 意图区分原则】
请基于语义理解判断意图，不要机械匹配关键词。同一个词在不同语境下可能对应不同意图：
- "分析一下市场" → research（市场调研）
- "制定营销策略" → marketing（营销策略）
- "做一个产品规划" → product（产品规划）
- "找一些潜在客户" → sales（销售执行）
- "看看数据表现" → monitoring（绩效监控）
- "做一个落地页" → web（Web部署）

优先级规则：
- research 在需要数据支撑其他决策时优先调度
- web 在需要部署产品或营销资产时作为后续任务

【任务要求】
请按以下步骤进行分析：

**第1步：推理过程生成**
- 分析用户query的核心诉求
- 识别query中的关键实体和意图信号
- 判断是否需要结合对话历史进行消歧
- 说明如何融合上下文信息进行推理

**第2步：多意图识别（原因）**
- 识别所有可能的用户意图（可以是多个）
- 为每个意图分配置信度（0-1之间）
- 说明为什么识别出该意图的原因

**第3步：智能Query改写**
- 识别口语化表达，进行标准化
- 补全省略的上下文信息
- 提取和重组关键信息

**第4步：构建结构化决策**
- 基于识别的意图，决定调用哪些子智能体
- 说明调用顺序和优先级
- 输出结构化的调用策略

【输出格式要求】
必须严格按照以下JSON格式输出（**只输出JSON，不要有其他文本**）：

{{
    "reasoning": "这里是详细的推理过程，包含第1步的分析，说明如何理解用户query，如何结合上下文，如何识别意图信号",

    "intents": [
        {{
            "type": "意图类型（如：research, marketing, product, sales, monitoring, web）",
            "confidence": 0.95,
            "description": "该意图的具体说明",
            "reason": "为什么识别出该意图的原因"
        }}
    ],

    "key_entities": {{
        "industry": "行业领域（如果有）",
        "product_type": "产品类型（如果有）",
        "target_market": "目标市场（如果有）",
        "action": "具体操作（如果有）",
        "other": "其他关键信息"
    }},

    "rewritten_query": "标准化、补全后的查询内容",

    "agent_schedule": [
        {{
            "agent_name": "子智能体名称",
            "priority": 1,
            "reason": "调用该智能体的原因和依据",
            "expected_output": "期望该智能体提供什么输出"
        }}
    ]
}}

【重要提示 - 优先级设置规则】
优先级数字相同的智能体会**并行执行**，不同优先级按顺序批次执行。

**所有智能体优先级分组：**

**Priority 1（并行执行）- 信息收集与分析类：**
- research: 市场调研智能体
- monitoring: 绩效监控智能体
- sales: 销售执行智能体

**Priority 2（依赖 Priority 1）- 策略生成类：**
- marketing: 营销策略智能体（可能需要 research 的结果）
- product: 产品规划智能体（可能需要 research 的结果）

**Priority 3（依赖 Priority 2）- 执行部署类：**
- web: Web部署智能体（需要 product/marketing 的结果）

**说明：**
- Priority 1 的智能体都是信息获取，互不依赖，可并行执行提升速度
- Priority 2 的智能体需要使用 Priority 1 收集的信息
- Priority 3 的智能体需要使用前两步的结果
- 示例：用户说"帮我调研一下AI教育市场，然后做一个产品方案"
  → Priority 1: research（并行）
  → Priority 2: product（使用 Priority 1 的结果）

请开始分析，直接输出JSON：
"""

        # 默认结果（LLM调用失败时兜底）
        default_result = {
            "reasoning": "意图识别出错，使用默认策略。",
            "intents": [
                {
                    "type": "research",
                    "confidence": 0.5,
                    "description": "默认查询意图",
                    "reason": "无法解析用户意图，使用默认策略"
                }
            ],
            "key_entities": {},
            "rewritten_query": user_query,
            "agent_schedule": [
                {
                    "agent_name": "research",
                    "priority": 1,
                    "reason": "默认查询",
                    "expected_output": "查询结果"
                }
            ]
        }

        # 调用LLM进行意图识别
        try:
            messages = [
                {"role": "system", "content": "你是一个高级意图识别专家。只输出JSON格式的结果，不要输出其他文本。"},
                {"role": "user", "content": prompt}
            ]
            response = await self.model(messages)

            text = await extract_json_from_async_response(response)
            result = robust_json_parse(text, fallback=default_result)

        except Exception as e:
            logger.error(f"Intent recognition failed: {e}")
            result = default_result

        # 将结果转换为JSON字符串，因为Msg的content必须是字符串
        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")
