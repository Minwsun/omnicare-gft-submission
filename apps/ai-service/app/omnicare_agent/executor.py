from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from ..contracts import ToolResult, ToolStatus
from .harness_contracts import ToolExecutionRecord
from .registry import ToolRegistry, tool_registry


class ToolExecutor:
    def __init__(self, registry: ToolRegistry = tool_registry) -> None:
        self.registry = registry

    async def execute(
        self,
        name: str,
        actor_role: str,
        customer_verified: bool,
        operation: Callable[[], Awaitable[ToolResult]],
    ) -> ToolExecutionRecord:
        specification = self.registry.specification(name)
        policy = self.registry.authorize(name, actor_role, customer_verified)
        if not policy.allowed:
            return ToolExecutionRecord(name=name, result=ToolResult(status=ToolStatus.FORBIDDEN, error_code=policy.reason), latency_ms=0, attempts=0, policy_reason=policy.reason)
        started = time.perf_counter()
        attempts = 0
        result = ToolResult(status=ToolStatus.UNAVAILABLE, error_code="TOOL_NOT_EXECUTED")
        while attempts <= specification.max_retries:
            attempts += 1
            try:
                result = await asyncio.wait_for(operation(), timeout=specification.timeout_seconds)
            except TimeoutError:
                result = ToolResult(status=ToolStatus.UNAVAILABLE, error_code="TOOL_TIMEOUT", safe_message="Tra cứu đang mất nhiều thời gian hơn bình thường.")
            except Exception:
                result = ToolResult(status=ToolStatus.FAILED, error_code="TOOL_EXECUTION_FAILED", safe_message="Chưa thể tra cứu thông tin lúc này.")
            if result.status not in {ToolStatus.UNAVAILABLE, ToolStatus.FAILED}:
                break
        return ToolExecutionRecord(name=name, result=result, latency_ms=round((time.perf_counter() - started) * 1000), attempts=attempts, policy_reason=policy.reason)

    async def execute_parallel(self, operations: list[tuple[str, str, bool, Callable[[], Awaitable[ToolResult]]]]) -> list[ToolExecutionRecord]:
        return await asyncio.gather(*(self.execute(*operation) for operation in operations))


tool_executor = ToolExecutor()
