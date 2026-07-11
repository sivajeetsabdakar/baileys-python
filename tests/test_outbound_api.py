from __future__ import annotations

import asyncio

import baileys as b
from baileys.auth_state import AuthState, JsonCredentialStore
from baileys.generated import WAProto_pb2 as proto
from baileys.media import (
    EncryptedMedia,
    MediaPayload,
    MediaRetryEvent,
    MediaUploadResult,
    decode_media_retry_node,
    decrypt_media_retry_data,
    encrypt_media_retry_request,
    encrypt_media_retry_response,
    media_message,
    read_media_payload,
)
import baileys.message_send as message_send_module
from baileys.message_send import (
    OutboundMessage,
    UnsupportedMessageContent,
    build_proto_message_node,
    normalize_message_content,
)
from baileys.receipts import RetryRequest
from baileys.socket import WhatsAppClient, make_socket
from baileys.wabinary import BinaryNode


def _minimal_creds() -> dict:
    return {"me": {"id": "me@s.whatsapp.net", "name": "Me"}}


def test_message_content_builders_cover_common_shapes():
    text, kind = normalize_message_content({"text": "hello", "mentions": ["123@s.whatsapp.net"]})
    assert kind == "text"
    assert text.extendedTextMessage.text == "hello"
    assert text.extendedTextMessage.contextInfo.mentionedJid == ["123@s.whatsapp.net"]

    key = {"remote_jid": "chat@s.whatsapp.net", "id": "m1", "from_me": False}
    reaction, kind = normalize_message_content({"reaction": {"key": key, "text": ":)"}})
    assert kind == "reaction"
    assert reaction.reactionMessage.key.id == "m1"
    assert reaction.reactionMessage.text == ":)"

    edit, kind = normalize_message_content({"edit": {"key": key, "text": "fixed"}})
    assert kind == "protocol"
    assert edit.protocolMessage.type == proto.Message.ProtocolMessage.Type.MESSAGE_EDIT
    assert edit.protocolMessage.editedMessage.conversation == "fixed"

    delete, kind = normalize_message_content({"delete": key})
    assert kind == "protocol"
    assert delete.protocolMessage.type == proto.Message.ProtocolMessage.Type.REVOKE

    pin, kind = normalize_message_content({"pin": {"key": key, "pin": True, "duration": 3600}})
    assert kind == "text"
    assert pin.pinInChatMessage.key.id == "m1"
    assert pin.pinInChatMessage.type == proto.Message.PinInChatMessage.PIN_FOR_ALL
    assert pin.messageContextInfo.messageAddOnDurationInSecs == 3600

    unpin, kind = normalize_message_content({"pin": {"key": key, "pin": False}})
    assert kind == "text"
    assert unpin.pinInChatMessage.type == proto.Message.PinInChatMessage.UNPIN_FOR_ALL
    assert unpin.messageContextInfo.messageAddOnDurationInSecs == 0

    poll, kind = normalize_message_content({"poll": {"name": "Choose", "values": ["One", "Two"], "selectable_count": 1}})
    assert kind == "poll"
    assert poll.pollCreationMessageV3.name == "Choose"
    assert [item.optionName for item in poll.pollCreationMessageV3.options] == ["One", "Two"]

    multi_poll, kind = normalize_message_content(
        {"poll": {"name": "Choose many", "values": ["One", "Two"], "selectable_count": 2}}
    )
    assert kind == "poll"
    assert multi_poll.pollCreationMessage.name == "Choose many"
    assert multi_poll.pollCreationMessage.selectableOptionsCount == 2

    location, kind = normalize_message_content({"location": {"latitude": 12.3, "longitude": 45.6, "name": "Spot"}})
    assert kind == "location"
    assert location.locationMessage.degreesLatitude == 12.3
    assert location.locationMessage.name == "Spot"

    contact, kind = normalize_message_content({"contact": {"display_name": "Alice", "vcard": "BEGIN:VCARD"}})
    assert kind == "contact"
    assert contact.contactMessage.displayName == "Alice"

    group_invite, kind = normalize_message_content(
        {
            "group_invite": {
                "jid": "123@g.us",
                "invite_code": "abc123",
                "invite_expiration": 12345,
                "subject": "Test Group",
                "caption": "Join",
            }
        }
    )
    assert kind == "url"
    assert group_invite.groupInviteMessage.groupJid == "123@g.us"
    assert group_invite.groupInviteMessage.inviteCode == "abc123"
    assert group_invite.groupInviteMessage.inviteExpiration == 12345
    assert group_invite.groupInviteMessage.groupName == "Test Group"
    assert group_invite.groupInviteMessage.caption == "Join"


