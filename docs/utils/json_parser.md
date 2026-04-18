# JSON 解析工具 (json_parser)

**源文件**: `utils/json_parser.py`

## 概述

`json_parser` 是 CEOClaw 应对"LLM 返回的 JSON 经常不合规"这一现实问题的**鲁棒解析工具箱**。提供四个函数:

| 函数 | 同异步 | 用途 |
|---|---|---|
| `robust_json_parse` | 同步 | 6 层常规容错解析(不调 LLM) |
| `robust_json_parse_with_llm` | **异步** | 6 层容错 + LLM 修复兜底 |
| `extract_json_from_response` | 同步 | 从多种响应格式中提取文本 |
| `extract_json_from_async_response` | **异步** | 处理异步生成器响应 |

常见调用模式:

```python
text = await extract_json_from_async_response(response)   # 先提文本
result = await robust_json_parse_with_llm(text, model,    # 再鲁棒解析
                                           fallback=None)
```

MarketingAgent / ProductAgent 走这条路径;IntentionAgent 只用同步版本。

---

## `robust_json_parse(text, fallback=None) -> dict`

同步的鲁棒 JSON 解析,按顺序尝试 **6 种策略**,任一成功即返回。

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `text` | `str` \| `dict` | — | 待解析文本;若已是 `dict` 直接返回 |
| `fallback` | `Any` | `None` | 所有策略失败时返回的默认值 |

### 返回 / 异常

- 成功:返回 `dict`
- 失败且 `fallback is not None`:返回 `fallback`
- 失败且 `fallback is None`:抛 `ValueError`

### 预处理

1. 空文本 → 走 fallback 分支
2. 已经是 dict → 直接返回
3. **剥离 markdown 围栏**:去掉开头的 ` ```json` 或 ` ``` `,和结尾的 ` ``` `
4. **截取 JSON 体**:找第一个 `{` 和最后一个 `}`,取这段子串。找不到 → fallback 或 `ValueError`

### 六层容错

每一层失败会记一条 `WARNING` 日志,附带错误位置前后 50 字符的上下文片段:

1. **直接解析**: `json.loads(json_str)`。
2. **移除控制字符**: `re.sub(r'[\x00-\x1f\x7f-\x9f]', '', s)`——去掉所有 ASCII 控制字符和扩展控制字符。LLM 偶尔输出不可见字符。
3. **修复引号**: 单引号转双引号。先修键名(`'key':` → `"key":`),再修字符串值(`: 'val'` → `: "val"`)。
4. **移除尾部逗号**: `re.sub(r',(\s*[}\]])', r'\1', s)`——去掉 `,}` 和 `,]` 里多余的逗号。
5. **转义字符串内换行**: 最复杂的一层,自己走一遍字符流,只对**字符串值内部**的 `\n`/`\r`/`\t` 做转义,保留 JSON 结构外的换行。用 `in_string` 和 `escape_next` 两个状态位追踪是否在字符串内。
6. **json5 兜底**: 尝试 `import json5`,用它宽松解析。未安装则跳过。

### 设计要点

- **按成本递增**: 前几层都是纯字符串处理,毫秒级;json5 要导入模块;全部失败后才走 LLM 修复(在 `robust_json_parse_with_llm`)。
- **每层独立 try**: 上一层失败不影响下一层。每一层都从原始 `json_str` 开始,不会累加多层修改。
- **日志友好**: 每次成功记 `INFO`(如 `"JSON parsed successfully after removing trailing commas"`),失败记 `WARNING` 且带错误上下文——方便统计哪种错误最多。
- **`fallback` 是"知错仍继续"的信号**: 传入 `fallback` 表示调用方接受"解析失败返回默认值";传 `None` 则强制抛异常。

---

## `async robust_json_parse_with_llm(text, model, fallback=None) -> dict`

在 `robust_json_parse` 的 6 层基础上追加**第 7 层:让 LLM 修复 JSON**。

### 参数

| 参数 | 类型 | 说明 |
|---|---|---|
| `text` | `str` | 待解析文本 |
| `model` | 可调用对象 | LLM 模型,`await model([{"role":"user","content":...}])` |
| `fallback` | `Any` | 最终兜底 |

### 执行流程

1. 先调 `robust_json_parse(text, fallback=None)`;成功直接返回。
2. 失败后进入 LLM 修复路径:
   - 再次剥离 markdown 围栏、截取 `{...}` 子串
   - **截断**: 超过 12000 字符则截断并追加 `"\n... (truncated)"`——避免超 context
   - 构造 `repair_prompt`,要求 LLM "输出修复后的纯 JSON,不要添加任何解释"
   - `await model([{"role":"user","content":repair_prompt}])`
   - 用 `extract_json_from_async_response` 取文本
   - 再剥一次 markdown 围栏和 `{...}` 边界
   - `json.loads(repaired_text)`
3. LLM 修复成功 → 返回 dict(INFO 日志 `"JSON parsed successfully after LLM repair"`)
4. LLM 修复失败 → `fallback` 或抛 `ValueError`

### 成本提示

- **最多 1 次额外 LLM 调用**: 只在前 6 层全挂时触发。
- **截断阈值硬编码 12000**: 若 LLM 返回超长 JSON,会丢掉尾部上下文再送修。12000 字符对 Deepseek 的 context 足够安全。
- **修复失败不重试**: LLM 修复只试一次,失败就走 fallback。不做二次修复。

---

## `extract_json_from_response(response, field_name="content") -> str`

同步版本的响应文本提取。处理 AgentScope / OpenAI SDK 返回的多种形态:

| 响应形态 | 提取逻辑 |
|---|---|
| 有 `.text` 属性 | `response.text` |
| 有指定字段(默认 `content`) | 若是 `str` → 直接取;若是 `list[dict]` → 遍历找 `{"type":"text"}` 的 `text` 字段 |
| `dict` 且包含该字段 | `response[field_name]` |
| `str` | 直接返回 |
| 其他 | `str(response)` 兜底 |

---

## `async extract_json_from_async_response(response, field_name="content") -> str`

异步版本。核心差异:**支持异步生成器**(`__aiter__`)——AgentScope 的流式响应是生成器。

### 流式处理逻辑

```python
async for chunk in response:
    if isinstance(chunk, str):
        text = chunk
    elif hasattr(chunk, field_name):
        content = getattr(chunk, field_name)
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get('type') == 'text':
                    text = item.get('text', '')
