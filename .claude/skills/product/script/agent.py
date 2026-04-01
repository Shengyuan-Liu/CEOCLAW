"""
产品规划智能体 ProductAgent
职责：产品策略生成、功能规划、产品迭代
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List, Dict, Any
import json
import logging
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

from utils.json_parser import robust_json_parse_with_llm, extract_json_from_async_response

logger = logging.getLogger(__name__)


class ProductAgent(AgentBase):
    """产品规划智能体"""

    def __init__(self, name: str = "ProductAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        from utils.skill_loader import SkillLoader
        self.skill_loader = SkillLoader()

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content={}, role="assistant")

        content = x.content if not isinstance(x, list) else x[-1].content

        user_query = ""
        context_info = {}
        previous_results = []
        user_preferences = {}

        if isinstance(content, str):
            try:
                data = json.loads(content)
                context_info = data.get("context", {})
                user_query = context_info.get("rewritten_query", "")
                previous_results = data.get("previous_results", [])
                user_preferences = context_info.get("user_preferences", {})
            except json.JSONDecodeError:
                user_query = content
        elif isinstance(content, dict):
            context_info = content
            user_query = content.get("rewritten_query", str(content))
            user_preferences = content.get("user_preferences", {})

        all_info = {
            "user_query": user_query,
            "context": context_info,
        }

        for prev in previous_results:
            agent_name = prev.get("agent_name", "")
            result_data = prev.get("result", {}).get("data", {})
            if result_data and agent_name:
                all_info[agent_name] = result_data

        skill_instruction = self.skill_loader.get_skill_content("product")
        if not skill_instruction:
            skill_instruction = "请根据用户需求生成产品规划。"

        from datetime import datetime
        current_date = datetime.now().strftime("%Y年%m月%d日")

        prompt = f"""你是一个高级产品经理和创业顾问。

【当前时间】
{current_date}

【用户需求】
{user_query}

【所有收集的信息】
{json.dumps(all_info, ensure_ascii=False, indent=2)}

【任务说明与指南】
{skill_instruction}

请直接输出 JSON 格式的产品规划。
"""

        try:
            response = await self.model([
                {"role": "user", "content": prompt}
            ])

            text = await extract_json_from_async_response(response)

            result = await robust_json_parse_with_llm(text, self.model, fallback=None)
            if result is None:
                raise ValueError("Parsed result is None")

        except Exception as e:
            logger.error(f"Product planning failed: {e}")
            result = {
                "product_plan": {
                    "name": "产品规划",
                    "vision": "待完善",
                    "features": [],
                    "roadmap": []
                },
                "error": str(e)
            }

        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")
