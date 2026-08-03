from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from typing import Generic, TypeVar


T = TypeVar("T")


class AsyncSingleFlightCache(Generic[T]):
    def __init__(self, ttl_seconds: float, max_entries: int) -> None:
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, T]] = OrderedDict()
        self._inflight: dict[str, asyncio.Task[T]] = {}
        self._lock = asyncio.Lock()
        self.generation = 0

    async def get_or_compute(self, key: str, compute: Callable[[], Awaitable[T]]) -> tuple[T, bool]:
        now = time.monotonic()
        async with self._lock:
            cached = self._entries.get(key)
            if cached and now - cached[0] < self.ttl_seconds:
                self._entries.move_to_end(key)
                return cached[1], True
            if cached:
                self._entries.pop(key, None)
            task = self._inflight.get(key)
            if task is None:
                task = asyncio.create_task(compute())
                self._inflight[key] = task
        try:
            value = await asyncio.shield(task)
        except BaseException:
            async with self._lock:
                if self._inflight.get(key) is task:
                    self._inflight.pop(key, None)
            raise
        async with self._lock:
            if self._inflight.get(key) is task:
                self._inflight.pop(key, None)
                self._entries[key] = (time.monotonic(), value)
                self._entries.move_to_end(key)
                while len(self._entries) > self.max_entries:
                    self._entries.popitem(last=False)
        return value, False

    async def clear(self) -> None:
        async with self._lock:
            self.generation += 1
            self._entries.clear()

