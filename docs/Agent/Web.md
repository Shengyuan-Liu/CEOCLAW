# Web部署智能体 (WebAgent)

**源文件**: `.claude/skills/web/script/agent.py`
**技能描述**: `.claude/skills/web/SKILL.md`

## 概述

WebAgent 负责将前序 agent 产出的产品/营销信息转化为**落地页部署链接**。它不自己渲染 HTML，而是让 LLM 生成一段专业的自然语言 prompt，编码进 **Lovable Build-with-URL**（`https://lovable.dev/?autosubmit=true#prompt=...`），用户点击后由 Lovable 自动生成并托管落地页。WebAgent 是整条流水线的"交付端"。

## 在系统中的位置

```
OrchestrationAgent
  → P1: Research / Monitoring / Sales   ─┐
  → P2: Marketing / Product              ─┤ previous_results
  → P3: WebAgent.reply(input_msg)         ← 接收上述全部结果
  → 返回 Lovable URL + 部署说明
```

WebAgent 属于 Priority 3（执行/部署类），是流水线的**最后一环**，无并行 agent。它依赖 P1 和 P2 的全部产出——特别强依赖 ProductAgent 的 `product_plan` 和 MarketingAgent 的 `strategy`，这些信息会被融入 Lovable prompt 的页面文案。

## 依赖组件

- **SkillLoader**（`utils/skill_loader.py`）：读取 SKILL.md 中的 Lovable prompt 生成指南
- **`urllib.parse.quote`**：对 Lovable prompt 做 URL 编码（`safe=''`，即所有特殊字符都转义）
- **LLM 模型**（`self.model`）：生成给 Lovable 的详细落地页 prompt
- **Lovable 外部服务**：`https://lovable.dev` 的 Build-with-URL 入口，`autosubmit=true` 会让 Lovable 登录后自动提交 prompt

---

## 类: `WebAgent(AgentBase)`

### `__init__(self, name: str = "WebAgent", model=None, **kwargs)`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `name` | `str` | `"WebAgent"` | Agent 名称 |
| `model` | 可调用对象 | `None` | LLM 模型实例 |

**内部状态**:
- `self.name`, `self.model`
- `self.skill_loader`: `SkillLoader` 实例

---

### `async reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg`

落地页生成主流程。

**输入**:

| 参数 | 类型 | 说明 |
|---|---|---|
| `x` | `None` | 返回 `{"status": "error", "error": "No input"}` |
| `x` | `Msg` | 取 `x.content` |
| `x` | `List[Msg]` | 取最后一条的 `content` |

**实际接收的输入**（由 OrchestrationAgent 构建）:

```json
{
    "context": {
        "reasoning": "...",
        "intents": [...],
        "key_entities": {...},
        "rewritten_query": "为AI教育产品做一个落地页",
        "recent_dialogue": [...],
        "user_preferences": {...}
    },
    "reason": "需要生成落地页用于推广",
    "expected_output": "Lovable 落地页链接",
    "previous_results": [
        {
            "agent_name": "product",
            "priority": 2,
            "result": {
                "status": "success",
                "data": {"product_plan": {"name": "...", "features": [...], "pricing": "..."}}
            }
        },
        {
            "agent_name": "marketing",
            "priority": 2,
            "result": {
                "status": "success",
                "data": {"strategy": {"target_audience": "...", "channels": [...]}}
            }
        }
    ]
}
```

**输出**: `Msg(name=self.name, content=json_string, role="assistant")`

成功时：
```json
{
    "status": "success",
    "lovable_url": "https://lovable.dev/?autosubmit=true#prompt=%E7%94%9F%E6%88%90...",
    "lovable_prompt": "LLM 生成的落地页描述（纯文本，2000字内）",
    "deployment": {
        "method": "Lovable 自动生成",
        "instructions": "点击上方链接，Lovable 将自动为您生成并部署落地页。登录后选择工作区即可开始。",
        "platforms": ["Lovable (自动托管)", "可导出至 Vercel / Netlify"]
    }
}
```

