from __future__ import annotations

from dataclasses import dataclass

from .socket_nodes import find_child
from .wabinary import BinaryNode


@dataclass(frozen=True)
class NotificationInfo:
    id: str | None
    type: str | None
    category: str
    from_jid: str | None
    participant: str | None
    recipient: str | None
    timestamp: int | None
    offline: bool
    child_tags: tuple[str, ...]
    attrs: dict[str, str]
    child_attrs: dict[str, dict[str, str]]


@dataclass(frozen=True)
class DirtyInfo:
    type: str | None
    timestamp: int | None
    attrs: dict[str, str]


@dataclass(frozen=True)
class OfflineInfo:
    count: int
    preview: bool
    attrs: dict[str, str]


@dataclass(frozen=True)
class CallInfo:
    id: str | None
    from_jid: str | None
    timestamp: int | None
    offline: bool
    child_tags: tuple[str, ...]
    attrs: dict[str, str]


def parse_notification_info(node: BinaryNode) -> NotificationInfo | None:
    if node.tag != "notification":
        return None

    child_tags = _child_tags(node)
    child_attrs = _child_attrs(node)
    notification_type = node.attrs.get("type")
    return NotificationInfo(
        id=node.attrs.get("id"),
        type=notification_type,
        category=_notification_category(notification_type, child_tags),
        from_jid=node.attrs.get("from"),
        participant=node.attrs.get("participant"),
        recipient=node.attrs.get("recipient"),
        timestamp=_optional_int(node.attrs.get("t")),
        offline=bool(node.attrs.get("offline")),
        child_tags=child_tags,
        attrs=dict(node.attrs),
        child_attrs=child_attrs,
    )


def parse_dirty_info(node: BinaryNode) -> DirtyInfo | None:
    dirty = find_child(node, "dirty")
    if dirty is None:
        return None
    return DirtyInfo(
        type=dirty.attrs.get("type"),
        timestamp=_optional_int(dirty.attrs.get("timestamp") or dirty.attrs.get("t")),
        attrs=dict(dirty.attrs),
    )


def parse_offline_info(node: BinaryNode) -> OfflineInfo | None:
    offline = find_child(node, "offline") or find_child(node, "offline_preview")
    if offline is None:
        return None
    return OfflineInfo(
        count=_optional_int(offline.attrs.get("count")) or 0,
        preview=offline.tag == "offline_preview",
        attrs=dict(offline.attrs),
    )


def parse_call_info(node: BinaryNode) -> CallInfo | None:
    if node.tag != "call":
        return None
    return CallInfo(
        id=node.attrs.get("id"),
        from_jid=node.attrs.get("from"),
        timestamp=_optional_int(node.attrs.get("t")),
        offline=bool(node.attrs.get("offline")),
        child_tags=_child_tags(node),
        attrs=dict(node.attrs),
    )


def _notification_category(notification_type: str | None, child_tags: tuple[str, ...]) -> str:
    tags = set(child_tags)
    if notification_type in {"encrypt", "devices"} or tags & {"count", "devices", "device"}:
        return "devices"
    if notification_type in {"identity", "security"} or tags & {"identity", "device-identity", "key-index-list"}:
        return "identity"
    if notification_type in {"contacts", "contact"} or tags & {"contact", "contacts"}:
        return "contacts"
    if notification_type in {"newsletter", "mex"} or tags & {"newsletter", "mex"}:
        return "newsletter"
    if notification_type in {"w:gp2", "group", "participant"} or tags & {"participant", "participants", "add", "remove", "promote", "demote"}:
        return "groups"
    if notification_type in {"app_state", "app-state", "sync", "server_sync"} or tags & {"collection", "patch", "sync"}:
        return "app_state"
    if notification_type in {"privacy", "privacy_token"} or tags & {"privacy", "token", "tokens"}:
        return "privacy"
    if notification_type in {"server_props", "props"} or tags & {"props", "server_props"}:
        return "server_props"
    return notification_type or "unknown"


def _child_tags(node: BinaryNode) -> tuple[str, ...]:
    if not isinstance(node.content, list):
        return ()
    return tuple(child.tag for child in node.content)


def _child_attrs(node: BinaryNode) -> dict[str, dict[str, str]]:
    if not isinstance(node.content, list):
        return {}
    return {child.tag: dict(child.attrs) for child in node.content}


def _optional_int(value: str | None) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except ValueError:
        return None
