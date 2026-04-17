# 绩效监控智能体 (MonitoringAgent)

**源文件**: `.claude/skills/monitoring/script/agent.py`
**技能描述**: `.claude/skills/monitoring/SKILL.md`

## 概述

MonitoringAgent 负责追踪和分析业务指标（流量、注册、收入、ROI 等）。与 ResearchAgent 不同，它**不做网络搜索**，而是从长期记忆中读取项目历史记录和偏好设置，将其作为上下文交给 LLM 进行分析。本质上是一个"基于已有数据的 LLM 分析器"。

## 在系统中的位置

```
OrchestrationAgent
  → 构建 input_msg（包含 context、reason、expected_output、previous_results）
  → MonitoringAgent.reply(input_msg)
  → 返回分析结果 JSON
```

MonitoringAgent 属于 Priority 1（信息收集类），与 research、sales 并行执行。

## 依赖组件

- **MemoryManager**（`context/memory_manager.py`）：通过 `memory_manager.long_term` 读取项目历史和偏好
- **SkillLoader**（`utils/skill_loader.py`）：读取 SKILL.md 中的监控分析指南
- **LLM 模型**（`self.model`）：基于历史数据生成分析报告

---

## 类: `MonitoringAgent(AgentBase)`

### `__init__(self, name: str = "MonitoringAgent", model=None, memory_manager=None, **kwargs)`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | `str` | `"MonitoringAgent"` | Agent 名称 |
| `model` | 可调用对象 | `None` | LLM 模型实例 |
| `memory_manager` | `MemoryManager` | `None` | 记忆管理器，用于读取长期记忆 |

**内部状态**:
- `self.name`, `self.model`, `self.memory_manager`
- `self.skill_loader`: `SkillLoader` 实例

**注意**: 与 ResearchAgent 不同，MonitoringAgent 在构造时接收 `memory_manager`，因为它需要直接读取长期记忆。ResearchAgent 不需要记忆，只依赖搜索 API。

---

### `async reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg`

绩效分析主流程。读取长期记忆中的项目数据，调用 LLM 生成分析报告。

**输入**:

| 参数 | 类型 | 说明 |
|---|---|---|
| `x` | `None` | 返回空 JSON 的 Msg |
| `x` | `Msg` | 取 `x.content` |
| `x` | `List[Msg]` | 取最后一条的 `content` |

**实际接收的输入**（由 OrchestrationAgent 构建，同 ResearchAgent）:

```json
{
    "context": {
        "reasoning": "...",
        "intents": [...],
        "key_entities": {...},
        "rewritten_query": "分析最近的业务数据表现",
        "recent_dialogue": [{"role": "user", "content": "..."}],
        "user_preferences": {...}
    },
    "reason": "...",
    "expected_output": "...",
    "previous_results": [...]
}
```

**输出**: `Msg(name=self.name, content=json_string, role="assistant")`

成功时：
```json
{
    "status": "success",
    "query": "用户查询文本",
    "answer": "LLM 生成的分析报告文本",
    "data_sources": {
        "project_count": 5,
        "has_preferences": true
    }
}
```

失败时：
```json
{
    "status": "error",
    "message": "错误信息",
    "query": "用户查询文本"
}
```

**内部逻辑**:

#### 1. 解析输入，提取用户查询

优先级链：
1. `context.rewritten_query` — IntentionAgent 改写后的查询
2. `context.recent_dialogue` 中最后一条 `role="user"` 的消息 — 从对话历史中回溯
3. 若都取不到，返回 error：`"无法获取用户查询"`

#### 2. 读取长期记忆

从 `self.memory_manager.long_term` 获取：
- `get_project_history(limit=50)` — 最近 50 条项目决策记录
- `get_preference()` — 所有项目偏好

若 `memory_manager` 为 `None`，两者均为空。

#### 3. 格式化数据

- 项目历史通过 `_format_project_history()` 格式化
- 偏好通过 `_format_preferences()` 格式化

#### 4. 构建 Prompt 并调用 LLM

Prompt 包含：
- 用户问题
- 项目历史记录（格式化文本）
- 项目偏好设置（格式化文本）
- SKILL.md 中的任务说明

LLM 调用：
```python
response = await self.model([
    {"role": "system", "content": "你是一个业务数据分析专家，帮助创始人监控和分析业务指标。"},
    {"role": "user", "content": prompt}
])
```

#### 5. 解析响应并返回

处理多种 LLM 返回格式（异步生成器、`.text`、`.content`、字典），提取分析文本。返回结果包含 `data_sources` 元数据，标注使用了多少条项目记录和是否有偏好数据。

---

### `_format_project_history(self, project_history: List[Dict]) -> str`

将项目历史记录格式化为文本。

**输入**:

| 参数 | 类型 | 说明 |
|---|---|---|
| `project_history` | `List[Dict]` | 项目决策记录列表 |

**输出**: `str` — 格式化文本，空时返回 `"（暂无项目记录）"`。

**格式**:
```
1. [2026-04-04T10:00:00] research: AI教育市场调研完成
2. [2026-04-04T11:00:00] product_planning: 制定了MVP产品方案
```

---

### `_format_preferences(self, preferences: Dict) -> str`

将项目偏好格式化为文本。

**输入**:

| 参数 | 类型 | 说明 |
|---|---|---|
| `preferences` | `Dict` | 偏好字典 `{type: value}` |

**输出**: `str` — 格式化文本，空或全为空值时返回 `"（暂无偏好记录）"`。

**格式**:
```
- target_market: B2B SaaS
- tech_stack: Python + React
```

---

## 与 ResearchAgent 的对比

| | ResearchAgent | MonitoringAgent |
|---|---|---|
| 数据来源 | Tavily 网络搜索（实时外部数据） | 长期记忆（历史内部数据） |
| 构造参数 | `model` | `model` + `memory_manager` |
| LLM 调用次数 | 1 次（总结搜索结果） | 1 次（分析历史数据） |
| 外部 API | Tavily Search API | 无 |
| 无数据时表现 | 搜索无结果返回 error | 传入 "暂无项目记录" 让 LLM 回答 |

---

## 设计要点

- **纯 LLM 分析**: 没有真实的数据监控系统接入，所有"数据"来自长期记忆中的项目历史文本。LLM 实际上是在基于文本描述做推理，而非分析结构化指标数据。
- **数据量上限**: 读取最近 50 条项目历史。若项目历史条数多且每条 `description` 较长，prompt 可能会很大。
- **Query 回退链**: 先取 `rewritten_query`，取不到再从 `recent_dialogue` 回溯找用户消息，保证尽可能获取到查询意图。
- **memory_manager 可选**: 若未传入，项目历史和偏好均为空，LLM 会基于空数据回答（可能给出通用建议）。
- **SKILL.md 注入**: 分析风格由 SKILL.md 正文控制，要求客观分析、识别趋势异常、给出可操作建议。
