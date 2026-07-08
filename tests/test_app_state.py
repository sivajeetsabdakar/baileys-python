from __future__ import annotations

import base64

from baileys.app_state import (
    app_state_patch_node,
    app_state_sync_key_request_message,
    chat_modification_to_app_patch,
    inject_app_state_sync_key_share,
    lt_hash_subtract_then_add,
)
from baileys.generated import WAProto_pb2 as proto


def _app_state_creds() -> dict:
    key_id = base64.b64encode(b"k" * 32).decode("ascii")
    return {
        "me": {"id": "me@s.whatsapp.net", "name": "Me"},
        "myAppStateKeyId": key_id,
        "app_state_sync_keys": {
            key_id: {
                "keyData": base64.b64encode(b"a" * 32).decode("ascii"),
            }
        },
    }


def test_lt_hash_round_trips_add_and_subtract():
    base = bytes(128)
    first = lt_hash_subtract_then_add(base, [], [b"first"])
    second = lt_hash_subtract_then_add(first, [b"first"], [])

    assert first != base
    assert second == base


def test_chat_modification_builds_expected_patch_types():
    archive = chat_modification_to_app_patch({"archive": True}, "chat@s.whatsapp.net")
    assert archive.patch_type == "regular_low"
    assert archive.index == ["archive", "chat@s.whatsapp.net"]
    assert archive.sync_action.archiveChatAction.archived is True

    push_name = chat_modification_to_app_patch({"pushNameSetting": "New Name"}, "")
    assert push_name.patch_type == "critical_block"
    assert push_name.index == ["setting_pushName"]
    assert push_name.sync_action.pushNameSetting.name == "New Name"


def test_app_state_patch_node_encodes_syncd_patch_and_updates_state():
    creds = _app_state_creds()
    encoded = app_state_patch_node(creds, {"pin": True}, "chat@s.whatsapp.net", "tag-1")

    assert encoded.node.tag == "iq"
    assert encoded.node.attrs["xmlns"] == "w:sync:app:state"
    collection = encoded.node.content[0].content[0]
    assert collection.attrs["name"] == "regular_low"
    assert collection.attrs["version"] == "0"
    patch_bytes = collection.content[0].content
    patch = proto.SyncdPatch()
    patch.ParseFromString(patch_bytes)
    assert patch.keyId.id == b"k" * 32
    assert not patch.HasField("version")
    assert patch.mutations[0].operation == proto.SyncdMutation.SET
    assert len(patch.mutations[0].record.value.blob) > 32

    state = creds["app_state_sync_versions"]["regular_low"]
    assert state["version"] == 1
    assert base64.b64decode(state["hash"]) != bytes(128)


def test_app_state_key_share_updates_credentials():
    key = proto.Message.AppStateSyncKey()
    key.keyId.keyId = b"k" * 32
    key.keyData.keyData = b"a" * 32
    key.keyData.timestamp = 123

    message = proto.Message()
    message.protocolMessage.type = proto.Message.ProtocolMessage.APP_STATE_SYNC_KEY_SHARE
    message.protocolMessage.appStateSyncKeyShare.keys.append(key)

    creds = {}
    key_ids = inject_app_state_sync_key_share(creds, message)

    assert key_ids == [base64.b64encode(b"k" * 32).decode("ascii")]
    assert creds["myAppStateKeyId"] == key_ids[0]
    assert creds["app_state_sync_keys"][key_ids[0]]["keyData"] == base64.b64encode(b"a" * 32).decode("ascii")


def test_app_state_sync_key_request_message_encodes_key_ids():
    key_id = base64.b64encode(b"k" * 32).decode("ascii")

    message = app_state_sync_key_request_message(key_id)

    assert message.protocolMessage.type == proto.Message.ProtocolMessage.APP_STATE_SYNC_KEY_REQUEST
    request = message.protocolMessage.appStateSyncKeyRequest
    assert len(request.keyIds) == 1
    assert request.keyIds[0].keyId == b"k" * 32
