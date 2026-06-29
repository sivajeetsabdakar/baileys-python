from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Iterable

from signal_protocol import address, protocol, session_cipher

from baileys.auth_store import build_signal_store, export_session, unb64
from baileys.generated import WAProto_pb2 as proto
from baileys.jid import jid_decode_tuple
from baileys.wabinary import BinaryNode


@dataclass(frozen=True)
class OutboundMessage:
    node: BinaryNode
    message_id: str
    signal_type: str
    recipient_address: address.ProtocolAddress
    participant_jids: list[str]
    signal_types: dict[str, str]


def jid_decode(jid: str) -> tuple[str, str, int]:
    return jid_decode_tuple(jid)


def jid_encode(user: str, server: str, device: int | None = None) -> str:
    from baileys.jid import jid_encode as _jid_encode

    return _jid_encode(user, server, device)


def protocol_address_for_jid(jid: str) -> address.ProtocolAddress:
    user, _, device = jid_decode(jid)
    return address.ProtocolAddress(user, device)


def generate_message_id(user_jid: str | None = None) -> str:
    data = bytearray(8 + 20 + 16)
    data[:8] = int(time.time()).to_bytes(8, "big")
    if user_jid:
        user, _, _ = jid_decode(user_jid)
        user_bytes = user.encode("ascii")[:15]
        data[8 : 8 + len(user_bytes)] = user_bytes
        data[8 + len(user_bytes) : 8 + len(user_bytes) + 5] = b"@c.us"
    data[28:] = os.urandom(16)
    return "3EB0" + hashlib.sha256(data).hexdigest().upper()[:18]


def random_pad_max_16(data: bytes) -> bytes:
    pad = (os.urandom(1)[0] & 0x0F) + 1
    return data + bytes([pad]) * pad


def participant_hash_v2(participants: list[str]) -> str:
    joined = "".join(sorted(participants)).encode("utf-8")
    digest = hashlib.sha256(joined).digest()
    import base64

    return "2:" + base64.b64encode(digest).decode("ascii")[:6]


def text_message(text: str) -> proto.Message:
    message = proto.Message()
    message.conversation = text
    message.messageContextInfo.messageSecret = os.urandom(32)
    return message


def device_sent_message(destination_jid: str, message: proto.Message) -> proto.Message:
    wrapper = proto.Message()
    wrapper.deviceSentMessage.destinationJid = destination_jid
    wrapper.deviceSentMessage.message.CopyFrom(message)
    if message.HasField("messageContextInfo"):
        wrapper.messageContextInfo.CopyFrom(message.messageContextInfo)
    return wrapper


def encode_message_payload(message: proto.Message) -> bytes:
    return random_pad_max_16(message.SerializeToString())


def encrypt_for_recipient(creds: dict, recipient_jid: str, plaintext: bytes) -> tuple[str, bytes, address.ProtocolAddress]:
    addr = protocol_address_for_jid(recipient_jid)
    store = build_signal_store(creds)
    encrypted = session_cipher.message_encrypt(store, addr, plaintext)
    export_session(creds, store, addr)
    signal_type = "pkmsg" if encrypted.message_type() == 3 else "msg"
    return signal_type, encrypted.serialize(), addr


def build_encrypted_node(creds: dict, recipient_jid: str, payload: proto.Message) -> tuple[BinaryNode, str, address.ProtocolAddress]:
    signal_type, ciphertext, addr = encrypt_for_recipient(creds, recipient_jid, encode_message_payload(payload))
    return BinaryNode("enc", {"v": "2", "type": signal_type}, ciphertext), signal_type, addr


def signed_device_identity_node(creds: dict) -> BinaryNode | None:
    if not creds.get("account"):
        return None
    account = proto.ADVSignedDeviceIdentity()
    account.ParseFromString(unb64(creds["account"]))
    account.ClearField("accountSignatureKey")
    return BinaryNode("device-identity", {}, account.SerializeToString())


def build_text_message_node(
    creds: dict,
    recipient_jid: str,
    text: str,
    *,
    message_id: str | None = None,
    direct_enc: bool = True,
    recipient_device_jids: Iterable[str] | None = None,
    own_fanout_jids: Iterable[str] = (),
    include_phash: bool = False,
) -> OutboundMessage:
    return build_proto_message_node(
        creds,
        recipient_jid,
        text_message(text),
        message_type="text",
        message_id=message_id,
        direct_enc=direct_enc,
        recipient_device_jids=recipient_device_jids,
        own_fanout_jids=own_fanout_jids,
        include_phash=include_phash,
    )


def build_proto_message_node(
    creds: dict,
    recipient_jid: str,
    message: proto.Message,
    *,
    message_type: str,
    message_id: str | None = None,
    direct_enc: bool = True,
    recipient_device_jids: Iterable[str] | None = None,
    own_fanout_jids: Iterable[str] = (),
    include_phash: bool = False,
) -> OutboundMessage:
    message_id = message_id or generate_message_id(creds.get("me", {}).get("id"))
    recipient_user, recipient_server, _ = jid_decode(recipient_jid)
    recipient_device_jid = jid_encode(recipient_user, recipient_server, 0)
    enc_node, signal_type, addr = build_encrypted_node(creds, recipient_device_jid, message)
    signal_types = {recipient_device_jid: signal_type}

    attrs = {"id": message_id, "to": recipient_jid, "type": message_type}
    if direct_enc:
        content = [enc_node]
        participant_jids = [recipient_device_jid]
    else:
        participant_nodes = []
        participant_jids = []
        target_jids = list(recipient_device_jids) if recipient_device_jids is not None else [recipient_device_jid]
        for target_jid in target_jids:
            target_enc, target_type, _ = (
                (enc_node, signal_type, addr)
                if target_jid == recipient_device_jid
                else build_encrypted_node(creds, target_jid, message)
            )
            participant_nodes.append(BinaryNode("to", {"jid": target_jid}, [target_enc]))
            participant_jids.append(target_jid)
            signal_types[target_jid] = target_type

        for own_jid in own_fanout_jids:
            own_user, own_server, own_device = jid_decode(own_jid)
            own_device_jid = jid_encode(own_user, own_server, own_device)
            own_payload = device_sent_message(recipient_jid, message)
            own_enc, _, _ = build_encrypted_node(creds, own_device_jid, own_payload)
            own_type = own_enc.attrs["type"]
            participant_nodes.append(BinaryNode("to", {"jid": own_device_jid}, [own_enc]))
            participant_jids.append(own_device_jid)
            signal_types[own_device_jid] = own_type

        if include_phash:
            attrs["phash"] = participant_hash_v2(participant_jids)
        content = [
            BinaryNode(
                "participants",
                {},
                participant_nodes,
            )
        ]
        if "pkmsg" in signal_types.values():
            device_identity = signed_device_identity_node(creds)
            if device_identity is not None:
                content.append(device_identity)

    return OutboundMessage(
        node=BinaryNode("message", attrs, content),
        message_id=message_id,
        signal_type=signal_type,
        recipient_address=addr,
        participant_jids=participant_jids,
        signal_types=signal_types,
    )
