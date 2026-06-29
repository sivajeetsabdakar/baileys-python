from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Iterable

from signal_protocol import address, curve, identity_key, sender_keys, state, storage

from baileys.auth import AuthCredentials
from baileys.auth_state import JsonCredentialStore
from baileys.defaults import SIGNAL_PUBLIC_PREFIX


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def unb64(value: str) -> bytes:
    return base64.b64decode(value)


def _raw_public(value: bytes) -> bytes:
    return value[1:] if len(value) == 33 and value[:1] == SIGNAL_PUBLIC_PREFIX else value


def prefixed_public(value: str | bytes) -> bytes:
    raw = unb64(value) if isinstance(value, str) else value
    return raw if len(raw) == 33 else SIGNAL_PUBLIC_PREFIX + raw


def identity_pair_from_creds(creds: dict) -> identity_key.IdentityKeyPair:
    serialized = (
        b"\x0a\x21"
        + prefixed_public(creds["identity_public"])
        + b"\x12\x20"
        + unb64(creds["identity_private"])
    )
    return identity_key.IdentityKeyPair.from_bytes(serialized)


def key_pair(public_b64: str, private_b64: str) -> curve.KeyPair:
    return curve.KeyPair.from_public_and_private(prefixed_public(public_b64), unb64(private_b64))


def protocol_address_key(addr: address.ProtocolAddress) -> str:
    return f"{addr.name()}:{addr.device_id()}"


def parse_protocol_address_key(key: str) -> address.ProtocolAddress:
    name, device_id = key.rsplit(":", 1)
    return address.ProtocolAddress(name, int(device_id))


def sender_key_name_key(name: sender_keys.SenderKeyName) -> str:
    sender = name.sender()
    return f"{name.group_id()}|{sender.name()}:{sender.device_id()}"


def parse_sender_key_name_key(key: str) -> sender_keys.SenderKeyName:
    group_id, sender = key.split("|", 1)
    return sender_keys.SenderKeyName(group_id, parse_protocol_address_key(sender))


def load_creds(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_auth_credentials(path: str | Path) -> AuthCredentials:
    return JsonCredentialStore(path).load_typed_credentials()


def save_creds(path: str | Path, creds: dict) -> None:
    Path(path).write_text(json.dumps(creds, indent=2), encoding="utf-8")


def save_auth_credentials(path: str | Path, creds: AuthCredentials) -> None:
    JsonCredentialStore(path).save_typed_credentials(creds)


def build_signal_store(creds: dict) -> storage.InMemSignalProtocolStore:
    store = storage.InMemSignalProtocolStore(identity_pair_from_creds(creds), int(creds["registration_id"]))

    for key_id, item in (creds.get("pre_keys") or {}).items():
        pair = key_pair(item["public"], item["private"])
        store.save_pre_key(int(key_id), state.PreKeyRecord(int(key_id), pair))

    signed_pair = key_pair(creds["signed_pre_key_public"], creds["signed_pre_key_private"])
    signed = state.SignedPreKeyRecord(
        int(creds["signed_pre_key_id"]),
        int(creds.get("signed_pre_key_timestamp", 0)),
        signed_pair,
        unb64(creds["signed_pre_key_signature"]),
    )
    store.save_signed_pre_key(int(creds["signed_pre_key_id"]), signed)

    for addr_key, session_b64 in (creds.get("signal_sessions") or {}).items():
        store.store_session(parse_protocol_address_key(addr_key), state.SessionRecord.deserialize(unb64(session_b64)))

    for name_key, sender_key_b64 in (creds.get("sender_keys") or {}).items():
        store.store_sender_key(parse_sender_key_name_key(name_key), sender_keys.SenderKeyRecord.deserialize(unb64(sender_key_b64)))

    return store


def export_session(creds: dict, store: storage.InMemSignalProtocolStore, addr: address.ProtocolAddress) -> bool:
    record = store.load_session(addr)
    if record is None:
        return False
    creds.setdefault("signal_sessions", {})[protocol_address_key(addr)] = b64(record.serialize())
    return True


def export_sender_key(creds: dict, store: storage.InMemSignalProtocolStore, name: sender_keys.SenderKeyName) -> bool:
    record = store.load_sender_key(name)
    if record is None or record.is_empty():
        return False
    creds.setdefault("sender_keys", {})[sender_key_name_key(name)] = b64(record.serialize())
    return True


def mark_pre_key_consumed(creds: dict, key_id: int | None) -> bool:
    if key_id is None:
        return False
    pre_keys = creds.get("pre_keys") or {}
    removed = pre_keys.pop(str(key_id), None) is not None
    if removed:
        creds["pre_keys"] = pre_keys
    return removed


def export_known_sessions(
    creds: dict,
    store: storage.InMemSignalProtocolStore,
    addrs: Iterable[address.ProtocolAddress],
) -> int:
    count = 0
    for addr in addrs:
        if export_session(creds, store, addr):
            count += 1
    return count


def creds_from_generated_signal_material(
    *,
    identity_pair: identity_key.IdentityKeyPair,
    registration_id: int,
    pre_keys: dict[int, curve.KeyPair] | None = None,
    signed_pre_key_id: int,
    signed_pre_key_pair: curve.KeyPair,
    signed_pre_key_signature: bytes,
    signed_pre_key_timestamp: int = 0,
) -> dict:
    return {
        "identity_public": b64(_raw_public(identity_pair.identity_key().serialize())),
        "identity_private": b64(identity_pair.private_key().serialize()),
        "registration_id": registration_id,
        "pre_keys": {
            str(key_id): {
                "public": b64(_raw_public(pair.public_key().serialize())),
                "private": b64(pair.private_key().serialize()),
            }
            for key_id, pair in (pre_keys or {}).items()
        },
        "signed_pre_key_id": signed_pre_key_id,
        "signed_pre_key_public": b64(_raw_public(signed_pre_key_pair.public_key().serialize())),
        "signed_pre_key_private": b64(signed_pre_key_pair.private_key().serialize()),
        "signed_pre_key_signature": b64(signed_pre_key_signature),
        "signed_pre_key_timestamp": signed_pre_key_timestamp,
    }
