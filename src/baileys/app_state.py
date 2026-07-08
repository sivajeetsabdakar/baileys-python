from __future__ import annotations

import base64
import copy
import json
import os
import sys
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .auth_store import b64, unb64
from .crypto import hkdf, hmac_sign
from .defaults import S_WHATSAPP_NET
from .generated import WAProto_pb2 as proto
from .wabinary import BinaryNode
from .whatsapp_keys import expand_app_state_keys


APP_STATE_KEY_NAMESPACE = "app-state-sync-key"
APP_STATE_VERSION_NAMESPACE = "app-state-sync-version"
PATCH_INFO = b"WhatsApp Patch Integrity"
WA_PATCH_NAMES = (
    "regular_low",
    "regular",
    "regular_high",
    "critical_block",
    "critical_unblock_low",
)


@dataclass
class LTHashState:
    version: int = 0
    hash: bytes = bytes(128)
    index_value_map: dict[str, bytes] = field(default_factory=dict)

    @classmethod
    def from_json(cls, value: dict[str, Any] | None) -> "LTHashState":
        if not value:
            return cls()
        index_value_map = {}
        for key, item in (value.get("indexValueMap") or value.get("index_value_map") or {}).items():
            raw = item.get("valueMac") if isinstance(item, dict) else item
            if raw:
                index_value_map[key] = unb64(raw)
        return cls(
            version=int(value.get("version") or 0),
            hash=unb64(value["hash"]) if value.get("hash") else bytes(128),
            index_value_map=index_value_map,
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "hash": b64(self.hash),
            "indexValueMap": {key: {"valueMac": b64(value)} for key, value in self.index_value_map.items()},
        }


@dataclass(frozen=True)
class AppPatchCreate:
    patch_type: str
    index: list[str]
    sync_action: proto.SyncActionValue
    api_version: int
    operation: int = proto.SyncdMutation.SET


@dataclass(frozen=True)
class EncodedAppPatch:
    node: BinaryNode
    patch: proto.SyncdPatch
    state: LTHashState
    patch_type: str


@dataclass(frozen=True)
class AppStateSnapshotInfo:
    collection: str
    version: int
    records: int
    key_id: str | None
    has_key: bool
    has_more_patches: bool = False

    @property
    def missing_key(self) -> bool:
        return bool(self.key_id and not self.has_key)


def store_app_state_sync_key(credentials: dict[str, Any], key_id: str, key_data: proto.Message.AppStateSyncKeyData) -> None:
    credentials.setdefault("app_state_sync_keys", {})[key_id] = {
        "keyData": b64(key_data.keyData),
        "timestamp": int(key_data.timestamp) if key_data.timestamp else None,
        "raw": b64(key_data.SerializeToString()),
    }
    credentials["myAppStateKeyId"] = key_id


def inject_app_state_sync_key_share(credentials: dict[str, Any], message: proto.Message) -> list[str]:
    if not message.HasField("protocolMessage"):
        return []
    protocol = message.protocolMessage
    if protocol.type != proto.Message.ProtocolMessage.APP_STATE_SYNC_KEY_SHARE:
        return []
    if not protocol.HasField("appStateSyncKeyShare"):
        return []

    key_ids = []
    for item in protocol.appStateSyncKeyShare.keys:
        if not item.HasField("keyId") or not item.keyId.keyId or not item.HasField("keyData"):
            continue
        key_id = b64(item.keyId.keyId)
        store_app_state_sync_key(credentials, key_id, item.keyData)
        key_ids.append(key_id)
    return key_ids


def app_state_sync_key_request_message(key_ids: list[str] | tuple[str, ...] | str) -> proto.Message:
    if isinstance(key_ids, str):
        key_ids = [key_ids]
    message = proto.Message()
    protocol = message.protocolMessage
    protocol.type = proto.Message.ProtocolMessage.APP_STATE_SYNC_KEY_REQUEST
    for key_id in key_ids:
        item = protocol.appStateSyncKeyRequest.keyIds.add()
        item.keyId = unb64(key_id)
    return message


def app_state_sync_request_node(
    collections: list[str] | tuple[str, ...],
    tag_id: str,
    *,
    versions: dict[str, Any] | None = None,
    force_snapshot: bool = True,
) -> BinaryNode:
    content = []
    for name in collections:
        state = LTHashState.from_json((versions or {}).get(name))
        content.append(
            BinaryNode(
                "collection",
                {
                    "name": name,
                    "version": str(state.version),
                    "return_snapshot": str(force_snapshot or state.version == 0).lower(),
                },
            )
        )
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "set", "xmlns": "w:sync:app:state"},
        [BinaryNode("sync", {}, content)],
    )


