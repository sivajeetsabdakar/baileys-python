from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .mex import QUERY_IDS, XWA_PATHS, wmex_query_node
from .socket_nodes import find_child, node_content_bytes
from .wabinary import BinaryNode


@dataclass(frozen=True)
class NewsletterMetadata:
    id: str
    name: str | None = None
    description: str | None = None
    invite: str | None = None
    creation_time: int | None = None
    subscribers: int | None = None
    verification: str | None = None
    mute_state: str | None = None
    picture: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class NewsletterReactionUpdate:
    id: str
    server_id: str
    reaction: dict[str, Any]


@dataclass(frozen=True)
class NewsletterViewUpdate:
    id: str
    server_id: str
    count: int


@dataclass(frozen=True)
class NewsletterParticipantUpdate:
    id: str
    author: str | None
    user: str
    new_role: str | None
    action: str | None


@dataclass(frozen=True)
class NewsletterSettingsUpdate:
    id: str
    update: dict[str, Any]


def parse_newsletter_metadata(result: Any) -> NewsletterMetadata | None:
    if not isinstance(result, dict):
        return None
    data = result.get("result") if isinstance(result.get("result"), dict) else result
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        return None
    thread = data.get("thread_metadata") if isinstance(data.get("thread_metadata"), dict) else {}
    viewer = data.get("viewer_metadata") if isinstance(data.get("viewer_metadata"), dict) else {}
    name = _text_field(thread.get("name")) or data.get("name")
    description = _text_field(thread.get("description")) or data.get("description")
    picture = thread.get("picture") if isinstance(thread.get("picture"), dict) else data.get("picture")
    return NewsletterMetadata(
        id=data["id"],
        name=name,
        description=description,
        invite=thread.get("invite") or data.get("invite"),
        creation_time=_optional_int(thread.get("creation_time") or data.get("creation_time")),
        subscribers=_optional_int(thread.get("subscribers_count") or data.get("subscribers")),
        verification=thread.get("verification") or data.get("verification"),
        mute_state=viewer.get("mute") or data.get("mute_state"),
        picture=picture if isinstance(picture, dict) else None,
        raw=data,
    )


def newsletter_create_query(name: str, description: str | None, tag_id: str) -> tuple[BinaryNode, str]:
    variables = {"input": {"name": name, "description": description}}
    return wmex_query_node(variables, QUERY_IDS["CREATE"], tag_id), XWA_PATHS["CREATE"]


def newsletter_update_query(jid: str, updates: dict[str, Any], tag_id: str) -> tuple[BinaryNode, str]:
    variables = {"newsletter_id": jid, "updates": {**updates, "settings": None}}
    return wmex_query_node(variables, QUERY_IDS["UPDATE_METADATA"], tag_id), "xwa2_newsletter_update"


def newsletter_metadata_query(kind: str, key: str, tag_id: str) -> tuple[BinaryNode, str]:
    variables = {
        "fetch_creation_time": True,
        "fetch_full_image": True,
        "fetch_viewer_metadata": True,
        "input": {"key": key, "type": kind.upper()},
    }
    return wmex_query_node(variables, QUERY_IDS["METADATA"], tag_id), XWA_PATHS["METADATA"]


def newsletter_simple_query(jid: str, operation: str, tag_id: str) -> tuple[BinaryNode, str]:
    return wmex_query_node({"newsletter_id": jid}, QUERY_IDS[operation], tag_id), XWA_PATHS[operation]


def newsletter_owner_query(jid: str, user_jid: str, operation: str, tag_id: str) -> tuple[BinaryNode, str]:
    return wmex_query_node({"newsletter_id": jid, "user_id": user_jid}, QUERY_IDS[operation], tag_id), XWA_PATHS[operation]


def newsletter_reaction_node(jid: str, server_id: str, tag_id: str, reaction: str | None = None) -> BinaryNode:
    attrs = {"to": jid, "type": "reaction", "server_id": server_id, "id": tag_id}
    if reaction is None:
        attrs["edit"] = "7"
    return BinaryNode("message", attrs, [BinaryNode("reaction", {"code": reaction} if reaction else {})])


def newsletter_fetch_messages_node(jid: str, count: int, since: int | None, after: int | None, tag_id: str) -> BinaryNode:
    attrs = {"count": str(count)}
    if since is not None:
        attrs["since"] = str(since)
    if after is not None:
        attrs["after"] = str(after)
    return BinaryNode("iq", {"id": tag_id, "type": "get", "xmlns": "newsletter", "to": jid}, [BinaryNode("message_updates", attrs)])


def newsletter_live_updates_node(jid: str, tag_id: str) -> BinaryNode:
    return BinaryNode("iq", {"id": tag_id, "type": "set", "xmlns": "newsletter", "to": jid}, [BinaryNode("live_updates", {}, [])])


