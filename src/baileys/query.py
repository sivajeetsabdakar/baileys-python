from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from .wabinary import BinaryNode


@dataclass(frozen=True)
class QueryResult:
    tag_id: str
    node: BinaryNode


class TagGenerator:
    def __init__(self, prefix: str | None = None) -> None:
        self.prefix = prefix or f"{int(time.time() * 1000)}."
        self.epoch = 1

    def next(self) -> str:
        value = f"{self.prefix}{self.epoch}"
        self.epoch += 1
        return value


class QueryManager:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[BinaryNode]] = {}
        self.tags = TagGenerator()

    def next_tag(self) -> str:
        return self.tags.next()

    def create_waiter(self, tag_id: str) -> asyncio.Future[BinaryNode]:
        if tag_id in self._pending:
            raise ValueError(f"query id already pending: {tag_id}")
        loop = asyncio.get_running_loop()
        future: asyncio.Future[BinaryNode] = loop.create_future()
        self._pending[tag_id] = future
        return future

    async def wait_for(self, tag_id: str, *, timeout: float | None = None) -> BinaryNode:
        future = self._pending.get(tag_id)
        if future is None:
            future = self.create_waiter(tag_id)
        try:
            return await asyncio.wait_for(future, timeout)
        finally:
            self._pending.pop(tag_id, None)

    def resolve(self, node: BinaryNode) -> bool:
        tag_id = node.attrs.get("id")
        if not tag_id:
            return False
        future = self._pending.get(tag_id)
        if future is None or future.done():
            return False
        future.set_result(node)
        return True

    def reject(self, tag_id: str, error: BaseException) -> bool:
        future = self._pending.get(tag_id)
        if future is None or future.done():
            return False
        future.set_exception(error)
        return True

    def discard(self, tag_id: str) -> bool:
        return self._pending.pop(tag_id, None) is not None

    def cancel_all(self) -> int:
        count = 0
        for future in self._pending.values():
            if not future.done():
                future.cancel()
                count += 1
        self._pending.clear()
        return count

    @property
    def pending_ids(self) -> tuple[str, ...]:
        return tuple(self._pending)
