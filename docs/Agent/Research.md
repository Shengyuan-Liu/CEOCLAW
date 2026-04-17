# 调研智能体 (ResearchAgent)

**源文件**: `.claude/skills/research/script/agent.py`
**技能描述**: `.claude/skills/research/SKILL.md`

## 概述

ResearchAgent 负责市场调研、竞品分析和创意验证。它通过 Tavily Search API 执行网络搜索获取实时数据，然后用 LLM 对搜索结果进行总结，生成结构化的调研报告。

## 在系统中的位置

```
OrchestrationAgent
  → 构建 input_msg（包含 context、reason、expected_output、previous_results）
  → ResearchAgent.reply(input_msg)
  → 返回调研结果 JSON
```

ResearchAgent 属于 Priority 1（信息收集类），与 monitoring、sales 并行执行，不依赖其他 agent 的输出。其结果会被 Priority 2 的 marketing、product agent 使用。

## 依赖组件

- **Tavily Search API**（`tavily-python`）：网络搜索，需要 `TAVILY_API_KEY` 环境变量或代码内默认值
- **SkillLoader**（`utils/skill_loader.py`）：读取 SKILL.md 中的调研生成指南，注入 LLM 总结 prompt
- **LLM 模型**（`self.model`）：对搜索结果做总结分析

---

## 类: `ResearchAgent(AgentBase)`

### `__init__(self, name: str = "ResearchAgent", model=None, **kwargs)`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | `str` | `"ResearchAgent"` | Agent 名称 |
| `model` | 可调用对象 | `None` | LLM 模型实例 |

**内部状态**:
- `self.name`, `self.model`
- `self.skill_loader`: `SkillLoader` 实例
- `self.tavily_client`: `AsyncTavilyClient` 实例（若 `tavily-python` 已安装），否则为 `None`

**Tavily API Key 优先级**:
1. 环境变量 `TAVILY_API_KEY`
2. 代码内硬编码的默认值

---

### `async reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg`

调研主流程。接收查询输入，执行网络搜索，返回调研结果。

**输入**:

| 参数 | 类型 | 说明 |
|---|---|---|
| `x` | `None` | 返回 `{"query_success": false}` |
| `x` | `Msg` | 取 `x.content` |
| `x` | `List[Msg]` | 取最后一条的 `content` |

**实际接收的输入**（由 `OrchestrationAgent._execute_agent()` 构建）:

```json
{
    "context": {
        "reasoning": "IntentionAgent 的推理过程",
        "intents": [...],
        "key_entities": {...},
        "rewritten_query": "标准化后的查询",
        "recent_dialogue": [...],
        "user_preferences": {...}
    },
    "reason": "调用该智能体的原因",
    "expected_output": "期望输出",
    "previous_results": [...]
}
```

**输出**: `Msg(name=self.name, content=json_string, role="assistant")`

成功时：
```json
{
    "status": "success",
    "findings": "LLM 生成的调研摘要文本",
    "results": {
        "summary": "同 findings",
        "sources": [
            {
                "title": "文章标题",
                "snippet": "内容摘要",
                "url": "https://...",
                "score": 0.85,
                "published_date": "2026-04-01"
            }
        ]
    }
}
```

失败时：
```json
{
    "status": "error",
    "findings": "",
    "results": {"error": "错误信息"}
}
```

**内部逻辑**:

1. **解析输入**: 从 `content` 中尝试 JSON 解析，提取 `context.rewritten_query` 作为搜索查询。若解析失败，用原始 `content` 字符串作为查询。
2. **执行搜索**: 调用 `self._web_search(user_query)`。
3. **异常处理**: 搜索失败时返回 error 状态，`findings` 为空字符串。

---

### `async _web_search(self, query: str) -> Dict[str, Any]`

使用 Tavily API 执行网络搜索并用 LLM 总结结果。

**输入**:

| 参数 | 类型 | 说明 |
|---|---|---|
| `query` | `str` | 搜索查询文本 |

**输出**: `Dict[str, Any]` — 同 `reply()` 输出的 JSON 结构。

**逻辑**:

1. **前置检查**: 若 Tavily 未安装或客户端为 `None`，返回 error 并提示安装。

2. **调用 Tavily 搜索**:
   ```python
   response = await self.tavily_client.search(
       query=query,
       search_depth="advanced",    # 使用深度搜索模式
       max_results=8,              # 最多返回 8 条结果
       include_answer=True,        # 让 Tavily 生成一个 AI 摘要
   )
   ```

