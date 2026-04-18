# LLM 连接韧性 (llm_resilience)

**源文件**: `utils/llm_resilience.py`

## 概述

`llm_resilience` 提供 LLM 调用的**短期容错工具**:重试退避、可重试错误判断、服务健康检查。它与 `circuit_breaker.py` 互补——熔断器负责**长期失败**的保护,这里负责**单次调用**的瞬时错误恢复。

三个公开函数:

| 函数 | 同异步 | 用途 |
|---|---|---|
| `is_retriable_error` | 同步 | 判断异常是否可重试(网络/超时/限流/5xx) |
| `retry_with_backoff` | **异步** | 指数退避(带抖动)重试异步调用 |
| `run_health_check` | **异步** | 对 LLM 服务做一次最小化冒烟测试 |

---

## `is_retriable_error(exc: BaseException) -> bool`

判断一个异常是否属于"值得重试"的类型。

### 分类逻辑

按两类判定:

**1. 异常类型白名单**(通过 `isinstance` 判断):
- `asyncio.TimeoutError`
- `TimeoutError`
- `ConnectionError`
- `OSError`

**2. 异常消息关键字匹配**(`str(exc).lower()` 后用 `in` 查):
- 限流:`"429"`、`"rate limit"`、`"too many requests"`
- 服务端错误:`"500"`、`"502"`、`"503"`、`"504"`
- 超时:`"timeout"`、`"timed out"`

### 不可重试的场景

- `CircuitOpenError`(熔断已打开,重试无意义)
- 400/401/403/404 类客户端错误(消息里没有 5xx 或 429 关键字)
- JSON 解析错误、`ValueError` 等业务逻辑错误
- 代码 bug 类异常(`AttributeError`、`KeyError` 等)

### 设计要点

- **靠消息字符串判断 5xx/429**: AgentScope / OpenAI SDK 的异常类型层次不统一,最稳妥的做法是把状态码当关键字搜。代价是:如果异常消息里**恰巧**出现 `"500"`(比如 token 数=500)会误判——但实践中 HTTP 状态码几乎不会和业务数字混淆。
- **大小写不敏感**: 先 `.lower()` 再 `in`,避免 `"Rate Limit"` / `"RATE LIMIT"` 等大小写差异。
- **`OSError` 覆盖面广**: Python 把 `ConnectionRefusedError`、`ConnectionResetError`、DNS 失败等都归到 `OSError` 子类,一条 `isinstance` 就覆盖大多数网络底层错。

---

## `async retry_with_backoff(coro_factory, max_retries=3, base_delay_sec=1.0, max_delay_sec=30.0, jitter=True) -> T`

对异步调用进行**指数退避重试**(可选抖动)。

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `coro_factory` | `Callable[[], Awaitable[T]]` | — | **无参可调用**,每次返回新的协程 |
| `max_retries` | `int` | `3` | 最多重试次数(不含首次),总共最多调用 `1 + max_retries` 次 |
| `base_delay_sec` | `float` | `1.0` | 首次退避基数(秒) |
| `max_delay_sec` | `float` | `30.0` | 退避上限 |
| `jitter` | `bool` | `True` | 是否加随机抖动,范围 `[0.5x, 1.5x)` |

### 为什么是 `coro_factory` 而不是 `coro`?

协程对象只能 await 一次。如果直接传入 `coro`,重试时会抛 `RuntimeError: cannot reuse already awaited coroutine`。正确做法是传入**工厂函数**,每次循环调用工厂生成新协程:

```python
# ❌ 错
coro = model(messages)
await retry_with_backoff(lambda: coro)   # 第二次重试就炸

# ✅ 对
await retry_with_backoff(lambda: model(messages))  # 每次 lambda() 都生成新协程
```

### 退避算法

```python
delay = min(base_delay_sec * (2 ** attempt), max_delay_sec)
if jitter:
    delay = delay * (0.5 + random.random())  # 0.5x ~ 1.5x
await asyncio.sleep(delay)
```

默认参数下的实际退避序列(不含抖动):
- attempt=0 失败 → 等 1 秒
- attempt=1 失败 → 等 2 秒
- attempt=2 失败 → 等 4 秒
- attempt=3 失败 → 直接抛异常(已达 `max_retries`)

**最坏耗时**: 1 + 2 + 4 = 7 秒的等待 + 4 次调用本身。加上抖动后等待时间在 3.5s ~ 10.5s 之间。

### 特殊处理

- **`CircuitOpenError` 不重试**: 显式 `except CircuitOpenError: raise` 直接透传。熔断打开意味着服务已确定性不可用,重试只会浪费时间。
- **`is_retriable_error` 判定为 False 的异常**: 立刻抛出,不等待也不计 attempt。
- **最后一次仍失败**: 抛出**最后一次**的异常,不会返回聚合信息。

### 设计要点

