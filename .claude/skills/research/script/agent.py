"""
调研智能体 ResearchAgent
职责：市场调研、竞品分析、创意验证

核心功能：
- 市场调研 - 使用 Tavily 搜索市场数据
- 竞品分析 - 搜索并分析竞争对手
- 创意验证 - 搜索相关数据验证商业想法
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

logger = logging.getLogger(__name__)

# Tavily API key: 优先从环境变量读取，其次使用默认值
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "tvly-dev-x")

try:
    from tavily import AsyncTavilyClient
    TAVILY_AVAILABLE = True
except ImportError:
    TAVILY_AVAILABLE = False
    logger.warning("tavily-python not installed. Install with: pip install tavily-python")


class ResearchAgent(AgentBase):
    """
    调研智能体

    核心功能：
    - 市场调研 - 使用 Tavily 搜索市场数据
    - 竞品分析 - 搜索并分析竞争对手信息
    - 创意验证 - 基于搜索结果验证商业想法
    """

    def __init__(self, name: str = "ResearchAgent", model=None, **kwargs):
        super().__init__()
        self.name = name
        self.model = model
        from utils.skill_loader import SkillLoader
        self.skill_loader = SkillLoader()
        if TAVILY_AVAILABLE:
            self.tavily_client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
        else:
            self.tavily_client = None

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        if x is None:
            return Msg(name=self.name, content=json.dumps({"query_success": False}), role="assistant")

        # 解析输入
        content = x.content if not isinstance(x, list) else x[-1].content

        if isinstance(content, str):
            try:
                data = json.loads(content)
                context = data.get("context", {})
                user_query = context.get("rewritten_query", "") or content
            except json.JSONDecodeError:
                user_query = content
        else:
            user_query = str(content)

        # 执行网络搜索
        logger.info(f"Research query: {user_query}")
        try:
            result = await self._web_search(user_query)
        except Exception as e:
            logger.error(f"Research failed: {e}")
            result = {
                "status": "error",
                "findings": "",
                "results": {"error": str(e)},
            }

        return Msg(name=self.name, content=json.dumps(result, ensure_ascii=False), role="assistant")

    async def _web_search(self, query: str) -> Dict[str, Any]:
        """使用 Tavily 进行网络搜索"""
        if not TAVILY_AVAILABLE or not self.tavily_client:
            return {
                "status": "error",
                "findings": "",
                "results": {
                    "message": "Tavily 搜索库未安装",
                    "note": "请运行：pip install tavily-python",
                },
            }

        try:
            # 使用 Tavily advanced 搜索获取高质量结果
            response = await self.tavily_client.search(
                query=query,
                search_depth="advanced",
                max_results=8,
                include_answer=True,
            )

            tavily_results = response.get("results", [])
            tavily_answer = response.get("answer", "")

            if not tavily_results:
                return {
                    "status": "error",
                    "findings": "",
                    "results": {"message": "未找到相关结果"},
                }

            # 过滤低相关性结果（Tavily 提供 score 字段）
            results = []
            for item in tavily_results:
                score = item.get("score", 0)
                if score < 0.3:
                    logger.debug(f"Filtered low-relevance result (score={score}): {item.get('title', '')[:50]}")
                    continue
                results.append({
                    "title": item.get("title", ""),
                    "snippet": item.get("content", ""),
                    "url": item.get("url", ""),
                    "score": score,
                    "published_date": item.get("published_date", ""),
                })

            if not results:
                return {
                    "status": "error",
                    "findings": tavily_answer or "",
                    "results": {"message": "搜索结果相关性不足"},
                }

            # 使用 LLM 总结搜索结果
            summary = await self._summarize_research(query, results, tavily_answer)

            return {
                "status": "success",
                "findings": summary,
                "results": {
                    "summary": summary,
                    "sources": results,
                },
            }
        except Exception as e:
            logger.error(f"Tavily search failed: {e}")
            return {
                "status": "error",
                "findings": "",
                "results": {"error": f"搜索失败: {str(e)}"},
            }

    async def _summarize_research(self, query: str, results: List[Dict], tavily_answer: str = "") -> str:
        """使用 LLM 总结调研结果"""
        if not results:
            return "未找到相关信息"

        results_text = ""
        for i, result in enumerate(results, 1):
            date_info = f" ({result['published_date']})" if result.get('published_date') else ""
            results_text += f"\n{i}. [{result['title']}]{date_info}\n{result['snippet']}\n来源: {result['url']}\n"

        from datetime import datetime
        current_date = datetime.now().strftime("%Y年%m月%d日")

        skill_instruction = self.skill_loader.get_skill_content("research")
        if not skill_instruction:
            skill_instruction = "请基于搜索结果进行专业的市场分析。"

        tavily_context = ""
        if tavily_answer:
            tavily_context = f"\n【AI 搜索摘要】\n{tavily_answer}\n"

        prompt = f"""根据以下搜索结果，为用户提供专业的调研分析报告。

【当前时间】
{current_date}

【调研问题】
{query}
{tavily_context}
【搜索结果】
{results_text}

【任务说明】
{skill_instruction}
"""

        try:
            response = await self.model([{"role": "user", "content": prompt}])

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

            return text.strip() if text else "无法生成调研摘要"
        except Exception as e:
            logger.error(f"Summarization failed: {e}")
            return "搜索成功，但调研摘要生成失败"
