from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

from .generated import WAProto_pb2 as proto
from .jid import are_jids_same_user, is_jid_group, is_jid_status, jid_normalized_user
from .messages import MessageKey, WAMessage
from .wabinary import BinaryNode


ACKABLE_TAGS = {"message", "receipt", "notification", "call"}


@dataclass(frozen=True)
class RetryRequest:
    key: MessageKey
    ids: list[str]
    retry_count: int
    error_code: int | None
    node: BinaryNode


@dataclass(frozen=True)
class RetryOutcome:
    request: RetryRequest
    local_retry_count: int
    will_retry: bool
    resent: bool = False
    reason: str | None = None
    session_bundle: object | None = None


@dataclass(frozen=True)
class ReceiptInfo:
    key: MessageKey
    ids: list[str]
    status: int | None
    timestamp: int | None
    user_jid: str | None
    receipt_timestamp_key: str | None
    is_group_or_status: bool


def build_ack_node(node: BinaryNode, error_code: int | None = None, me_id: str | None = None) -> BinaryNode:
    """Build the WhatsApp Web ACK stanza for an inbound node."""
    attrs = {
        "id": node.attrs["id"],
        "to": node.attrs["from"],
        "class": node.tag,
    }
    if error_code:
        attrs["error"] = str(error_code)
    if node.attrs.get("participant"):
        attrs["participant"] = node.attrs["participant"]
    if node.attrs.get("recipient"):
        attrs["recipient"] = node.attrs["recipient"]
    if node.attrs.get("type"):
        attrs["type"] = node.attrs["type"]
    if node.tag == "message" and me_id:
        attrs["from"] = me_id
    return BinaryNode("ack", attrs)


def can_ack_node(node: BinaryNode) -> bool:
    return node.tag in ACKABLE_TAGS and bool(node.attrs.get("id") and node.attrs.get("from"))


def build_receipt_node(
    jid: str,
    message_ids: Iterable[str],
    *,
    participant: str | None = None,
    receipt_type: str | None = None,
    timestamp: int | None = None,
) -> BinaryNode:
    ids = [message_id for message_id in message_ids if message_id]
    if not ids:
        raise ValueError("receipt requires at least one message id")

    attrs = {"id": ids[0], "to": jid}
    if participant:
        attrs["participant"] = participant
    if receipt_type:
        attrs["type"] = receipt_type
    if receipt_type in {"read", "read-self"}:
        attrs["t"] = str(timestamp if timestamp is not None else int(time.time()))

    content = None
    if len(ids) > 1:
        content = [BinaryNode("list", {}, [BinaryNode("item", {"id": message_id}) for message_id in ids[1:]])]
    return BinaryNode("receipt", attrs, content)


def receipt_node_for_message(
    message: WAMessage,
    *,
    receipt_type: str = "read",
    timestamp: int | None = None,
) -> BinaryNode:
    key = message.key
    if not key.remote_jid:
        raise ValueError("message key is missing remote_jid")
    if not key.id:
        raise ValueError("message key is missing id")
    return build_receipt_node(
        key.remote_jid,
        [key.id],
        participant=key.participant,
        receipt_type=receipt_type,
        timestamp=timestamp,
    )


def aggregate_message_keys(keys: Iterable[MessageKey]) -> list[tuple[str, str | None, list[str]]]:
    grouped: dict[tuple[str, str | None], list[str]] = {}
    for key in keys:
        if not key.remote_jid or not key.id or key.from_me:
            continue
        group_key = (key.remote_jid, key.participant)
        grouped.setdefault(group_key, []).append(key.id)
    return [(jid, participant, ids) for (jid, participant), ids in grouped.items()]


def receipt_message_ids(node: BinaryNode) -> list[str]:
    ids = [node.attrs["id"]] if node.attrs.get("id") else []
    if isinstance(node.content, list):
        for child in node.content:
            if child.tag == "list" and isinstance(child.content, list):
                ids.extend(item.attrs["id"] for item in child.content if item.attrs.get("id"))
    return ids


