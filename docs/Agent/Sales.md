# 销售执行智能体 (SalesAgent)

**源文件**: `.claude/skills/sales/script/agent.py`
**技能描述**: `.claude/skills/sales/SKILL.md`

## 概述

SalesAgent 负责客户发现、潜在客户研究、外展方案生成和线索评估。它不接入外部 API 或数据库，完全依赖 LLM 基于用户查询和项目偏好生成销售策略。SKILL.md 中定义了严格的 JSON 输出格式，LLM 需按该格式返回结构化的销售方案。

## 在系统中的位置

```
OrchestrationAgent
  → 构建 input_msg（包含 context、reason、expected_output、previous_results）
  → SalesAgent.reply(input_msg)
  → 返回销售方案 JSON
```

SalesAgent 属于 Priority 1（信息收集类），与 research、monitoring 并行执行。

## 依赖组件

- **SkillLoader**（`utils/skill_loader.py`）：读取 SKILL.md 中的销售执行指南和输出格式定义
- **LLM 模型**（`self.model`）：生成销售策略

---

## 类: `SalesAgent(AgentBase)`

### `__init__(self, name: str = "SalesAgent", model=None, **kwargs)`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | `str` | `"SalesAgent"` | Agent 名称 |
| `model` | 可调用对象 | `None` | LLM 模型实例 |

**内部状态**:
- `self.name`, `self.model`
- `self.skill_loader`: `SkillLoader` 实例

**注意**: 与 MonitoringAgent 不同，SalesAgent 不接收 `memory_manager`。但它通过 OrchestrationAgent 传入的 `context.user_preferences` 间接获取项目偏好。

---

### `async reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg`

销售策略生成主流程。

**输入**:

| 参数 | 类型 | 说明 |
|---|---|---|
| `x` | `None` | 返回空字典内容的 Msg |
| `x` | `Msg` | 取 `x.content` |
| `x` | `List[Msg]` | 取最后一条的 `content` |

**实际接收的输入**（由 OrchestrationAgent 构建）:

```json
{
    "context": {
        "reasoning": "...",
        "intents": [...],
        "key_entities": {...},
        "rewritten_query": "为AI教育SaaS产品寻找潜在客户",
        "recent_dialogue": [...],
        "user_preferences": {
            "target_market": "B2B SaaS",
            "product_type": "AI教育平台",
            "industry": "教育科技"
        }
    },
    "reason": "...",
    "expected_output": "...",
    "previous_results": [...]
}
```

**输出**: `Msg(name=self.name, content=json_string, role="assistant")`

成功时（由 SKILL.md 定义的格式）:
```json
{
    "prospects": {
        "target_profile": "目标客户画像",
        "channels": ["获客渠道1", "获客渠道2"],
        "potential_customers": [
            {
                "type": "客户类型",
                "description": "客户描述",
                "approach": "接触方式"
            }
        ]
    },
    "outreach_plan": {
        "email_template": "邮件模板",
        "pitch": "电梯演讲稿",
        "follow_up": "跟进策略"
    }
}
```

失败时:
```json
{
    "error": "错误信息"
}
```

**内部逻辑**:

#### 1. 解析输入，提取查询和偏好

从 `content` 中尝试 JSON 解析：
- **成功**: 取 `context.rewritten_query` 作为查询，取 `context.user_preferences` 作为偏好。若 `rewritten_query` 为空，回退到 `str(data)` 整个 JSON 字符串。
- **失败**: 用原始 `content` 字符串作为查询，偏好为空字典。

#### 2. 构建项目背景信息

从 `user_preferences` 中提取三个字段拼接为背景文本：
- `target_market` → `目标市场`
- `product_type` → `产品类型`
- `industry` → `行业领域`

若三个字段都为空则不添加背景信息。

#### 3. 构建 Prompt 并调用 LLM

Prompt 包含：
- 项目背景信息（若有）
- 用户需求（rewritten_query）
- SKILL.md 中的任务说明和输出格式要求

LLM 调用（无 system message）：
```python
response = await self.model([
    {"role": "user", "content": prompt}
])
```

**注意**: 与其他 agent 不同，SalesAgent 没有传 `system` role 消息。

#### 4. 解析 LLM 响应

1. 处理多种返回格式（异步生成器、`.text`、`.content`、字典），提取文本。
2. 清理 markdown 代码块标记（```` ```json ```  ````）。
3. 查找第一个 `{` 和最后一个 `}` 之间的文本，尝试 `json.loads()` 解析。
4. 若找不到 JSON 或解析失败，抛出 `ValueError`。

**注意**: SalesAgent 自己实现了简单的 JSON 提取逻辑，没有复用 `utils/json_parser.py` 中的 `robust_json_parse`。因此容错能力较弱——只做了一次直接解析，不支持修复引号、尾部逗号等常见问题。

#### 5. 异常处理

所有异常（包括 LLM 调用失败和 JSON 解析失败）统一捕获，返回 `{"error": str(e)}`。

---

## 与同级 Agent 的对比

| | ResearchAgent | MonitoringAgent | SalesAgent |
|---|---|---|---|
| 外部 API | Tavily | 无 | 无 |
| 记忆依赖 | 无 | `memory_manager` | 间接（通过 context） |
| JSON 解析 | `robust_json_parse`（6 层容错） | 不解析（返回纯文本） | 自实现（单层） |
| LLM system message | 无 | 有 | 无 |
| 输出格式 | 自定义 | 自定义 | SKILL.md 定义的严格 JSON |

---

## 设计要点

- **纯 LLM 生成**: 没有真实的客户数据库或 CRM 接入，所有销售策略由 LLM 基于描述生成。
- **偏好间接传递**: 不直接持有 `memory_manager`，而是通过 OrchestrationAgent 在 `context.user_preferences` 中传入偏好数据。如果 OrchestrationAgent 未传入偏好，SalesAgent 生成的方案缺少项目背景。
- **JSON 解析容错不足**: 没有复用 `robust_json_parse`，只做一次直接 `json.loads()`。若 LLM 输出的 JSON 有格式问题（尾部逗号、单引号等），会直接失败返回 error。
- **输出格式依赖 LLM 遵守**: SKILL.md 中定义了 `prospects` + `outreach_plan` 的 JSON 结构，但代码中没有校验。LLM 可能输出不符合预期格式的 JSON，OrchestrationAgent 会原样透传。
- **无 previous_results 使用**: 与 ResearchAgent 一样，不使用前序 agent 的结果，符合 P1 无依赖的定位。
