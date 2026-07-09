from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .defaults import S_WHATSAPP_NET
from .socket_nodes import find_child, node_content_bytes
from .wabinary import BinaryNode


XWA_PATHS = {
    "CREATE": "xwa2_newsletter_create",
    "SUBSCRIBERS": "xwa2_newsletter_subscribers",
    "METADATA": "xwa2_newsletter",
    "ADMIN_COUNT": "xwa2_newsletter_admin",
    "MUTE": "xwa2_newsletter_mute_v2",
    "UNMUTE": "xwa2_newsletter_unmute_v2",
    "FOLLOW": "xwa2_newsletter_join_v2",
    "UNFOLLOW": "xwa2_newsletter_leave_v2",
    "CHANGE_OWNER": "xwa2_newsletter_change_owner",
    "DEMOTE": "xwa2_newsletter_demote",
    "DELETE": "xwa2_newsletter_delete_v2",
    "REACHOUT_TIMELOCK": "xwa2_fetch_account_reachout_timelock",
    "MESSAGE_CAPPING_INFO": "xwa2_message_capping_info",
}

QUERY_IDS = {
    "CREATE": "8823471724422422",
    "UPDATE_METADATA": "24250201037901610",
    "METADATA": "6563316087068696",
    "SUBSCRIBERS": "9783111038412085",
    "FOLLOW": "24404358912487870",
    "UNFOLLOW": "9767147403369991",
    "MUTE": "29766401636284406",
    "UNMUTE": "9864994326891137",
    "ADMIN_COUNT": "7130823597031706",
    "CHANGE_OWNER": "7341777602580933",
    "DEMOTE": "6551828931592903",
    "DELETE": "30062808666639665",
    "REACHOUT_TIMELOCK": "23983697327930364",
    "MESSAGE_CAPPING_INFO": "24503548349331633",
}


@dataclass(frozen=True)
class MexError(RuntimeError):
    message: str
    data: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.message


def wmex_query_node(variables: dict[str, Any], query_id: str, tag_id: str) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"id": tag_id, "type": "get", "to": S_WHATSAPP_NET, "xmlns": "w:mex"},
        [BinaryNode("query", {"query_id": query_id}, json.dumps({"variables": variables}, separators=(",", ":")).encode("utf-8"))],
    )


def parse_wmex_result(node: BinaryNode, data_path: str | None = None) -> Any:
    child = find_child(node, "result")
    payload = node_content_bytes(child)
    if payload is None:
        raise MexError("missing MEX result payload", {"node": node.attrs})
    data = json.loads(payload.decode("utf-8"))
    errors = data.get("errors") or []
    if errors:
        messages = ", ".join(str(item.get("message") or "Unknown error") for item in errors if isinstance(item, dict))
        raise MexError(f"GraphQL server error: {messages or 'Unknown error'}", {"errors": errors})
    response: Any = data.get("data")
    if data_path:
        response = response.get(data_path) if isinstance(response, dict) else None
    if response is None:
        raise MexError("unexpected MEX response structure", {"data_path": data_path, "data": data})
    return response