def parse_retry_request(node: BinaryNode, creds: dict) -> RetryRequest | None:
    if node.tag != "receipt" or node.attrs.get("type") != "retry":
        return None
    retry = _find_child(node, "retry")
    if retry is None:
        return None

    attrs = node.attrs
    ids = receipt_message_ids(node)
    if not ids:
        return None

    me = creds.get("me") or {}
    sender = attrs.get("participant") or attrs.get("from")
    own_jid = me.get("lid") if "lid" in str(attrs.get("from", "")) else me.get("id")
    is_node_from_me = are_jids_same_user(sender, own_jid)
    from_jid = attrs.get("from")
    remote_jid = from_jid if (not is_node_from_me or (from_jid and is_jid_group(from_jid))) else attrs.get("recipient")
    from_me = not attrs.get("recipient") or (attrs.get("type") in {"retry", "sender"} and is_node_from_me)

    key = MessageKey(
        remote_jid=remote_jid,
        id=ids[0],
        from_me=from_me,
        participant=attrs.get("participant") or attrs.get("from"),
    )
    return RetryRequest(
        key=key,
        ids=ids,
        retry_count=_optional_int(retry.attrs.get("count")) or 1,
        error_code=_optional_int(retry.attrs.get("error")),
        node=node,
    )


def parse_receipt_info(node: BinaryNode, creds: dict) -> ReceiptInfo | None:
    if node.tag != "receipt" or node.attrs.get("type") == "retry":
        return None
    ids = receipt_message_ids(node)
    if not ids:
        return None

    attrs = node.attrs
    me = creds.get("me") or {}
    from_jid = attrs.get("from")
    sender = attrs.get("participant") or from_jid
    own_jid = me.get("lid") if "lid" in str(from_jid or "") else me.get("id")
    is_node_from_me = are_jids_same_user(sender, own_jid)
    remote_jid = from_jid if (not is_node_from_me or _safe_is_group(from_jid)) else attrs.get("recipient")
    from_me = not attrs.get("recipient") or (attrs.get("type") in {"retry", "sender"} and is_node_from_me)
    status = receipt_status_from_type(attrs.get("type"))
    is_group_or_status = _safe_is_group(remote_jid) or _safe_is_status(remote_jid)
    timestamp_key = "receipt_timestamp" if status == proto.WebMessageInfo.Status.DELIVERY_ACK else "read_timestamp"

    return ReceiptInfo(
        key=MessageKey(
            remote_jid=remote_jid,
            id=ids[0],
            from_me=from_me,
            participant=attrs.get("participant"),
        ),
        ids=ids,
        status=status,
        timestamp=_optional_int(attrs.get("t")) or 0,
        user_jid=jid_normalized_user(attrs["participant"]) if attrs.get("participant") else None,
        receipt_timestamp_key=timestamp_key if status is not None else None,
        is_group_or_status=is_group_or_status,
    )


def receipt_status_from_type(receipt_type: str | None) -> int | None:
    status_map = {
        "sender": proto.WebMessageInfo.Status.SERVER_ACK,
        "played": proto.WebMessageInfo.Status.PLAYED,
        "read": proto.WebMessageInfo.Status.READ,
        "read-self": proto.WebMessageInfo.Status.READ,
    }
    if receipt_type is None:
        return proto.WebMessageInfo.Status.DELIVERY_ACK
    return status_map.get(receipt_type)


def _find_child(node: BinaryNode, tag: str) -> BinaryNode | None:
    if not isinstance(node.content, list):
        return None
    for child in node.content:
        if child.tag == tag:
            return child
    return None


def _optional_int(value: str | None) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _safe_is_group(jid: str | None) -> bool:
    if not jid:
        return False
    try:
        return is_jid_group(jid)
    except ValueError:
        return False


def _safe_is_status(jid: str | None) -> bool:
    if not jid:
        return False
    try:
        return is_jid_status(jid)
    except ValueError:
        return False