输入为 `None` 时：
```json
{"status": "error", "error": "No input"}
```

**内部逻辑**:

#### 1. 解析输入，提取查询和前序结果

从 `content` 中尝试 JSON 解析，提取：
- `user_query`: 来自 `context.rewritten_query`
- `context_info`: 完整的 `context` 字典
- `previous_results`: 前序 agent 的执行结果列表

与 Product/Marketing 不同，这里**没有**单独提取 `user_preferences`。若 `content` 为 `dict`，直接从字典中取值。

#### 2. 收集所有上游信息

构建 `all_info` 字典，将前序结果按 `agent_name` 展开：

```python
all_info = {
    "user_query": "为AI教育产品做一个落地页",
    "product": {"product_plan": {...}},      # P2 product 的结果
    "marketing": {"strategy": {...}},         # P2 marketing 的结果
    "research": {"findings": "...", ...},     # P1 research 的结果（如有）
}
```

遍历 `previous_results`，取每项的 `result.data`，以 `agent_name` 为 key 存入 `all_info`。空结果或无名称的项会被跳过。注意 WebAgent 的 `all_info` **不包含 `context` 字段**（与 Product/Marketing 的差异之一）。

#### 3. 生成 Lovable prompt

调用 `self._generate_lovable_prompt(user_query, all_info)` 让 LLM 产出一段自然语言描述。

#### 4. 构建 Lovable URL

```python
encoded_prompt = quote(lovable_prompt, safe='')
lovable_url = f"https://lovable.dev/?autosubmit=true#prompt={encoded_prompt}"
```

使用 `urllib.parse.quote` 做**严格 URL 编码**（`safe=''`，连常规的 `/`、`:` 也会被转义），确保 prompt 作为 URL fragment 不会被截断。`autosubmit=true` 查询参数让 Lovable 登录后自动提交 prompt。

#### 5. 组装返回结构

无异常路径——`reply()` 不捕获异常。若 `_generate_lovable_prompt` 内部出错，它自己会返回兜底文本，`reply()` 仍会生成可用的 URL。

---

### `async _generate_lovable_prompt(self, user_query: str, all_info: dict) -> str`

使用 LLM 基于产品/营销信息生成给 Lovable 的自然语言落地页描述。

**输入**:

| 参数 | 类型 | 说明 |
|---|---|---|
| `user_query` | `str` | 用户原始查询 |
| `all_info` | `dict` | 合并后的上游信息（含 product、marketing 等） |

**输出**: `str` — Lovable 可直接消费的 prompt 文本。失败时返回兜底英文文本。

**逻辑**:

1. **加载 SKILL.md 指令**: `self.skill_loader.get_skill_content("web")` 读取 SKILL.md 中 frontmatter 之后的正文。失败时使用默认指令 `"生成一个专业的落地页。"`。

2. **构建 Prompt**: 包含以下部分：
   - 角色设定（"你是一个产品落地页设计专家"）
   - 用户需求（`user_query`）
   - 已有的产品/营销信息（`all_info` 序列化为 JSON）
   - 6 条**硬约束**（直接写在 prompt 中，不来自 SKILL.md）：
     1. 输出纯文本 prompt，不是 JSON/HTML
     2. 描述页面结构、设计风格、配色、各 section 内容、CTA 文案
     3. 融入产品名、功能、定价、目标用户
     4. 使用中文描述，页面语言中文
     5. **长度 ≤ 2000 字**
     6. 不要任何前缀或说明

3. **调用 LLM**:
   ```python
   response = await self.model([{"role": "user", "content": prompt}])
   ```

4. **提取文本**: 处理多种返回格式（异步生成器、`.text`、`.content`、字典、字符串）。代码逻辑与 ResearchAgent 的 `_summarize_research` 非常接近。

5. **兜底**:
   - LLM 返回空文本：`"Create a professional landing page for: {user_query}"`
   - LLM 调用异常：`"Create a professional Chinese landing page for the following product: {user_query}"`
   - 注意兜底文本是**英文**，但正常路径要求中文——这是一处不一致。

