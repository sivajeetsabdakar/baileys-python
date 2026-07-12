from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any, Protocol

from .wabinary import BinaryNode


@dataclass(frozen=True)
class ReplayEntry:
    message_id: str
    node: BinaryNode
    expires_at: float

    @property
    def expired(self) -> bool:
        return self.expires_at <= time.time()


class ReplayStore(Protocol):
    def save_recent_outbound(self, message_id: str, node: BinaryNode, expires_at: float) -> None:
        ...

    def load_recent_outbound(self, message_id: str) -> BinaryNode | None:
        ...

    def delete_recent_outbound(self, message_id: str) -> None:
        ...

    def prune_expired(self, now: float | None = None) -> int:
        ...


class InMemoryReplayStore:
    def __init__(self) -> None:
        self._entries: dict[str, ReplayEntry] = {}

    def save_recent_outbound(self, message_id: str, node: BinaryNode, expires_at: float) -> None:
        if not message_id:
            return
        self._entries[message_id] = ReplayEntry(message_id=message_id, node=node, expires_at=expires_at)

    def load_recent_outbound(self, message_id: str) -> BinaryNode | None:
        entry = self._entries.get(message_id)
        if entry is None:
            return None
        if entry.expired:
            self._entries.pop(message_id, None)
            return None
        return entry.node

    def delete_recent_outbound(self, message_id: str) -> None:
        self._entries.pop(message_id, None)

    def prune_expired(self, now: float | None = None) -> int:
        cutoff = time.time() if now is None else now
        expired = [message_id for message_id, entry in self._entries.items() if entry.expires_at <= cutoff]
        for message_id in expired:
            self._entries.pop(message_id, None)
        return len(expired)


def binary_node_to_json(node: BinaryNode) -> dict[str, Any]:
    return {
        "tag": node.tag,
        "attrs": dict(node.attrs),
        "content": _content_to_json(node.content),
    }


def binary_node_from_json(payload: dict[str, Any]) -> BinaryNode:
    return BinaryNode(
        tag=str(payload["tag"]),
        attrs={str(key): str(value) for key, value in dict(payload.get("attrs") or {}).items()},
        content=_content_from_json(payload.get("content")),
    )


def _content_to_json(content: str | bytes | list[BinaryNode] | None) -> Any:
    if content is None:
        return None
    if isinstance(content, bytes):
        return {"type": "bytes", "base64": base64.b64encode(content).decode("ascii")}
    if isinstance(content, str):
        return {"type": "str", "value": content}
    if isinstance(content, list):
        return {"type": "list", "items": [binary_node_to_json(child) for child in content]}
    raise TypeError(f"unsupported node content: {type(content).__name__}")


def _content_from_json(payload: Any) -> str | bytes | list[BinaryNode] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise TypeError(f"invalid node content payload: {type(payload).__name__}")
    content_type = payload.get("type")
    if content_type == "bytes":
        return base64.b64decode(str(payload["base64"]))
    if content_type == "str":
        return str(payload["value"])
    if content_type == "list":
        return [binary_node_from_json(item) for item in payload.get("items") or []]
    raise ValueError(f"unsupported node content type: {content_type!r}")
