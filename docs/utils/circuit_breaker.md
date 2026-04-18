# 熔断器 (CircuitBreaker)

**源文件**: `utils/circuit_breaker.py`

## 概述

`CircuitBreaker` 是经典的**三态熔断器**——连续失败 N 次后"跳闸"拒绝请求,冷却一段时间后进入半开试探,若恢复成功则关闭回到正常。主要用于保护 LLM 调用不被雪崩式失败拖垮。在 CEOClaw 里,它通常配合 `retry_with_backoff`(`llm_resilience.py`)使用:重试负责单次抖动,熔断负责长期失败的降级。

## 状态机

```
         failure_threshold 次连续失败
CLOSED ──────────────────────────────► OPEN
  ▲                                     │
  │ half_open_successes 次连续成功      │ recovery_timeout_sec 秒后自动转移
  │                                     ▼
  └──────────────────  HALF_OPEN ◄──────┘
                         │
                         │ 任一次失败
                         ▼
                       OPEN (重新计时)
```

- **CLOSED**(正常):放行所有调用,失败计数达阈值则跳到 OPEN。
- **OPEN**(熔断):`allow_call()` 返回 `False`,上层应直接降级或抛 `CircuitOpenError`。距 `_opened_at` 超过 `recovery_timeout_sec` 后,下一次读取 `state` 属性时自动迁移到 HALF_OPEN。
- **HALF_OPEN**(试探):放行少量请求,累计 `half_open_successes` 次成功就回到 CLOSED;任一次失败立即回到 OPEN 并重置计时。

> 注意:`CLOSED → OPEN` 由 `record_failure()` 触发;`OPEN → HALF_OPEN` 是**惰性**触发——必须有代码读取 `state` 属性才会发生迁移。

---

## 类: `CircuitState(Enum)`

三个状态值:`CLOSED`、`OPEN`、`HALF_OPEN`(字符串值同名小写)。

## 类: `CircuitOpenError(Exception)`

熔断打开时由 `raise_if_open()` 抛出。上层捕获后应直接降级,不应再重试——重试已被熔断器拒绝。

---

## 类: `CircuitBreaker`

### `__init__(self, failure_threshold=5, recovery_timeout_sec=60.0, half_open_successes=2)`

| 参数 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `failure_threshold` | `int` | `5` | CLOSED 状态下累计多少次失败跳到 OPEN |
| `recovery_timeout_sec` | `float` | `60.0` | OPEN 状态持续多久后进入 HALF_OPEN |
| `half_open_successes` | `int` | `2` | HALF_OPEN 状态下累计多少次成功才回到 CLOSED |

**内部状态**:
- `_state: CircuitState` — 当前状态
- `_failure_count: int` — CLOSED 下的连续失败计数
- `_half_open_success_count: int` — HALF_OPEN 下的连续成功计数
- `_last_failure_time: Optional[float]` — 最近一次失败的 `time.monotonic()` 时间戳
- `_opened_at: Optional[float]` — 进入 OPEN 的时间,用于判断是否超过 `recovery_timeout_sec`

---

### `state: CircuitState` (property)

返回当前状态。**带惰性迁移**:若当前是 OPEN 且超过 `recovery_timeout_sec`,读取时就地把状态改成 HALF_OPEN 并重置 `_half_open_success_count`。

这意味着:如果长时间没有任何读取操作,熔断器会"停留"在 OPEN——不会自动恢复。在 CEOClaw 里,上层在调用 LLM 前总会先调 `allow_call()`,从而触发读取。

### `allow_call() -> bool`

判断是否允许本次调用:
- `CLOSED`: `True`
- `OPEN`: `False`
- `HALF_OPEN`: `True`(用于试探)

内部通过 `self.state`(property)触发 OPEN→HALF_OPEN 的时间迁移。

### `record_success() -> None`