def parse_live_update_duration(node: BinaryNode) -> str | None:
    live_updates = find_child(node, "live_updates")
    return live_updates.attrs.get("duration") if live_updates is not None else None


def parse_newsletter_notification_events(node: BinaryNode) -> list[tuple[str, Any]]:
    if node.tag != "notification":
        return []
    if node.attrs.get("type") == "mex" or find_child(node, "mex") is not None:
        return _parse_mex_newsletter_notification_events(node)
    from_jid = node.attrs.get("from")
    if not from_jid or not isinstance(node.content, list):
        return []

    events: list[tuple[str, Any]] = []
    author = node.attrs.get("participant")
    for child in node.content:
        if child.tag == "reaction":
            server_id = child.attrs.get("message_id") or child.attrs.get("server_id")
            if not server_id:
                continue
            reaction = {"count": _optional_int(child.attrs.get("count")) or 1}
            code = _child_text(child, "reaction") or child.attrs.get("code")
            if code:
                reaction["code"] = code
            if _truthy(child.attrs.get("removed")) or child.attrs.get("op") in {"remove", "delete"}:
                reaction["removed"] = True
            events.append(("newsletter.reaction", NewsletterReactionUpdate(id=from_jid, server_id=server_id, reaction=reaction)))
        elif child.tag == "view":
            server_id = child.attrs.get("message_id") or child.attrs.get("server_id")
            if not server_id:
                continue
            count = _optional_int(_node_text(child) or child.attrs.get("count")) or 0
            events.append(("newsletter.view", NewsletterViewUpdate(id=from_jid, server_id=server_id, count=count)))
        elif child.tag == "participant":
            user = child.attrs.get("jid") or child.attrs.get("user")
            if not user:
                continue
            events.append(
                (
                    "newsletter-participants.update",
                    NewsletterParticipantUpdate(
                        id=from_jid,
                        author=author,
                        user=user,
                        new_role=child.attrs.get("role") or child.attrs.get("new_role"),
                        action=child.attrs.get("action"),
                    ),
                )
            )
        elif child.tag == "update":
            settings = find_child(child, "settings")
            update = _parse_settings_node(settings)
            if update:
                events.append(("newsletter-settings.update", NewsletterSettingsUpdate(id=from_jid, update=update)))
    return events


def _parse_mex_newsletter_notification_events(node: BinaryNode) -> list[tuple[str, Any]]:
    payload_node = find_child(node, "mex")
    if payload_node is None or node_content_bytes(payload_node) is None:
        payload_node = find_child(node, "update")
    if payload_node is None and isinstance(node.content, list) and node.content:
        payload_node = node.content[0]
    payload = node_content_bytes(payload_node)
    if payload is None:
        return []
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []

    operation = data.get("operation") or (payload_node.attrs.get("op_name") if payload_node is not None else None)
    updates = data.get("updates")
    if updates is None:
        linked_profiles = data.get("data", {}).get("xwa2_notify_linked_profiles") if isinstance(data.get("data"), dict) else None
        if linked_profiles is not None:
            updates = [linked_profiles]
    if not operation or not isinstance(updates, list):
        return []

    events: list[tuple[str, Any]] = []
    if operation == "NotificationNewsletterUpdate":
        for update in updates:
            if not isinstance(update, dict):
                continue
            jid = update.get("jid")
            settings = update.get("settings")
            if jid and isinstance(settings, dict) and settings:
                events.append(("newsletter-settings.update", NewsletterSettingsUpdate(id=jid, update=settings)))
    elif operation == "NotificationNewsletterAdminPromote":
        for update in updates:
            if not isinstance(update, dict):
                continue
            jid = update.get("jid")
            user = update.get("user")
            if jid and user:
                events.append(
                    (
                        "newsletter-participants.update",
                        NewsletterParticipantUpdate(id=jid, author=node.attrs.get("from"), user=user, new_role="ADMIN", action="promote"),
                    )
                )
    return events


def _parse_settings_node(settings: BinaryNode | None) -> dict[str, Any]:
    if settings is None:
        return {}
    update: dict[str, Any] = {}
    for key in ("name", "description"):
        value = _child_text(settings, key)
        if value is not None:
            update[key] = value
    return update


def _text_field(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("text")
    return value if isinstance(value, str) else None


def _child_text(node: BinaryNode | None, tag: str) -> str | None:
    return _decode_content(node_content_bytes(find_child(node, tag))) if node is not None else None


def _node_text(node: BinaryNode | None) -> str | None:
    return _decode_content(node_content_bytes(node))


def _decode_content(content: bytes | None) -> str | None:
    if content is None:
        return None
    return content.decode("utf-8", errors="replace")


def _truthy(value: str | None) -> bool:
    return str(value).lower() in {"1", "true", "yes"} if value is not None else False


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
