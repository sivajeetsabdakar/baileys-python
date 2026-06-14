from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from signal_protocol import address, curve, identity_key, session, state, storage

from baileys.auth_store import build_signal_store, export_session, prefixed_public
from baileys.message_send import jid_decode
from baileys.socket_nodes import find_child, node_content_bytes
from baileys.wabinary import BinaryNode


S_WHATSAPP_NET = "s.whatsapp.net"


@dataclass(frozen=True)
class InjectedSession:
    jid: str
    address_key: str
    pre_key_id: int | None
    signed_pre_key_id: int
    registration_id: int


@dataclass(frozen=True)
class EncryptUserShape:
    jid: str
    child_tags: list[str]
    error: str | None = None


def encrypt_session_query_node(jids: Iterable[str], tag_id: str, *, force: bool = False) -> BinaryNode:
    users = []
    for jid in jids:
        attrs = {"jid": jid}
        if force:
            attrs["reason"] = "identity"
        users.append(BinaryNode("user", attrs))
    return BinaryNode(
        "iq",
        {"id": tag_id, "xmlns": "encrypt", "type": "get", "to": S_WHATSAPP_NET},
        [BinaryNode("key", {}, users)],
    )


def inject_sessions_from_encrypt_result(creds: dict, node: BinaryNode) -> list[InjectedSession]:
    store = build_signal_store(creds)
    injected = inject_sessions_into_store(creds, store, node)
    for item in injected:
        export_session(creds, store, _protocol_address_for_wire_jid(item.jid))
    return injected


def inject_sessions_into_store(
    creds: dict,
    store: storage.InMemSignalProtocolStore,
    node: BinaryNode,
) -> list[InjectedSession]:
    list_node = find_child(node, "list")
    if not isinstance(list_node.content if list_node else None, list):
        return []

    injected: list[InjectedSession] = []
    for user_node in list_node.content:
        if user_node.tag != "user":
            continue
        if find_child(user_node, "error") is not None or user_node.attrs.get("error"):
            raise ValueError(f"encrypt session query returned user error: {user_node.attrs!r}")
        jid = user_node.attrs["jid"]
        bundle = _prekey_bundle_from_user_node(user_node)
        addr = _protocol_address_for_wire_jid(jid)
        session.process_prekey_bundle(addr, store, bundle)
        injected.append(
            InjectedSession(
                jid=jid,
                address_key=f"{addr.name()}:{addr.device_id()}",
                pre_key_id=bundle.pre_key_id(),
                signed_pre_key_id=bundle.signed_pre_key_id(),
                registration_id=bundle.registration_id(),
            )
        )
    return injected


def summarize_encrypt_user_shapes(node: BinaryNode) -> list[EncryptUserShape]:
    list_node = find_child(node, "list")
    if not isinstance(list_node.content if list_node else None, list):
        return []
    shapes: list[EncryptUserShape] = []
    for user_node in list_node.content:
        if user_node.tag != "user":
            continue
        child_tags = [child.tag for child in user_node.content] if isinstance(user_node.content, list) else []
        error_node = find_child(user_node, "error")
        shapes.append(
            EncryptUserShape(
                jid=user_node.attrs.get("jid", ""),
                child_tags=child_tags,
                error=user_node.attrs.get("error") or (str(error_node.attrs) if error_node else None),
            )
        )
    return shapes


def _prekey_bundle_from_user_node(node: BinaryNode) -> state.PreKeyBundle:
    registration = _required_uint_child(node, "registration", 4)
    signed = _required_child(node, "skey")
    prekey = find_child(node, "key")
    identity = _required_bytes_child(node, "identity")

    signed_key_id = _required_uint_child(signed, "id", 3)
    signed_key_public = _public_key(_required_bytes_child(signed, "value"))
    signed_key_signature = _required_bytes_child(signed, "signature")
    if prekey is not None:
        pre_key_id = _required_uint_child(prekey, "id", 3)
        pre_key_public = _public_key(_required_bytes_child(prekey, "value"))
    else:
        pre_key_id = None
        pre_key_public = None

    _, _, device = jid_decode(node.attrs["jid"])
    return state.PreKeyBundle(
        registration,
        device,
        pre_key_id,
        pre_key_public,
        signed_key_id,
        signed_key_public,
        signed_key_signature,
        identity_key.IdentityKey(prefixed_public(identity)),
    )


def _protocol_address_for_wire_jid(jid: str) -> address.ProtocolAddress:
    user, _, device = jid_decode(jid)
    return address.ProtocolAddress(user, device)


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