记录一次成功调用:
- HALF_OPEN: `_half_open_success_count += 1`,达到 `half_open_successes` 后迁移到 CLOSED,重置 `_failure_count` 和 `_opened_at`
- CLOSED: 把 `_failure_count` 重置为 0(清空连续失败计数)
- OPEN: **无操作**(按理说 OPEN 下不会有成功调用,因为请求被拒绝)

> 重要:CLOSED 下的 `_failure_count` 统计的是**连续失败**——成功就会清零。这不是"5 次累计失败就跳闸",而是"连续 5 次失败就跳闸"。

### `record_failure() -> None`

记录一次失败调用:
- 先更新 `_last_failure_time`
- HALF_OPEN: 立刻回到 OPEN,重置 `_opened_at` 和 `_failure_count`
- CLOSED: `_failure_count += 1`,达阈值后迁移到 OPEN,记录 `_opened_at`
- OPEN: 无显式分支(OPEN 下本不该有调用,也就没有失败可记录)

### `raise_if_open() -> None`

`allow_call()` 的包装,若不允许则抛 `CircuitOpenError("服务暂时不可用,请稍后再试")`。便于调用方用 try/except 替代 if/else。

### `get_status() -> dict`

返回状态摘要,供日志或 CLI `/status` 命令使用:

```python
{
    "state": "closed" / "open" / "half_open",
    "failure_count": 3,
    "last_failure_time": 12345.67,  # time.monotonic 值,不是 wall clock
    "opened_at": None               # 或 time.monotonic 值
}
```

---

## 典型用法

**手动包裹 LLM 调用**:

```python
breaker = CircuitBreaker(failure_threshold=5, recovery_timeout_sec=60)

breaker.raise_if_open()  # OPEN 时直接降级
try:
    result = await model(messages)
    breaker.record_success()
    return result
except Exception as e:
    breaker.record_failure()
    raise
```

**与 `retry_with_backoff` 组合**(本项目实际用法):

```python
from utils.llm_resilience import retry_with_backoff
from utils.circuit_breaker import CircuitBreaker, CircuitOpenError

breaker = CircuitBreaker()

async def call_llm():
    breaker.raise_if_open()
    try:
        r = await model(messages)
        breaker.record_success()
        return r
    except CircuitOpenError:
        raise  # 不重试
    except Exception:
        breaker.record_failure()
        raise

# retry 内部会识别 CircuitOpenError 并直接 raise,不重试
result = await retry_with_backoff(call_llm, max_retries=3)
```

---

## 设计要点

- **使用 `time.monotonic()` 而非 `time.time()`**: 避免系统时钟回跳影响计时。`_last_failure_time` 和 `_opened_at` 记录的都是单调时钟值,不能直接当 wall-clock 用。
- **惰性状态迁移**: OPEN→HALF_OPEN 不是后台线程驱动,也不是定时器回调,而是在读取 `state` 时检查时间——单线程、无副作用、无资源占用。代价是:若长时间没有调用,熔断器"视觉上"永远不会恢复,但一旦有调用就会立刻恢复。
- **HALF_OPEN 下的成功计数**: 默认 `half_open_successes=2`,即试探需要连续成功 2 次才完全恢复。中间任一次失败都会回到 OPEN——这比"只要一次成功就恢复"更保守,适合 LLM 这种可能间歇性成功但底层已崩的场景。
- **非线程安全**: 所有状态变量都是普通属性,没有 `Lock`。若多线程使用会有竞态。CEOClaw 是单事件循环 async,不受影响。
- **不持久化**: 熔断器状态全在内存。进程重启后从 CLOSED 开始——这对 CLI 工具足够,但对长期运行的服务需要额外考虑。
- **`record_failure` 在 OPEN 下无分支**: 意味着 OPEN 时若意外有失败调用进来,不会让熔断延长。这是合理的——OPEN 本就不应该有调用,如果有,说明调用方没检查 `allow_call()`,问题在调用方。
