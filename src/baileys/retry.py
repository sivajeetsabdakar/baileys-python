from __future__ import annotations

from dataclasses import dataclass

from signal_protocol import address, curve, identity_key, session, state

from baileys.auth_store import build_signal_store, export_session, prefixed_public, unb64
from baileys.defaults import KEY_BUNDLE_TYPE
from baileys.message_send import jid_decode, signed_device_identity_node
from baileys.prekeys import xmpp_pre_key, xmpp_signed_pre_key
from baileys.registration import encode_big_endian
from baileys.socket_nodes import find_child, node_content_bytes
from baileys.wabinary import BinaryNode


@dataclass(frozen=True)
class RetrySessionBundle:
    registration_id: int
    pre_key_id: int | None
    pre_key_public: bytes | None
    signed_pre_key_id: int
    signed_pre_key_public: bytes
    signed_pre_key_signature: bytes
    identity_public: bytes


def retry_receipt_node(
    creds: dict,
    failed_node_attrs: dict[str, str],
    *,
    receipt_id: str | None = None,
    retry_count: int = 1,
    force_include_keys: bool = False,
    error: str = "0",
    pre_key_id: int | None = None,
) -> BinaryNode:
    attrs = {
        "id": receipt_id or failed_node_attrs["id"],
        "type": "retry",
        "to": failed_node_attrs["from"],
    }
    if failed_node_attrs.get("recipient"):
        attrs["recipient"] = failed_node_attrs["recipient"]
    if failed_node_attrs.get("participant"):
        attrs["participant"] = failed_node_attrs["participant"]

    retry_attrs = {
        "count": str(retry_count),
        "id": failed_node_attrs["id"],
        "v": "1",
        "error": error,
    }
    if failed_node_attrs.get("t"):
        retry_attrs["t"] = failed_node_attrs["t"]

    content = [
        BinaryNode("retry", retry_attrs),
        BinaryNode("registration", {}, encode_big_endian(int(creds["registration_id"]))),
    ]
    if force_include_keys or retry_count > 1:
        content.append(_retry_keys_node(creds, pre_key_id=pre_key_id))
    return BinaryNode("receipt", attrs, content)


def retry_count_from_receipt(node: BinaryNode) -> int | None:
    retry = find_child(node, "retry")
    if retry is None or "count" not in retry.attrs:
        return None
    return int(retry.attrs["count"])


def extract_retry_session_bundle(node: BinaryNode) -> RetrySessionBundle | None:
    keys = find_child(node, "keys")
    if keys is None:
        return None
    key_type = node_content_bytes(find_child(keys, "type"))
    if key_type != KEY_BUNDLE_TYPE:
        raise ValueError(f"unsupported retry key bundle type: {key_type!r}")

    registration = _required_uint_child(node, "registration", 4)
    identity = _required_bytes_child(keys, "identity")
    signed = _required_child(keys, "skey")
    prekey = find_child(keys, "key")

    if prekey is None:
        pre_key_id = None
        pre_key_public = None
    else:
        pre_key_id = _required_uint_child(prekey, "id", 3)
        pre_key_public = _required_bytes_child(prekey, "value")

    return RetrySessionBundle(
        registration_id=registration,
        pre_key_id=pre_key_id,
        pre_key_public=pre_key_public,
        signed_pre_key_id=_required_uint_child(signed, "id", 3),
        signed_pre_key_public=_required_bytes_child(signed, "value"),
        signed_pre_key_signature=_required_bytes_child(signed, "signature"),
        identity_public=identity,
    )


def inject_retry_session_from_receipt(creds: dict, receipt: BinaryNode, participant_jid: str) -> RetrySessionBundle | None:
    bundle = extract_retry_session_bundle(receipt)
    if bundle is None:
        return None

    _, _, device = jid_decode(participant_jid)
    prekey_public = _public_key(bundle.pre_key_public) if bundle.pre_key_public is not None else None
    prekey_bundle = state.PreKeyBundle(
        bundle.registration_id,
        device,
        bundle.pre_key_id,
        prekey_public,
        bundle.signed_pre_key_id,
        _public_key(bundle.signed_pre_key_public),
        bundle.signed_pre_key_signature,
        identity_key.IdentityKey(prefixed_public(bundle.identity_public)),
    )

    store = build_signal_store(creds)
    user, _, _ = jid_decode(participant_jid)
    addr = address.ProtocolAddress(user, device)
    session.process_prekey_bundle(addr, store, prekey_bundle)
    export_session(creds, store, addr)
    return bundle


def _retry_keys_node(creds: dict, *, pre_key_id: int | None = None) -> BinaryNode:
    pre_keys = creds.get("pre_keys") or {}
    if pre_key_id is None:
        try:
            pre_key_id = min(int(key_id) for key_id in pre_keys)
        except ValueError as exc:
            raise ValueError("retry key bundle requested but creds has no pre_keys") from exc
    pair = pre_keys.get(str(pre_key_id))
    if pair is None:
        raise ValueError(f"missing pre_key_id {pre_key_id}")

    children = [
        BinaryNode("type", {}, KEY_BUNDLE_TYPE),
        BinaryNode("identity", {}, unb64(creds["identity_public"])),
        xmpp_pre_key(pair, pre_key_id),
        xmpp_signed_pre_key(creds),
    ]
    device_identity = signed_device_identity_node(creds)
    if device_identity is not None:
        children.append(device_identity)
    return BinaryNode("keys", {}, children)


def _public_key(value: bytes) -> curve.PublicKey:
    return curve.PublicKey.deserialize(prefixed_public(value))


def _required_child(node: BinaryNode, tag: str) -> BinaryNode:
    child = find_child(node, tag)
    if child is None:
        raise ValueError(f"missing {tag!r} child in {node.tag!r}")
    return child


def _required_bytes_child(node: BinaryNode, tag: str) -> bytes:
    content = node_content_bytes(_required_child(node, tag))
    if content is None:
        raise ValueError(f"missing bytes for {tag!r} child")
    return content


def _required_uint_child(node: BinaryNode, tag: str, length: int) -> int:
    content = _required_bytes_child(node, tag)
    if len(content) > length:
        raise ValueError(f"{tag!r} child too long: {len(content)} > {length}")
    return int.from_bytes(content.rjust(length, b"\x00"), "big")