def test_message_content_builders_reject_invalid_poll_and_pin():
    key = {"remote_jid": "chat@s.whatsapp.net", "id": "m1", "from_me": False}
    try:
        normalize_message_content({"pin": {"id": key}})
    except UnsupportedMessageContent as exc:
        assert "pin content requires a key" in str(exc)
    else:
        raise AssertionError("expected pin validation error")

    try:
        normalize_message_content({"poll": {"name": "Bad", "values": [], "selectable_count": 1}})
    except UnsupportedMessageContent as exc:
        assert "poll content requires at least one option" in str(exc)
    else:
        raise AssertionError("expected poll option validation error")

    try:
        normalize_message_content({"poll": {"name": "Bad", "values": ["One"], "selectable_count": 2}})
    except UnsupportedMessageContent as exc:
        assert "poll selectable_count" in str(exc)
    else:
        raise AssertionError("expected poll selectable count validation error")


def test_media_payload_and_message_builders(tmp_path):
    file_path = tmp_path / "note.txt"
    file_path.write_text("hello", encoding="utf-8")
    payload = read_media_payload(file_path, "document", caption="doc")
    encrypted = EncryptedMedia(
        media_key=b"k" * 32,
        encrypted=b"encrypted",
        mac=b"mac",
        file_sha256=b"sha",
        file_enc_sha256=b"encsha",
        file_length=len(payload.data),
    )
    upload = MediaUploadResult(media_url="https://host/file", direct_path="/v/t/file", host="host")

    message = media_message(encrypted, upload, payload)

    assert payload.filename == "note.txt"
    assert message.documentMessage.fileName == "note.txt"
    assert message.documentMessage.caption == "doc"
    assert message.documentMessage.directPath == "/v/t/file"


def test_media_retry_request_and_response_round_trip():
    key = b.MessageKey("chat@s.whatsapp.net", "m1", from_me=False, participant="sender@s.whatsapp.net")
    media_key = b"k" * 32
    request = encrypt_media_retry_request(key, media_key, "me@s.whatsapp.net")

    assert request.tag == "receipt"
    assert request.attrs == {"id": "m1", "to": "me@s.whatsapp.net", "type": "server-error"}
    assert request.content[0].tag == "encrypt"
    assert request.content[1].attrs == {
        "jid": "chat@s.whatsapp.net",
        "from_me": "false",
        "participant": "sender@s.whatsapp.net",
    }

    encrypted = encrypt_media_retry_response(media_key, "m1", "/v/t/new")
    response = BinaryNode(
        "receipt",
        {"id": "m1"},
        [
            BinaryNode("encrypt", {}, [BinaryNode("enc_p", {}, encrypted["ciphertext"]), BinaryNode("enc_iv", {}, encrypted["iv"])]),
            BinaryNode("rmr", {"jid": "chat@s.whatsapp.net", "from_me": "false"}),
        ],
    )
    event = decode_media_retry_node(response)

    assert event is not None
    assert event.key["id"] == "m1"
    assert event.error is None
    retry = decrypt_media_retry_data(event.media, media_key, "m1")  # type: ignore[arg-type]
    assert retry.result == proto.MediaRetryNotification.ResultType.SUCCESS
    assert retry.directPath == "/v/t/new"


