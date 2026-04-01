"""
Web部署智能体 WebAgent
职责：基于产品信息生成 Lovable 链接，用户点击后自动生成落地页
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List
import json
import logging
import sys
import os
from urllib.parse import quote

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))


logger = logging.getLogger(__name__)


class WebAgent(AgentBase):
    """Web部署智能体 - 通过 Lovable Build-with-URL 生成落地页"""

    def __init__(self, name: str = "WebAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        from utils.skill_loader import SkillLoader
        self.skill_loader = SkillLoader()

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content=json.dumps({"status": "error", "error": "No input"}), role="assistant")

        content = x.content if not isinstance(x, list) else x[-1].content

        user_query = ""
        context_info = {}
        previous_results = []

        if isinstance(content, str):
            try:
                data = json.loads(content)
                context_info = data.get("context", {})
                user_query = context_info.get("rewritten_query", "")
                previous_results = data.get("previous_results", [])
            except json.JSONDecodeError:
                user_query = content
        elif isinstance(content, dict):
            context_info = content
            user_query = content.get("rewritten_query", str(content))

        # 收集所有上下文信息（产品规划、营销策略等）
        all_info = {
            "user_query": user_query,
        }
        for prev in previous_results:
            agent_name = prev.get("agent_name", "")
            result_data = prev.get("result", {}).get("data", {})
            if result_data and agent_name:
                all_info[agent_name] = result_data

        # 让 LLM 生成 Lovable 的详细 prompt
        lovable_prompt = await self._generate_lovable_prompt(user_query, all_info)

        # 构建 Lovable URL
        encoded_prompt = quote(lovable_prompt, safe='')
        lovable_url = f"https://lovable.dev/?autosubmit=true#prompt={encoded_prompt}"

        result = {
            "status": "success",
            "lovable_url": lovable_url,
            "lovable_prompt": lovable_prompt,
            "deployment": {
                "method": "Lovable 自动生成",
                "instructions": "点击上方链接，Lovable 将自动为您生成并部署落地页。登录后选择工作区即可开始。",
                "platforms": ["Lovable (自动托管)", "可导出至 Vercel / Netlify"],
            },
        }

        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

    async def _generate_lovable_prompt(self, user_query: str, all_info: dict) -> str:
        """让 LLM 基于产品信息生成给 Lovable 的详细 prompt"""

        skill_instruction = self.skill_loader.get_skill_content("web")
        if not skill_instruction:
            skill_instruction = "生成一个专业的落地页。"

        prompt = f"""你是一个产品落地页设计专家。你的任务是生成一段给 Lovable（AI网页生成工具）的 prompt，让 Lovable 自动创建一个专业的落地页。

【用户需求】
{user_query}

【已有的产品/营销信息】
{json.dumps(all_info, ensure_ascii=False, indent=2)}

【要求】
1. 输出一段**纯文本 prompt**（不是JSON，不是HTML），直接描述你希望 Lovable 生成的落地页
2. prompt 要详细描述：页面结构、设计风格、配色方案、各section内容、CTA按钮文案
3. 把已有的产品信息（产品名、功能、定价、目标用户）融入 prompt
4. 使用中文描述，但指定页面语言为中文
5. prompt 长度控制在 2000 字以内
6. 不要输出任何 JSON 或代码，只输出纯文本 prompt

直接输出 prompt 内容，不要有任何前缀或说明："""

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

            return text.strip() if text else f"Create a professional landing page for: {user_query}"

        except Exception as e:
            logger.error(f"Failed to generate Lovable prompt: {e}")
            return f"Create a professional Chinese landing page for the following product: {user_query}"
