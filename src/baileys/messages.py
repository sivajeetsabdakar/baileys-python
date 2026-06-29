from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .generated import WAProto_pb2 as proto
from .message_decrypt import DecryptedNode, decrypt_message_node
from .wabinary import BinaryNode


@dataclass(frozen=True)
class MessageKey:
    remote_jid: str | None
    id: str | None
    from_me: bool = False
    participant: str | None = None


@dataclass(frozen=True)
class WAMessage:
    key: MessageKey
    message: proto.Message | None
    message_timestamp: int | None = None
    push_name: str | None = None
    broadcast: bool = False
    raw_node: BinaryNode | None = None
    decrypted: DecryptedNode | None = None

    def to_web_message_info(self) -> proto.WebMessageInfo:
        info = proto.WebMessageInfo()
        if self.key.remote_jid is not None:
            info.key.remoteJid = self.key.remote_jid
        if self.key.id is not None:
            info.key.id = self.key.id
        info.key.fromMe = self.key.from_me
        if self.key.participant is not None:
            info.key.participant = self.key.participant
        if self.message is not None:
            info.message.CopyFrom(self.message)
        if self.message_timestamp is not None:
            info.messageTimestamp = self.message_timestamp
        if self.push_name is not None:
            info.pushName = self.push_name
        if self.broadcast:
            info.broadcast = True
        return info


@dataclass(frozen=True)
class MessageUpsert:
    messages: list[WAMessage]
    type: str = "notify"


def message_key_from_node(node: BinaryNode, creds: dict) -> MessageKey:
    attrs = node.attrs
    remote_jid = attrs.get("from")
    participant = attrs.get("participant") or attrs.get("participant_lid") or attrs.get("participant_pn")
    me = creds.get("me") or {}
    own_ids = {value for value in (me.get("id"), me.get("lid")) if value}
    from_me = bool(remote_jid and remote_jid in own_ids)
    return MessageKey(
        remote_jid=remote_jid,
        id=attrs.get("id"),
        from_me=from_me,
        participant=participant,
    )


def build_message_upsert(
    node: BinaryNode,
    creds: dict,
    *,
    persist_creds_path: str | Path | None = None,
    upsert_type: str = "notify",
) -> MessageUpsert | None:
    if node.tag != "message":
        return None

    decrypted = decrypt_message_node(binary_node_to_decrypt_dict(node), creds, persist_creds_path=persist_creds_path)
    message = WAMessage(
        key=message_key_from_node(node, creds),
        message=decrypted.message if decrypted else None,
        message_timestamp=_optional_int(node.attrs.get("t")),
        push_name=node.attrs.get("notify") or node.attrs.get("pushName"),
        broadcast=node.attrs.get("broadcast") == "true",
        raw_node=node,
        decrypted=decrypted,
    )
    return MessageUpsert(messages=[message], type=upsert_type)


def binary_node_to_decrypt_dict(node: BinaryNode) -> dict[str, Any]:
    return {
        "tag": node.tag,
        "attrs": dict(node.attrs),
        "content": [_content_child_to_dict(child) for child in node.content]
        if isinstance(node.content, list)
        else [],
    }


def _content_child_to_dict(node: BinaryNode) -> dict[str, Any]:
    content: Any
    if isinstance(node.content, bytes):
        content = {"base64": base64.b64encode(node.content).decode("ascii")}
    elif isinstance(node.content, list):
        content = [_content_child_to_dict(child) for child in node.content]
    else:
        content = node.content
    return {"tag": node.tag, "attrs": dict(node.attrs), "content": content}


def _optional_int(value: str | None) -> int | None:
    return int(value) if value is not None else None