async def extract_app_state_snapshot_info(
    node: BinaryNode,
    credentials: dict[str, Any],
    download_blob: Callable[[proto.ExternalBlobReference], Awaitable[bytes]],
) -> list[AppStateSnapshotInfo]:
    snapshots: list[AppStateSnapshotInfo] = []
    for sync in _children(node, "sync"):
        for collection in _children(sync, "collection"):
            name = collection.attrs.get("name") or ""
            has_more = collection.attrs.get("has_more_patches") == "true"
            for snapshot_node in _children(collection, "snapshot"):
                if not isinstance(snapshot_node.content, bytes):
                    continue
                blob = proto.ExternalBlobReference()
                blob.ParseFromString(snapshot_node.content)
                snapshot_data = await download_blob(blob)
                snapshot = proto.SyncdSnapshot()
                snapshot.ParseFromString(snapshot_data)
                key_id = b64(snapshot.keyId.id) if snapshot.HasField("keyId") and snapshot.keyId.id else None
                snapshots.append(
                    AppStateSnapshotInfo(
                        collection=name,
                        version=int(snapshot.version.version) if snapshot.HasField("version") else 0,
                        records=len(snapshot.records),
                        key_id=key_id,
                        has_key=bool(key_id and _app_state_key_data(credentials, key_id)),
                        has_more_patches=has_more,
                    )
                )
    return snapshots


def app_state_patch_node(
    credentials: dict[str, Any],
    modification: dict[str, Any],
    jid: str,
    tag_id: str,
) -> EncodedAppPatch:
    patch_create = chat_modification_to_app_patch(modification, jid)
    key_id = credentials.get("myAppStateKeyId")
    if not key_id:
        raise MissingAppStateKey("myAppStateKeyId is not present")
    key_data = _app_state_key_data(credentials, key_id)
    if not key_data:
        raise MissingAppStateKey(f"app-state sync key {key_id!r} is not present")

    states = credentials.setdefault("app_state_sync_versions", {})
    initial = LTHashState.from_json(states.get(patch_create.patch_type))
    encoded = encode_syncd_patch(patch_create, key_id, initial, key_data)
    states[patch_create.patch_type] = encoded.state.to_json()

    node = BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "set", "xmlns": "w:sync:app:state"},
        [
            BinaryNode(
                "sync",
                {},
                [
                    BinaryNode(
                        "collection",
                        {
                            "name": patch_create.patch_type,
                            "version": str(encoded.state.version - 1),
                            "return_snapshot": "false",
                        },
                        [BinaryNode("patch", {}, encoded.patch.SerializeToString())],
                    )
                ],
            )
        ],
    )
    return EncodedAppPatch(node=node, patch=encoded.patch, state=encoded.state, patch_type=patch_create.patch_type)


def encode_syncd_patch(
    patch_create: AppPatchCreate,
    key_id: str,
    state: LTHashState,
    key_data: bytes,
) -> EncodedAppPatch:
    enc_key_id = unb64(key_id)
    state = copy.deepcopy(state)
    index_buffer = json.dumps(patch_create.index, separators=(",", ":")).encode("utf-8")

    action_data = proto.SyncActionData()
    action_data.index = index_buffer
    action_data.value.CopyFrom(patch_create.sync_action)
    action_data.padding = b""
    action_data.version = patch_create.api_version
    encoded_action = action_data.SerializeToString()

    keys = expand_app_state_keys(key_data)
    encrypted_value = _aes_encrypt_prefix_iv(encoded_action, keys.value_encryption_key)
    value_mac = generate_content_mac(patch_create.operation, encrypted_value, enc_key_id, keys.value_mac_key)
    index_mac = hmac_sign(index_buffer, keys.index_key)

    previous = state.index_value_map.get(b64(index_mac))
    subtract = [previous] if previous else []
    state.hash = lt_hash_subtract_then_add(state.hash, subtract, [value_mac])
    state.version += 1
    state.index_value_map[b64(index_mac)] = value_mac

    snapshot_mac = generate_snapshot_mac(state.hash, state.version, patch_create.patch_type, keys.snapshot_mac_key)
    patch_mac = generate_patch_mac(snapshot_mac, [value_mac], state.version, patch_create.patch_type, keys.patch_mac_key)

    mutation = proto.SyncdMutation()
    mutation.operation = patch_create.operation
    mutation.record.index.blob = index_mac
    mutation.record.value.blob = encrypted_value + value_mac
    mutation.record.keyId.id = enc_key_id

    patch = proto.SyncdPatch()
    patch.patchMac = patch_mac
    patch.snapshotMac = snapshot_mac
    patch.keyId.id = enc_key_id
    patch.mutations.append(mutation)
    return EncodedAppPatch(node=BinaryNode("patch", {}, patch.SerializeToString()), patch=patch, state=state, patch_type=patch_create.patch_type)


