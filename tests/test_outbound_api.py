from __future__ import annotations

import asyncio

import baileys as b
from baileys.auth_state import AuthState, JsonCredentialStore
from baileys.generated import WAProto_pb2 as proto
from baileys.media import EncryptedMedia, MediaPayload, MediaUploadResult, media_message, read_media_payload
import baileys.message_send as message_send_module
from baileys.message_send import OutboundMessage, build_proto_message_node, normalize_message_content
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

    location, kind = normalize_message_content({"location": {"latitude": 12.3, "longitude": 45.6, "name": "Spot"}})
    assert kind == "location"
    assert location.locationMessage.degreesLatitude == 12.3
    assert location.locationMessage.name == "Spot"

    contact, kind = normalize_message_content({"contact": {"display_name": "Alice", "vcard": "BEGIN:VCARD"}})
    assert kind == "contact"
    assert contact.contactMessage.displayName == "Alice"


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
