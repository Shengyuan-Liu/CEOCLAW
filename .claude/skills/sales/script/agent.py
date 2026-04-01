"""
销售执行智能体 SalesAgent
职责：客户发现、潜在客户研究、外展方案生成、线索评估
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List
import json
import logging
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

logger = logging.getLogger(__name__)


class SalesAgent(AgentBase):
    """销售执行智能体"""

    def __init__(self, name: str = "SalesAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        from utils.skill_loader import SkillLoader
        self.skill_loader = SkillLoader()

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content={}, role="assistant")

        content = x.content if not isinstance(x, list) else x[-1].content

        if isinstance(content, str):
            try:
                data = json.loads(content)
                context = data.get("context", {})
                user_query = context.get("rewritten_query", "") or str(data)
                user_preferences = context.get("user_preferences", {})
            except json.JSONDecodeError:
                user_query = content
                user_preferences = {}
        else:
            user_query = str(content)
            user_preferences = {}

        # 构建项目背景信息
        background_info = ""
        if user_preferences:
            bg_parts = ["【项目背景信息】（可用于推断目标客户）"]
            if user_preferences.get("target_market"):
                bg_parts.append(f"• 目标市场: {user_preferences['target_market']}")
            if user_preferences.get("product_type"):
                bg_parts.append(f"• 产品类型: {user_preferences['product_type']}")
            if user_preferences.get("industry"):
                bg_parts.append(f"• 行业领域: {user_preferences['industry']}")

            if len(bg_parts) > 1:
                background_info = "\n".join(bg_parts) + "\n\n"

        skill_instruction = self.skill_loader.get_skill_content("sales")
        if not skill_instruction:
            skill_instruction = "请基于产品和市场信息生成销售策略。"

        prompt = f"""你是销售策略专家，负责客户发现和销售执行规划。

{background_info}【用户需求】
{user_query}

【任务说明】
{skill_instruction}

请直接输出JSON：
"""

        try:
            response = await self.model([
                {"role": "user", "content": prompt}
            ])

            text = ""
            if hasattr(response, '__aiter__'):
                async for chunk in response:
                    if isinstance(chunk, str):
                        text = chunk
                    elif hasattr(chunk, 'content'):
                        if isinstance(chunk.content, str):
                            text = chunk.content
                        elif isinstance(chunk.content, list):
                            for item in chunk.content:
                                if isinstance(item, dict) and item.get('type') == 'text':
                                    text = item.get('text', '')
            elif hasattr(response, 'text'):
                text = response.text
            elif hasattr(response, 'content'):
                text = response.content
            elif isinstance(response, dict) and 'content' in response:
                text = response['content']
            else:
                text = str(response) if response else ""

            # 清理文本，移除markdown代码块标记
            text = text.strip()
            if text.startswith('```json'):
                text = text[7:]
            if text.startswith('```'):
                text = text[3:]
            if text.endswith('```'):
                text = text[:-3]
            text = text.strip()

            start_idx = text.find('{')
            end_idx = text.rfind('}')

            if start_idx != -1 and end_idx != -1:
                json_str = text[start_idx:end_idx+1]
                try:
                    result = json.loads(json_str)
                except json.JSONDecodeError as e:
                    logger.error(f"JSON parse failed. Text sample: {json_str[:100]}")
                    raise ValueError(f"Failed to parse JSON. Error: {e}")
            else:
                raise ValueError("No JSON found in response")
        except Exception as e:
            logger.error(f"Sales execution failed: {e}")
            result = {"error": str(e)}

        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")