def chat_modification_to_app_patch(modification: dict[str, Any], jid: str) -> AppPatchCreate:
    value = proto.SyncActionValue()
    value.timestamp = int(time.time() * 1000)
    if "mute" in modification:
        mute = int(modification.get("mute") or 0)
        value.muteAction.muted = bool(mute)
        if mute:
            value.muteAction.muteEndTimestamp = mute
        return AppPatchCreate("regular_high", ["mute", jid], value, 2)
    if "archive" in modification:
        value.archiveChatAction.archived = bool(modification["archive"])
        return AppPatchCreate("regular_low", ["archive", jid], value, 3)
    if "pin" in modification:
        value.pinAction.pinned = bool(modification["pin"])
        return AppPatchCreate("regular_low", ["pin_v1", jid], value, 5)
    if "star" in modification:
        star = modification["star"]
        if not isinstance(star, dict) or not star.get("messages"):
            raise ValueError("star modification requires messages")
        key = star["messages"][0]
        value.starAction.starred = bool(star.get("star"))
        return AppPatchCreate(
            "regular_low",
            ["star", jid, str(key["id"]), "1" if key.get("from_me") or key.get("fromMe") else "0", "0"],
            value,
            2,
        )
    if "delete" in modification:
        return AppPatchCreate("regular_high", ["deleteChat", jid, "1"], value, 6)
    if "pushNameSetting" in modification:
        value.pushNameSetting.name = str(modification["pushNameSetting"])
        return AppPatchCreate("critical_block", ["setting_pushName"], value, 1)
    raise ValueError(f"unsupported chat modification keys: {', '.join(sorted(modification))}")


def generate_content_mac(operation: int, data: bytes, key_id: bytes, key: bytes) -> bytes:
    op_byte = b"\x01" if operation == proto.SyncdMutation.SET else b"\x02"
    length = (len(key_id) + 1).to_bytes(8, "big")
    return hmac_sign(op_byte + key_id + data + length, key, "sha512")[:32]


def generate_snapshot_mac(lt_hash: bytes, version: int, name: str, key: bytes) -> bytes:
    if len(lt_hash) != 128:
        raise ValueError("LT hash must be 128 bytes")
    return hmac_sign(lt_hash + version.to_bytes(8, "big") + name.encode("utf-8"), key)


def generate_patch_mac(snapshot_mac: bytes, value_macs: list[bytes], version: int, name: str, key: bytes) -> bytes:
    return hmac_sign(snapshot_mac + b"".join(value_macs) + version.to_bytes(8, "big") + name.encode("utf-8"), key)


def lt_hash_subtract_then_add(base: bytes, subtract: list[bytes], add: list[bytes]) -> bytes:
    if len(base) != 128:
        raise ValueError("base LT hash must be 128 bytes")
    output = bytearray(base)
    for item in subtract:
        _lt_hash_apply(output, item, subtract=True)
    for item in add:
        _lt_hash_apply(output, item, subtract=False)
    return bytes(output)


def _lt_hash_apply(base: bytearray, item: bytes, *, subtract: bool) -> None:
    derived = hkdf(item, 128, info=PATCH_INFO)
    byteorder = sys.byteorder
    for offset in range(0, 128, 2):
        current = int.from_bytes(base[offset : offset + 2], byteorder)
        delta = int.from_bytes(derived[offset : offset + 2], byteorder)
        value = (current - delta if subtract else current + delta) & 0xFFFF
        base[offset : offset + 2] = value.to_bytes(2, byteorder)


def _aes_encrypt_prefix_iv(data: bytes, key: bytes) -> bytes:
    iv = os.urandom(16)
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return iv + encryptor.update(padded) + encryptor.finalize()


def _app_state_key_data(credentials: dict[str, Any], key_id: str) -> bytes | None:
    keys = credentials.get("app_state_sync_keys") or credentials.get("app-state-sync-key") or {}
    raw = keys.get(key_id)
    if raw is None:
        return None
    if isinstance(raw, str):
        return unb64(raw)
    if isinstance(raw, dict):
        if raw.get("keyData"):
            return unb64(raw["keyData"])
        if raw.get("raw"):
            message = proto.Message.AppStateSyncKeyData()
            message.ParseFromString(unb64(raw["raw"]))
            return message.keyData
    return None


def _children(node: BinaryNode, tag: str) -> list[BinaryNode]:
    if not isinstance(node.content, list):
        return []
    return [child for child in node.content if isinstance(child, BinaryNode) and child.tag == tag]


class MissingAppStateKey(RuntimeError):
    pass
