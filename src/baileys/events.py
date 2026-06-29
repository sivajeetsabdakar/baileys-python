from __future__ import annotations

import asyncio
import inspect
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any


EventHandler = Callable[[Any], Any | Awaitable[Any]]


@dataclass(frozen=True)
class ListenerRef:
    event: str
    handler: EventHandler


class EventEmitter:
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def on(self, event: str, handler: EventHandler) -> ListenerRef:
        self._handlers[event].append(handler)
        return ListenerRef(event=event, handler=handler)

    def once(self, event: str, handler: EventHandler) -> ListenerRef:
        async def wrapper(payload: Any) -> None:
            self.off(event, wrapper)
            result = handler(payload)
            if inspect.isawaitable(result):
                await result

        return self.on(event, wrapper)

    def off(self, event: str, handler: EventHandler | ListenerRef) -> bool:
        if isinstance(handler, ListenerRef):
            event = handler.event
            handler = handler.handler
        handlers = self._handlers.get(event)
        if not handlers or handler not in handlers:
            return False
        handlers.remove(handler)
        if not handlers:
            self._handlers.pop(event, None)
        return True

    async def emit(self, event: str, payload: Any = None) -> int:
        handlers = list(self._handlers.get(event, ()))
        for handler in handlers:
            result = handler(payload)
            if inspect.isawaitable(result):
                await result
        return len(handlers)

    def emit_nowait(self, event: str, payload: Any = None) -> asyncio.Task[int]:
        return asyncio.create_task(self.emit(event, payload))

    async def wait_for(self, event: str, *, timeout: float | None = None) -> Any:
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()

        def resolve(payload: Any) -> None:
            if not future.done():
                future.set_result(payload)

        self.once(event, resolve)
        return await asyncio.wait_for(future, timeout)

    def listeners(self, event: str) -> tuple[EventHandler, ...]:
        return tuple(self._handlers.get(event, ()))
