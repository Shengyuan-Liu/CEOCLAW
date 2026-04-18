# 产品规划智能体 (ProductAgent)

**源文件**: `.claude/skills/product/script/agent.py`
**技能描述**: `.claude/skills/product/SKILL.md`

## 概述

ProductAgent 负责生成产品策略、功能规划、产品迭代方案和定价/UX 优化建议。它与 MarketingAgent 同属 Priority 2，同样会将前序 P1 agent（ResearchAgent、MonitoringAgent、SalesAgent）的输出整合进 prompt，让 LLM 基于调研数据和市场反馈生成有依据的产品规划。

## 在系统中的位置

```
OrchestrationAgent
  → P1: ResearchAgent（调研结果）  ─┐
  → P1: MonitoringAgent（数据分析）─┤ previous_results
  → P1: SalesAgent（销售方案）    ─┘
  → P2: ProductAgent.reply(input_msg)  ← 接收上述结果
  → 返回产品规划 JSON
```

ProductAgent 属于 Priority 2（策略生成类），依赖 P1 的结果。与 MarketingAgent 同优先级，两者并行执行。其输出会被 Priority 3 的 WebAgent 用作落地页生成依据。

## 依赖组件

- **SkillLoader**（`utils/skill_loader.py`）：读取 SKILL.md 中的产品规划指南和输出格式
- **`robust_json_parse_with_llm`**（`utils/json_parser.py`）：鲁棒 JSON 解析，6 层常规容错 + LLM 修复兜底
- **`extract_json_from_async_response`**（`utils/json_parser.py`）：从异步 LLM 响应中提取文本
- **LLM 模型**（`self.model`）：生成产品规划；同时也被 `robust_json_parse_with_llm` 用于修复格式错误的 JSON

---

## 类: `ProductAgent(AgentBase)`

### `__init__(self, name: str = "ProductAgent", model=None, **kwargs)`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | `str` | `"ProductAgent"` | Agent 名称 |
| `model` | 可调用对象 | `None` | LLM 模型实例 |

**内部状态**:
- `self.name`, `self.model`
- `self.skill_loader`: `SkillLoader` 实例

---

### `async reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg`

