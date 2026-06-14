from __future__ import annotations

from dataclasses import dataclass

from baileys.auth_store import b64, unb64
from baileys.registration import (
    KEY_BUNDLE_TYPE,
    encode_big_endian,
    generate_signal_key_pair,
    signed_key_pair,
)
from baileys.signal_crypto import SignalKeyPair
from baileys.wabinary import BinaryNode


S_WHATSAPP_NET = "s.whatsapp.net"
MIN_PREKEY_COUNT = 5
INITIAL_PREKEY_COUNT = 812


@dataclass(frozen=True)
class PreKeyNodeResult:
    node: BinaryNode
    uploaded_ids: list[int]


@dataclass(frozen=True)
class SignedPreKeyRotation:
    node: BinaryNode
    key_id: int


def _with_id(attrs: dict[str, str], tag_id: str | None) -> dict[str, str]:
    return {**attrs, "id": tag_id} if tag_id else attrs


def _identity_key_pair(creds: dict) -> SignalKeyPair:
    return SignalKeyPair(private=unb64(creds["identity_private"]), public=unb64(creds["identity_public"]))


def xmpp_pre_key(pair: dict[str, str], key_id: int) -> BinaryNode:
    return BinaryNode(
        "key",
        {},
        [
            BinaryNode("id", {}, encode_big_endian(key_id, 3)),
            BinaryNode("value", {}, unb64(pair["public"])),
        ],
    )


def xmpp_signed_pre_key(creds: dict) -> BinaryNode:
    return BinaryNode(
        "skey",
        {},
        [
            BinaryNode("id", {}, encode_big_endian(int(creds["signed_pre_key_id"]), 3)),
            BinaryNode("value", {}, unb64(creds["signed_pre_key_public"])),
            BinaryNode("signature", {}, unb64(creds["signed_pre_key_signature"])),
        ],
    )


def digest_key_bundle_node(tag_id: str | None = None) -> BinaryNode:
    return BinaryNode(
        "iq",
        _with_id({"to": S_WHATSAPP_NET, "type": "get", "xmlns": "encrypt"}, tag_id),
        [BinaryNode("digest", {})],
    )


def generate_or_get_pre_keys(creds: dict, count: int) -> tuple[list[int], list[int]]:
    first_unuploaded = int(creds.get("first_unuploaded_pre_key_id", creds.get("next_pre_key_id", 1)))
    next_id = int(creds.get("next_pre_key_id", 1))
    available = next_id - first_unuploaded
    remaining = count - available
    last_pre_key_id = next_id + remaining - 1
    prekeys = creds.setdefault("pre_keys", {})
    new_ids: list[int] = []

    if remaining > 0:
        for key_id in range(next_id, last_pre_key_id + 1):
            pair = generate_signal_key_pair()
            prekeys[str(key_id)] = {"private": b64(pair.private), "public": b64(pair.public)}
            new_ids.append(key_id)

    uploaded_ids = list(range(first_unuploaded, first_unuploaded + count))
    creds["next_pre_key_id"] = max(last_pre_key_id + 1, next_id)
    creds["first_unuploaded_pre_key_id"] = max(first_unuploaded, last_pre_key_id + 1)
    return uploaded_ids, new_ids


def build_prekey_upload_node(creds: dict, count: int = MIN_PREKEY_COUNT, tag_id: str | None = None) -> PreKeyNodeResult:
    uploaded_ids, _ = generate_or_get_pre_keys(creds, count)
    prekeys = creds.setdefault("pre_keys", {})
    missing = [key_id for key_id in uploaded_ids if str(key_id) not in prekeys]
    if missing:
        raise ValueError(f"missing generated prekeys for ids {missing}")

    node = BinaryNode(
        "iq",
        _with_id({"xmlns": "encrypt", "type": "set", "to": S_WHATSAPP_NET}, tag_id),
        [
            BinaryNode("registration", {}, encode_big_endian(int(creds["registration_id"]))),
            BinaryNode("type", {}, KEY_BUNDLE_TYPE),
            BinaryNode("identity", {}, unb64(creds["identity_public"])),
            BinaryNode("list", {}, [xmpp_pre_key(prekeys[str(key_id)], key_id) for key_id in uploaded_ids]),
            xmpp_signed_pre_key(creds),
        ],
    )
    return PreKeyNodeResult(node=node, uploaded_ids=uploaded_ids)


def rotate_signed_pre_key_node(creds: dict, tag_id: str | None = None) -> SignedPreKeyRotation:
    new_id = int(creds.get("signed_pre_key_id", 0)) + 1
    signed_pre_key, signature = signed_key_pair(_identity_key_pair(creds), new_id)
    creds["signed_pre_key_id"] = new_id
    creds["signed_pre_key_private"] = b64(signed_pre_key.private)
    creds["signed_pre_key_public"] = b64(signed_pre_key.public)
    creds["signed_pre_key_signature"] = b64(signature)

    node = BinaryNode(
        "iq",
        _with_id({"to": S_WHATSAPP_NET, "type": "set", "xmlns": "encrypt"}, tag_id),
        [BinaryNode("rotate", {}, [xmpp_signed_pre_key(creds)])],
    )
    return SignedPreKeyRotation(node=node, key_id=new_id)