---

## 完整调用链示例

用户输入"为AI教育产品做一个落地页"后的完整流程：

```
1. IntentionAgent 识别意图
   → intents: ["research", "product", "marketing", "web"]

2. OrchestrationAgent 按优先级执行
   → P1: ResearchAgent（调研市场）
   → P2: ProductAgent（生成 product_plan）/ MarketingAgent（生成 strategy），并行
   → P3: WebAgent.reply(input_msg) — previous_results 含 P1+P2 全部结果

3. WebAgent.reply()
   → 解析 user_query 和 previous_results
   → all_info = {user_query, research, product, marketing}

4. WebAgent._generate_lovable_prompt(user_query, all_info)
   → LLM 生成中文落地页描述（含配色、各section、CTA按钮文案）

5. WebAgent 构建 URL
   → quote(prompt, safe='') 编码
   → lovable_url = "https://lovable.dev/?autosubmit=true#prompt=..."

6. 返回 Msg(content={"status": "success", "lovable_url": "...", "lovable_prompt": "...", "deployment": {...}})

7. OrchestrationAgent 聚合结果，格式化后展示给用户
   → 用户点击 lovable_url，Lovable 自动创建并托管落地页
```

---

## 与其他 Agent 的对比

| | Product (P2) | Marketing (P2) | WebAgent (P3) |
|---|---|---|---|
| 使用 previous_results | 是 | 是 | **是（P1+P2 全部）** |
| 输出形式 | 结构化 JSON（`product_plan`） | 结构化 JSON（`strategy`） | **URL + 纯文本 prompt** |
| JSON 解析 | `robust_json_parse_with_llm` | `robust_json_parse_with_llm` | **无**（输出非 JSON） |
| LLM 调用次数 | 最多 2 次 | 最多 2 次 | **1 次** |
| 异常处理 | try/except + 结构化兜底 | try/except + 结构化兜底 | **`reply()` 不捕获，仅子函数兜底** |
| 角色设定 | 高级产品经理 | 营销专家 | **产品落地页设计专家** |
| 外部依赖 | 无 | 无 | **Lovable（第三方服务）** |

---

## 设计要点

- **交付端定位**: WebAgent 是整条流水线的最后一步，本身不生产策略，而是把上游所有信息"打包"成一个可点击的 URL。核心价值在于**把多 agent 的产出变成用户可感知的交付物**。
- **URL fragment 传递 prompt**: Lovable 约定通过 URL fragment（`#prompt=...`）接收 prompt，fragment 不会被发送到服务器，能承载较长内容且相对隐私。`safe=''` 的严格编码是为了兼容中文和特殊字符。
- **2000 字硬约束**: prompt 太长会让 URL 超出浏览器限制（Chrome 约 2MB 但 fragment 处理各异），也会拖慢 Lovable 自身的生成。2000 字是经验值。
- **无 JSON 解析**: 是唯一不需要 JSON 鲁棒解析的 P2/P3 agent——LLM 输出本就是纯文本，`reply()` 手动组装最终的 JSON 返回结构。
- **兜底文本语言不一致**: 正常路径强制中文 prompt，但 `_generate_lovable_prompt` 的两条兜底文本是英文。Lovable 仍能生成页面，但页面语言可能变成英文，与预期不符。
- **`reply()` 无 try/except**: 与 Product/Marketing 不同，`reply()` 层没有统一异常处理。URL 构建和 `quote` 调用理论上不会抛异常，唯一可能失败的 LLM 调用在 `_generate_lovable_prompt` 内部已兜底，因此整体是安全的。
- **下游依赖外部服务**: 最终效果依赖 Lovable 的可用性、账户登录、工作区选择等——WebAgent 只负责"把 URL 交到用户手里"，无法保证 Lovable 端成功落地。
- **无 system message**: 与 Product/Marketing/Sales 一致，只传 `user` role，角色设定写在 prompt 开头。