产品规划生成主流程。

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
        "rewritten_query": "为AI教育产品设计核心功能和路线图",
        "recent_dialogue": [...],
        "user_preferences": {"target_market": "B2B SaaS"}
    },
    "reason": "需要基于调研结果制定产品规划",
    "expected_output": "产品规划方案",
    "previous_results": [
        {
            "agent_name": "research",
            "priority": 1,
            "result": {
                "status": "success",
                "data": {"findings": "AI教育市场规模500亿...", "results": {...}}
            }
        }
    ]
}
```

**输出**: `Msg(name=self.name, content=json_string, role="assistant")`

成功时（由 SKILL.md 定义的格式）:
```json
{
    "product_plan": {
        "name": "产品名称",
        "vision": "产品愿景",
        "target_users": "目标用户",
        "core_value": "核心价值主张",
        "features": [
            {
                "name": "功能名",
                "priority": "P0/P1/P2",
                "description": "功能描述",
                "effort": "开发工作量估算"
            }
        ],
        "roadmap": [
            {
                "phase": "MVP",
                "timeline": "2周",
                "deliverables": ["交付物1", "交付物2"]
            }
        ],
        "tech_stack": "建议技术栈",
        "pricing": "定价策略"
    }
}
```

失败时（兜底结构）:
```json
{
    "product_plan": {
        "name": "产品规划",
        "vision": "待完善",
        "features": [],
        "roadmap": []
    },
    "error": "错误信息"
}
```

**内部逻辑**:

#### 1. 解析输入，提取查询、上下文和前序结果

从 `content` 中尝试 JSON 解析，提取四个信息：
- `user_query`: 来自 `context.rewritten_query`
- `context_info`: 完整的 `context` 字典
- `previous_results`: 前序 agent 的执行结果列表
- `user_preferences`: 来自 `context.user_preferences`

若 `content` 为 `dict` 类型（非字符串），直接从字典中取值。

#### 2. 整合前序 agent 结果

构建 `all_info` 字典，将前序结果按 `agent_name` 展开：

```python
all_info = {
    "user_query": "为AI教育产品设计核心功能和路线图",
    "context": {...},
    "research": {"findings": "...", "results": {...}},    # P1 research 的结果
    "monitoring": {"answer": "...", "data_sources": {...}} # P1 monitoring 的结果（如有）
}
```

遍历 `previous_results`，取每项的 `result.data`，以 `agent_name` 为 key 存入 `all_info`。空结果或无名称的项会被跳过。

#### 3. 构建 Prompt 并调用 LLM

Prompt 包含：
- 角色设定（"你是一个高级产品经理和创业顾问"）
- 当前日期
- 用户需求（`rewritten_query`）
- **所有收集的信息**（`all_info` 序列化为 JSON，含前序 agent 结果）
- SKILL.md 中的产品规划指南和输出格式要求

LLM 调用（无 system message）：
```python
response = await self.model([
    {"role": "user", "content": prompt}
])
```

#### 4. 解析 LLM 响应

两步解析：
1. `extract_json_from_async_response(response)` — 从异步响应中提取文本。
2. `robust_json_parse_with_llm(text, self.model, fallback=None)` — 鲁棒解析，流程为：
   - 先尝试 `robust_json_parse` 的 6 层常规容错（直接解析 → 移除控制字符 → 修复引号 → 移除尾部逗号 → 转义换行 → json5）
   - 全部失败后，用 LLM 修复 JSON 格式（第二次 LLM 调用）
   - LLM 修复也失败时，返回 `None`

若解析结果为 `None`，抛出 `ValueError` 触发兜底。

#### 5. 异常处理

所有异常统一捕获，返回一个**带结构的兜底对象**（不是简单的 `{"error": ...}`），包含空的 `product_plan`（含空的 `features` 和 `roadmap`）以及 `error` 字段。这样下游（如 WebAgent）处理时仍能按预期结构访问字段。

---

## 与同级 Agent 的对比

| | SalesAgent (P1) | MarketingAgent (P2) | ProductAgent (P2) |
|---|---|---|---|
| 使用 previous_results | 否 | 是 | **是** |
| JSON 解析 | 自实现（单层） | `robust_json_parse_with_llm`（6层 + LLM 修复） | `robust_json_parse_with_llm`（6层 + LLM 修复） |
| 兜底返回 | `{"error": ...}` | 带结构的完整兜底对象 | 带结构的完整兜底对象 |
| LLM 最多调用次数 | 1 次 | 2 次（生成 + JSON 修复） | **2 次**（生成 + JSON 修复） |
| SKILL.md 输出格式 | `prospects` + `outreach_plan` | `strategy` + `action_items` | `product_plan`（含 `features` + `roadmap`） |
| 角色设定 | 销售顾问 | 营销专家 | **高级产品经理和创业顾问** |

---

## 设计要点

- **利用前序结果**: 与 MarketingAgent 一致，ProductAgent 显式整合 `previous_results`。ResearchAgent 的调研数据、MonitoringAgent 的指标分析都会被放进 prompt 的"所有收集的信息"部分，让 LLM 基于真实数据做功能规划和优先级排序。
- **MVP 优先的规划原则**: SKILL.md 中强调"功能规划要有优先级排序（MVP优先）"和"考虑技术可行性和资源约束"，LLM 输出的 `features` 必须带 `P0/P1/P2` 优先级，`roadmap` 须包含明确阶段和时间线。
- **结构化兜底**: 异常时返回的不是简单 error，而是保持了 `product_plan` 结构（含空的 `features` 和 `roadmap`）的空壳对象，避免下游（特别是 WebAgent）因结构不一致而崩溃。
- **最强 JSON 容错**: 与 MarketingAgent 同样使用 `robust_json_parse_with_llm`，最多 2 次 LLM 调用（1 次生成 + 1 次 JSON 修复）。
- **all_info 可能很大**: 前序 agent 的完整 `data` 都被序列化进 prompt。如果 ResearchAgent 返回了大量搜索结果，prompt 会显著膨胀。
- **输出驱动 WebAgent**: ProductAgent 的输出是 Priority 3 WebAgent 生成落地页的核心输入——`product_plan.name`、`vision`、`core_value`、`features` 会直接映射到页面内容，因此字段的完整性很重要。
- **无 system message**: 与 MarketingAgent、SalesAgent 一样，只传 `user` role，角色设定写在 prompt 开头而非 `system` role。
