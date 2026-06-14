from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from signal_protocol import address, group_cipher, identity_key, protocol, sender_keys, session_cipher, storage

from baileys.auth_store import (
    build_signal_store,
    export_sender_key,
    export_session,
    mark_pre_key_consumed,
    save_creds,
    unb64,
)
from baileys.generated import WAProto_pb2 as proto


@dataclass(frozen=True)
class DecryptedNode:
    stanza_id: str | None
    enc_type: str
    address: address.ProtocolAddress | None
    message: proto.Message
    sender_key_name: sender_keys.SenderKeyName | None = None


def user_and_device(jid: str) -> tuple[str, int]:
    left = jid.split("@", 1)[0]
    if ":" in left:
        user, device = left.split(":", 1)
        return user, int(device)
    return left, 0


def candidate_addresses(stanza_attrs: dict, creds: dict) -> Iterable[address.ProtocolAddress]:
    seen: set[tuple[str, int]] = set()
    me = creds.get("me") or {}
    own_device = None
    if me.get("id"):
        own_device = user_and_device(me["id"])[1]

    candidates = [stanza_attrs.get("from"), me.get("id"), me.get("lid")]
    for jid in candidates:
        if not jid:
            continue
        user, device = user_and_device(jid)
        devices = [device, 0]
        if own_device is not None:
            devices.append(own_device)
        for maybe_device in dict.fromkeys(devices):
            key = (user, maybe_device)
            if key not in seen:
                seen.add(key)
                yield address.ProtocolAddress(user, maybe_device)


def unpad_random_max_16(data: bytes) -> bytes:
    if not data:
        raise ValueError("empty padded data")
    pad = data[-1]
    if pad > len(data):
        raise ValueError(f"invalid pad {pad} for {len(data)} bytes")
    return data[:-pad]


def pad_random_max_16(data: bytes, pad: int = 1) -> bytes:
    if pad < 1 or pad > 16:
        raise ValueError("pad must be between 1 and 16")
    return data + bytes([pad]) * pad


def first_enc(node: dict) -> tuple[dict, bytes] | None:
    for child in node.get("content") or []:
        if child.get("tag") == "enc":
            content = child.get("content") or {}
            return child, unb64(content["base64"])
    return None


def sender_jid_for_group_node(attrs: dict) -> str | None:
    return attrs.get("participant") or attrs.get("participant_lid") or attrs.get("participant_pn")


def sender_key_name_for_node(attrs: dict) -> sender_keys.SenderKeyName:
    group_jid = attrs.get("from")
    author_jid = sender_jid_for_group_node(attrs)
    if not group_jid or not group_jid.endswith("@g.us"):
        raise ValueError(f"not a group stanza: {attrs!r}")
    if not author_jid:
        raise ValueError(f"group stanza has no participant author: {attrs!r}")
    user, device = user_and_device(author_jid)
    return sender_keys.SenderKeyName(group_jid, address.ProtocolAddress(user, device))


def unwrap_device_sent_message(message: proto.Message) -> proto.Message:
    if message.HasField("deviceSentMessage"):
        return message.deviceSentMessage.message
    return message


def process_sender_key_distribution_message(
    creds: dict,
    message: proto.Message,
    author_jid: str,
    *,
    persist_creds_path: str | Path | None = None,
) -> bool:
    if not message.HasField("senderKeyDistributionMessage"):
        return False
    item = message.senderKeyDistributionMessage
    if not item.groupId or not item.axolotlSenderKeyDistributionMessage:
        raise ValueError("sender key distribution message missing group id or axolotl bytes")

    user, device = user_and_device(author_jid)
    sender_name = sender_keys.SenderKeyName(item.groupId, address.ProtocolAddress(user, device))
    store = build_signal_store(creds)
    distribution = _sender_key_distribution_message_from_bytes(item.axolotlSenderKeyDistributionMessage)
    group_cipher.process_sender_key_distribution_message(sender_name, distribution, store)
    export_sender_key(creds, store, sender_name)
    if persist_creds_path is not None:
        save_creds(persist_creds_path, creds)
    return True


def _sender_key_distribution_message_from_bytes(data: bytes):
    dummy_store = storage.InMemSignalProtocolStore(identity_key.IdentityKeyPair.generate(), 1)
    dummy_name = sender_keys.SenderKeyName("dummy@g.us", address.ProtocolAddress("dummy", 1))
    dummy_distribution = group_cipher.create_sender_key_distribution_message(dummy_name, dummy_store)
    return type(dummy_distribution).try_from(data)


def parse_plaintext_message(plaintext: bytes) -> proto.Message:
    message = proto.Message()
    message.ParseFromString(unpad_random_max_16(plaintext))
    return unwrap_device_sent_message(message)


def decrypt_message_node(
    node: dict,
    creds: dict,
    *,
    persist_creds_path: str | Path | None = None,
) -> DecryptedNode | None:
    enc = first_enc(node)
    if not enc:
        return None

    enc_node, ciphertext = enc
    enc_type = enc_node["attrs"].get("type")
    if enc_type not in {"pkmsg", "msg", "skmsg"}:
        return None

    if enc_type == "skmsg":
        store = build_signal_store(creds)
        sender_name = sender_key_name_for_node(node["attrs"])
        plaintext = group_cipher.group_decrypt(ciphertext, store, sender_name)
        export_sender_key(creds, store, sender_name)
        message = parse_plaintext_message(plaintext)
        author = sender_jid_for_group_node(node["attrs"])
        if author:
            process_sender_key_distribution_message(
                creds,
                message,
                author,
                persist_creds_path=None,
            )
        if persist_creds_path is not None:
            save_creds(persist_creds_path, creds)
        return DecryptedNode(
            stanza_id=node.get("attrs", {}).get("id"),
            enc_type=enc_type,
            address=None,
            message=message,
            sender_key_name=sender_name,
        )

    last_error: Exception | None = None
    for addr in candidate_addresses(node["attrs"], creds):
        store = build_signal_store(creds)
        try:
            if enc_type == "pkmsg":
                prekey_message = protocol.PreKeySignalMessage.try_from(ciphertext)
                plaintext = session_cipher.message_decrypt_prekey(store, addr, prekey_message)
                export_session(creds, store, addr)
                mark_pre_key_consumed(creds, prekey_message.pre_key_id())
            else:
                signal_message = protocol.SignalMessage.try_from(ciphertext)
                plaintext = session_cipher.message_decrypt_signal(store, addr, signal_message)
                export_session(creds, store, addr)

            message = parse_plaintext_message(plaintext)
            author = sender_jid_for_group_node(node["attrs"]) or node["attrs"].get("from")
            if author:
                process_sender_key_distribution_message(
                    creds,
                    message,
                    author,
                    persist_creds_path=None,
                )
            if persist_creds_path is not None:
                save_creds(persist_creds_path, creds)
            return DecryptedNode(
                stanza_id=node.get("attrs", {}).get("id"),
                enc_type=enc_type,
                address=addr,
                message=message,
            )
        except Exception as exc:
            last_error = exc

    if last_error is not None:
        raise last_error
    return None


def message_field_names(message: proto.Message) -> list[str]:
    return [field.name for field, _ in message.ListFields()]