- **线性累积,非并发**: 每次重试都是顺序 `await`,不会并发打多个请求。
- **抖动防雷鸣群效应**: 多个客户端同时失败时,若都在同一时刻重试会给服务端二次冲击。抖动让重试时间离散化。
- **`max_retries=3` 是保守默认**: 对 LLM 这种昂贵调用,失败 4 次仍不行就该降级。
- **不区分不同异常的退避策略**: 429 和超时用同样的退避曲线。对限流类错误,理论上服务端会返回 `Retry-After` 头,这里没读取——足够简单也足够用。

---

## `async run_health_check(base_url, api_key, model_name, timeout_sec=10.0) -> Tuple[bool, str]`

对 LLM 服务做一次**最小化冒烟测试**,供 `python cli.py health` 使用。

### 参数

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `base_url` | `str` | — | OpenAI 兼容端点的 base URL |
| `api_key` | `str` | — | API 密钥 |
| `model_name` | `str` | — | 模型名 |
| `timeout_sec` | `float` | `10.0` | 请求超时时间 |

### 返回

`Tuple[bool, str]`:
- `(True, "ok")` — 调用成功且有文本返回
- `(True, "ok (no content)")` — 调用成功但无文本(理论上走不到,因为判断条件 `len(str(text)) >= 0` 永远为 True)
- `(False, "AgentScope not installed")` — 缺依赖
- `(False, str(e))` — 任何异常的消息

### 执行逻辑

1. `from agentscope.model import OpenAIChatModel`,失败返回 `(False, "AgentScope not installed")`
2. 构造模型对象:
   ```python
   model = OpenAIChatModel(
       model_name=model_name,
       api_key=api_key,
       client_kwargs={"base_url": base_url, "timeout": timeout_sec},
       temperature=0,
       max_tokens=5,
   )
   ```
   `max_tokens=5` 保证响应极短、成本最低。
3. 发最小请求 `[{"role":"user","content":"1"}]`
4. 处理异步生成器 / `.text` / `.content` / dict 等多种响应形态(与 `json_parser` 类似)
5. 只要拿到响应就返回 `(True, "ok")`——**不校验**内容质量

### 设计要点

- **本函数自带导入**: `from agentscope.model import OpenAIChatModel` 写在函数内而不是模块顶部——避免 `utils/llm_resilience` 被导入时强制依赖 AgentScope。
- **只测可达性,不测正确性**: `temperature=0, max_tokens=5` 让响应确定且便宜。函数只关心"能不能连上、能不能响应",不关心响应内容是什么。
- **判断条件总为 True**: `if text is not None and len(str(text)) >= 0` ——`len` 不可能小于 0,所以只要没抛异常就视作成功。**实际上这里想表达的是"拿到任意响应就算成功"**,代码可以简化为 `return True, "ok"`。
- **无重试**: 健康检查就该看"最差一次能否成功",包重试会掩盖问题。
- **超时靠 SDK**: 通过 `client_kwargs["timeout"]` 交给 OpenAI SDK 处理,不自己加 `asyncio.wait_for`。

---

## 与 CircuitBreaker 的协作模式

CEOClaw 里的典型组合:

```python
from utils.circuit_breaker import CircuitBreaker, CircuitOpenError
from utils.llm_resilience import retry_with_backoff

breaker = CircuitBreaker(failure_threshold=5, recovery_timeout_sec=60)

async def call_llm():
    breaker.raise_if_open()       # OPEN 时直接抛 CircuitOpenError
    try:
        r = await model(messages)
        breaker.record_success()
        return r
    except CircuitOpenError:
        raise                      # 向上透传,retry 不会重试
    except Exception:
        breaker.record_failure()
        raise

result = await retry_with_backoff(call_llm, max_retries=3)
```

**分工**:
- `retry_with_backoff`: 瞬时故障(网络抖动、临时限流)→ 退避重试
- `CircuitBreaker`: 持续故障(API 宕机)→ 跳闸拒绝,避免每个请求都走完 4 次重试浪费时间

---

## 设计要点

- **重试 + 熔断 = 两层防御**: 一个负责"单次多试几次",一个负责"连续失败就歇会儿"。单独用任何一个都有短板。
- **异常消息关键字判定是实用主义**: 不同 SDK 的异常层次结构混乱,字符串匹配虽然"脏"但在各种客户端下都能工作。
- **`coro_factory` 的选择是正确的**: 协程不可重入是 Python async 的死规定,函数签名强制调用方传工厂,比传 `coro` 然后出错更友好。
- **健康检查用 `max_tokens=5`**: 在某些按 token 计费的服务下,每次 health check 约等于免费。配合 `temperature=0` 保证响应确定。
- **无 `Retry-After` 支持**: 限流场景下,服务端通常会在 HTTP 头里指定建议重试时间。本实现统一用指数退避,没读取头信息——代价是抖动窗口可能不够长。