def test_update_media_message_requests_reupload_and_updates_content(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        sent = []
        updates = []
        client.ev.on("messages.update", lambda payload: updates.extend(payload))
        media_key = b"k" * 32
        message = proto.Message()
        message.imageMessage.mediaKey = media_key
        message.imageMessage.directPath = "/v/t/old"
        wa_message = b.WAMessage(b.MessageKey("chat@s.whatsapp.net", "m1", from_me=False), message)

        async def fake_send_node(node):
            sent.append(node)
            encrypted = encrypt_media_retry_response(media_key, "m1", "/v/t/new")
            await client.ev.emit(
                "messages.media-update",
                [MediaRetryEvent(key={"id": "m1"}, media=encrypted)],
            )

        client.send_node = fake_send_node  # type: ignore[method-assign]

        result = await client.update_media_message(wa_message)

        assert result is wa_message
        assert sent[0].attrs["type"] == "server-error"
        assert sent[0].content[1].tag == "rmr"
        assert message.imageMessage.directPath == "/v/t/new"
        assert message.imageMessage.url == "https://mmg.whatsapp.net/v/t/new"
        assert updates[0]["key"]["id"] == "m1"
        assert updates[0]["update"]["message"] is message
        assert client.updateMediaMessage.__func__ is client.update_media_message.__func__

    asyncio.run(scenario())


def test_proto_message_builder_accepts_additional_attributes():
    message = proto.Message()
    message.conversation = "hello"
    original = message_send_module.build_encrypted_node

    def fake_build_encrypted_node(creds, recipient_jid, payload):
        return BinaryNode("enc", {"type": "msg"}, b"ciphertext"), "msg", None

    message_send_module.build_encrypted_node = fake_build_encrypted_node  # type: ignore[assignment]
    try:
        outbound = build_proto_message_node(
            _minimal_creds(),
            "chat@s.whatsapp.net",
            message,
            message_type="text",
            additional_attributes={"category": "peer", "push_priority": "high_force"},
            additional_nodes=[BinaryNode("meta", {"appdata": "default"})],
        )
    finally:
        message_send_module.build_encrypted_node = original

    assert outbound.node.attrs["category"] == "peer"
    assert outbound.node.attrs["push_priority"] == "high_force"
    assert outbound.node.content[-1].tag == "meta"


def test_protocol_message_builder_uses_text_stanza_type():
    message = proto.Message()
    message.protocolMessage.type = proto.Message.ProtocolMessage.APP_STATE_SYNC_KEY_REQUEST
    original = message_send_module.build_encrypted_node

    def fake_build_encrypted_node(creds, recipient_jid, payload):
        return BinaryNode("enc", {"type": "msg"}, b"ciphertext"), "msg", None

    message_send_module.build_encrypted_node = fake_build_encrypted_node  # type: ignore[assignment]
    try:
        outbound = message_send_module.build_message_content_node(
            _minimal_creds(),
            "chat@s.whatsapp.net",
            message,
        )
    finally:
        message_send_module.build_encrypted_node = original

    assert outbound.node.attrs["type"] == "text"


def test_relay_message_caches_and_retry_replays(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.sent = []

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        node = BinaryNode("message", {"id": "m1", "to": "chat@s.whatsapp.net", "type": "text"})

        result = await client.relay_message("chat@s.whatsapp.net", node)
        resent = await client.resend_message_for_retry(
            RetryRequest(
                key=b.MessageKey("chat@s.whatsapp.net", "m1", from_me=True),
                ids=["m1"],
                retry_count=1,
                error_code=None,
                node=BinaryNode("receipt", {"type": "retry"}),
            )
        )

        assert result.message_id == "m1"
        assert resent is True
        assert client._web.sent == [node, node]
        assert client.sendMessage.__func__ is client.send_message.__func__
        assert client.relayMessage.__func__ is client.relay_message.__func__

    asyncio.run(scenario())


def test_send_message_uses_build_and_relay(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        sent = []

        async def fake_build(jid, content, **kwargs):
            return OutboundMessage(
                node=BinaryNode("message", {"id": "m2", "to": jid, "type": "text"}),
                message_id="m2",
                signal_type="msg",
                recipient_address=None,  # type: ignore[arg-type]
                participant_jids=["chat:0@s.whatsapp.net"],
                signal_types={"chat:0@s.whatsapp.net": "msg"},
            )

        async def fake_relay(jid, outbound, **kwargs):
            sent.append((jid, outbound.message_id))
            return b.SendMessageResult(outbound.message_id, jid, "text", outbound.participant_jids, outbound.signal_types)

        client._build_outbound_message = fake_build  # type: ignore[method-assign]
        client.relay_message = fake_relay  # type: ignore[method-assign]

        result = await client.send_message("chat@s.whatsapp.net", "hello")

        assert result.message_id == "m2"
        assert sent == [("chat@s.whatsapp.net", "m2")]

    asyncio.run(scenario())
