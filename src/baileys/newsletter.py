from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .mex import QUERY_IDS, XWA_PATHS, wmex_query_node
from .socket_nodes import find_child
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


def _text_field(value: Any) -> str | None:
    if isinstance(value, dict):
        return value.get("text")
    return value if isinstance(value, str) else None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