```

> 注意:每个 chunk **覆盖**前一次的 `text`,而不是追加。这意味着函数假设最后一个 chunk 包含**完整文本**(Deepseek/OpenAI 的非流式调用确实如此)。若真正需要处理逐 token 流式,这里会丢数据——但 CEOClaw 没用流式。

非异步响应(没有 `__aiter__`)会 fallback 到同步版本 `extract_json_from_response`。

---

## 实际调用链

典型的 skill agent(如 MarketingAgent)解析响应的顺序:

```
1. response = await self.model([{"role":"user","content":prompt}])
2. text = await extract_json_from_async_response(response)
   → 异步生成器 → 取最后一个 chunk 的 content
3. result = await robust_json_parse_with_llm(text, self.model, fallback=None)
   → 6 层常规容错
   → 全挂 → 发第二次 LLM 调用修复 JSON
   → 若仍失败 → 抛 ValueError,上层用结构化兜底返回
```

---

## 设计要点

- **分层成本**: 6 层常规解析 << 1 次 LLM 修复。大部分 JSON 问题(markdown 围栏、尾部逗号、单引号)在前几层就能解决,避免无谓的 LLM 调用。
- **剥离 markdown 是第一优先级**: LLM 最常见的"错误"其实是把 JSON 包在 ` ```json ... ``` ` 里——这在 2-3 个函数里都重复处理了。
- **`{...}` 边界用 find/rfind**: 不是真正的 JSON 语法分析,而是简单取第一个 `{` 到最后一个 `}`。若响应里有多个 JSON 对象,只会取最外层的那一段。对 LLM 输出足够。
- **字符串内换行的状态机**: 第 5 层是整个文件最细的处理——LLM 常常在字符串值里直接塞 `\n`(没转义),这会让 `json.loads` 炸。这里手写了一个 `in_string` / `escape_next` 的简单词法分析器来只转义字符串内部的换行。
- **LLM 修复的 prompt 极简**: 只给"有错误的 JSON"原文,不附任何上下文或 schema。靠 LLM 的"修复 JSON"这个通用能力,而不试图让它理解业务含义——修完即可,正确性靠后续代码校验。
- **`extract_json_from_async_response` 的覆盖语义**: 对流式输出不友好。如果未来引入真正的流式 LLM,这里需要改成字符串累加。
- **线程安全**: 所有函数都是无状态的纯函数,可重入,适合 async 并发调用。
