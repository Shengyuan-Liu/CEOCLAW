"""
绩效监控智能体 MonitoringAgent
职责：追踪和分析业务指标（流量、注册、收入、ROI）
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List, Dict
import json
import logging
import sys
import os

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

logger = logging.getLogger(__name__)


class MonitoringAgent(AgentBase):
    """绩效监控智能体 - 基于长期记忆分析业务指标"""

    def __init__(
        self,
        name: str = "MonitoringAgent",
        model=None,
        memory_manager=None,
        **kwargs
    ):
        super().__init__()
        self.name = name
        self.model = model
        self.memory_manager = memory_manager
        from utils.skill_loader import SkillLoader
        self.skill_loader = SkillLoader()

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content=json.dumps({}), role="assistant")

        # 解析输入
        if isinstance(x, list):
            input_content = x[-1].content if x else "{}"
        else:
            input_content = x.content

        try:
            input_data = json.loads(input_content) if isinstance(input_content, str) else input_content
        except json.JSONDecodeError:
            input_data = {"context": {"rewritten_query": str(input_content)}}

        context = input_data.get("context", {})
        user_query = context.get("rewritten_query", "")
        if not user_query:
            recent_dialogue = context.get("recent_dialogue", [])
            if recent_dialogue:
                for msg in reversed(recent_dialogue):
                    if msg.get("role") == "user":
                        user_query = msg.get("content", "")
                        break

        if not user_query:
            return Msg(
                name=self.name,
                content=json.dumps({
                    "status": "error",
                    "message": "无法获取用户查询"
                }),
                role="assistant"
            )

        # 获取长期记忆中的项目历史
        project_history = []
        preferences = {}

        if self.memory_manager:
            project_history = self.memory_manager.long_term.get_project_history(limit=50)
            preferences = self.memory_manager.long_term.get_preference()

        # 格式化项目历史
        history_text = self._format_project_history(project_history)
        pref_text = self._format_preferences(preferences)

        skill_instruction = self.skill_loader.get_skill_content("monitoring")
        if not skill_instruction:
            skill_instruction = "请基于项目历史数据进行绩效分析。"

        prompt = f"""你是一个业务数据分析专家，请基于项目历史数据进行分析。

【用户问题】
{user_query}

【项目历史记录】
{history_text}

【项目偏好设置】
{pref_text}

【任务说明】
{skill_instruction}
"""

        try:
            response = await self.model([
                {"role": "system", "content": "你是一个业务数据分析专家，帮助创始人监控和分析业务指标。"},
                {"role": "user", "content": prompt}
            ])

            answer = ""
            if hasattr(response, '__aiter__'):
                async for chunk in response:
                    if isinstance(chunk, str):
                        answer = chunk
                    elif hasattr(chunk, 'content'):
                        if isinstance(chunk.content, str):
                            answer = chunk.content
                        elif isinstance(chunk.content, list):
                            for item in chunk.content:
                                if isinstance(item, dict) and item.get('type') == 'text':
                                    answer = item.get('text', '')
            elif hasattr(response, 'text'):
                answer = response.text
            elif hasattr(response, 'content'):
                answer = response.content
            elif isinstance(response, dict) and 'content' in response:
                answer = response['content']
            else:
                answer = str(response) if response else "无法生成分析"

            if not answer:
                answer = "无法基于现有数据生成分析"

            result = {
                "status": "success",
                "query": user_query,
                "answer": answer,
                "data_sources": {
                    "project_count": len(project_history),
                    "has_preferences": any(v for v in preferences.values() if v),
                }
            }

            return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

        except Exception as e:
            logger.error(f"Monitoring analysis failed: {e}")
            return Msg(
                name=self.name,
                content=json.dumps({
                    "status": "error",
                    "message": f"绩效分析失败: {str(e)}",
                    "query": user_query
                }),
                role="assistant"
            )

    def _format_project_history(self, project_history: List[Dict]) -> str:
        """格式化项目历史"""
        if not project_history:
            return "（暂无项目记录）"

        lines = []
        for i, record in enumerate(project_history, 1):
            action_type = record.get("action_type", "未知")
            description = record.get("description", "")
            timestamp = record.get("timestamp", "")
            lines.append(f"{i}. [{timestamp}] {action_type}: {description}")

        return "\n".join(lines)

    def _format_preferences(self, preferences: Dict) -> str:
        """格式化项目偏好"""
        if not preferences or not any(v for v in preferences.values() if v):
            return "（暂无偏好记录）"

        lines = []
        for key, value in preferences.items():
            if value:
                lines.append(f"- {key}: {value}")

        return "\n".join(lines) if lines else "（暂无偏好记录）"