3. **过滤低相关性结果**: 遍历 `response["results"]`，过滤掉 `score < 0.3` 的结果。保留的字段：`title`、`snippet`（原始字段名 `content`）、`url`、`score`、`published_date`。

4. **空结果处理**:
   - 搜索无结果：返回 error，`findings` 为空。
   - 过滤后无结果：返回 error，`findings` 为 Tavily 的 AI 摘要（若有）。

5. **LLM 总结**: 调用 `self._summarize_research(query, results, tavily_answer)` 生成调研报告。

6. **返回结果**: 组装 `status`、`findings`（LLM 总结）、`results.summary`（同 findings）、`results.sources`（原始搜索结果列表）。

---

### `async _summarize_research(self, query: str, results: List[Dict], tavily_answer: str = "") -> str`

使用 LLM 对搜索结果进行总结分析，生成调研报告。

**输入**:

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | `str` | (必填) | 原始搜索查询 |
| `results` | `List[Dict]` | (必填) | 过滤后的搜索结果列表 |
| `tavily_answer` | `str` | `""` | Tavily 生成的 AI 摘要 |

**输出**: `str` — LLM 生成的调研分析文本。失败时返回兜底文本。

**逻辑**:

1. **空结果检查**: 若 `results` 为空，返回 `"未找到相关信息"`。

2. **格式化搜索结果**: 将每条结果拼接为文本：
   ```
   1. [文章标题] (2026-04-01)
   内容摘要...
   来源: https://...
   ```

3. **加载 SKILL.md 指令**: 通过 `self.skill_loader.get_skill_content("research")` 获取 SKILL.md 中 frontmatter 之后的正文内容（调研生成指南）。若加载失败，使用默认指令 `"请基于搜索结果进行专业的市场分析。"`。

4. **构建 Prompt**: 包含以下部分：
   - 当前日期
   - 调研问题（原始 query）
   - AI 搜索摘要（Tavily answer，若有）
   - 搜索结果（格式化后的全部结果）
   - 任务说明（来自 SKILL.md）

5. **调用 LLM**:
   ```python
   response = await self.model([{"role": "user", "content": prompt}])
   ```

6. **解析响应**: 处理多种返回格式（异步生成器、`.text`、`.content`、字典、字符串），提取最终文本。

7. **兜底**:
   - LLM 返回空文本：`"无法生成调研摘要"`
   - LLM 调用异常：`"搜索成功，但调研摘要生成失败"`

---

## 完整调用链示例

用户输入"调研一下AI教育市场"后的完整流程：

```
1. IntentionAgent 识别意图
   → type: "research", rewritten_query: "AI教育市场规模、竞品、趋势分析"

2. OrchestrationAgent 构建 input_msg
   → content: {"context": {"rewritten_query": "AI教育市场..."}, "reason": "...", ...}

3. ResearchAgent.reply(input_msg)
   → 解析出 user_query = "AI教育市场规模、竞品、趋势分析"

4. ResearchAgent._web_search(user_query)
   → Tavily API 返回 8 条结果
   → 过滤掉 score < 0.3 的结果，剩余 5 条

5. ResearchAgent._summarize_research(query, results, tavily_answer)
   → 读取 SKILL.md 中的调研指南
   → LLM 总结搜索结果，生成调研报告

6. 返回 Msg(content={"status": "success", "findings": "调研报告...", "results": {...}})

7. OrchestrationAgent 将结果传给 P2 的 product/marketing agent
   → 同时保存 findings 到长期记忆的 project_history
```

---

## 设计要点

- **两次 LLM 调用**: `reply()` 本身不调用 LLM，但 `_summarize_research()` 会调用一次。加上 IntentionAgent 的调用，一次调研任务总共至少 2 次 LLM 调用 + 1 次 Tavily API 调用。
- **Query 来源**: 优先使用 IntentionAgent 改写后的 `rewritten_query`，而非用户原始输入。这意味着搜索质量依赖意图识别的 Query 改写能力。
- **相关性过滤**: `score < 0.3` 的结果会被丢弃。阈值硬编码，不可配置。
- **SKILL.md 注入**: 调研报告的生成风格由 SKILL.md 正文控制，修改 SKILL.md 可以调整报告格式和要求，无需改代码。
- **Tavily 降级**: 若 `tavily-python` 未安装，整个搜索功能不可用，返回 error 提示安装。不会 fallback 到其他搜索引擎。
- **结果未传递 previous_results**: `reply()` 解析输入时只取 `context.rewritten_query`，没有使用 `previous_results`。即使 OrchestrationAgent 传入了前序 agent 的结果，ResearchAgent 也不会参考。这符合其 P1（无依赖）的定位。
