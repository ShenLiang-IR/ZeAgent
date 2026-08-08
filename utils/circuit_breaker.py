"""Circuit Breaker：熔断保护机制。

设计参见 docs/specs/2026-07-19-circuit-breaker-design.md（本期新建）。

状态机：
  CLOSED → OPEN（连续失败达 failure_threshold）→ HALF_OPEN（recovery_timeout 后）
  HALF_OPEN → CLOSED（成功）| HALF_OPEN → OPEN（失败）

用途：包装 LLM 调用 / dispatch_stream，上游故障时自动开路，
避免雪崩（所有请求都失败重试）。

配置（agent.execution.circuit_breaker.*）：
  failure_threshold: 连续失败次数阈值（默认 5）
  recovery_timeout: open → half_open 等待秒数（默认 60）
"""
import time

from loguru import logger


class CircuitBreaker:
    """轻量 async circuit breaker（无第三方依赖）。

    状态：
    - closed: 正常，允许调用
    - open: 熔断，拒绝调用
    - half_open: 试探性允许调用（成功 → closed，失败 → open）
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        name: str = "default",
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name
        self._failure_count = 0
        self._state = "closed"
        self._last_failure_time: float | None = None

    @property
    def state(self) -> str:
        """当前状态（自动检查 timeout 转换 open → half_open）。"""
        if self._state == "open" and self._last_failure_time is not None:
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = "half_open"
                logger.info(
                    f"[CircuitBreaker:{self.name}] open → half_open "
                    f"(recovery_timeout={self.recovery_timeout}s elapsed)"
                )
        return self._state

    def record_success(self) -> None:
        """记录成功调用。重置失败计数 + 回到 closed。"""
        if self._state in ("open", "half_open"):
            logger.info(f"[CircuitBreaker:{self.name}] {self._state} → closed (success)")
        self._failure_count = 0
        self._state = "closed"
        self._last_failure_time = None

    def record_failure(self) -> None:
        """记录失败调用。达阈值时进入 open。"""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._state == "half_open":
            # half_open 时失败：直接回到 open
            self._state = "open"
            logger.warning(
                f"[CircuitBreaker:{self.name}] half_open → open (failure during probe)"
            )
        elif self._failure_count >= self.failure_threshold:
            self._state = "open"
            logger.warning(
                f"[CircuitBreaker:{self.name}] closed → open "
                f"(failures={self._failure_count} >= threshold={self.failure_threshold})"
            )

    def is_open(self) -> bool:
        """是否熔断中（open 状态）。"""
        return self.state == "open"

    def can_proceed(self) -> bool:
        """是否允许调用（closed 或 half_open 时允许）。"""
        return self.state in ("closed", "half_open")

    def reset(self) -> None:
        """手动重置（管理 API 调用）。"""
        self._failure_count = 0
        self._state = "closed"
        self._last_failure_time = None
        logger.info(f"[CircuitBreaker:{self.name}] manually reset to closed")
