from __future__ import annotations

import asyncio

from signal_protocol import address, curve, identity_key, protocol, session, session_cipher, state, storage

from baileys.auth_state import AuthState, JsonCredentialStore
from baileys.auth_store import build_signal_store, creds_from_generated_signal_material, export_session
from baileys.generated import WAProto_pb2 as proto
from baileys.message_decrypt import pad_random_max_16
from baileys.messages import build_message_upsert
from baileys.socket import make_socket
from baileys.wabinary import BinaryNode


def _signal_key_pair() -> curve.KeyPair:
    public_key, private_key = curve.generate_keypair()
    return curve.KeyPair.from_public_and_private(public_key, private_key)


def _conversation_payload(text: str) -> bytes:
    message = proto.Message()
    message.conversation = text
    return pad_random_max_16(message.SerializeToString())


def _encrypted_message_fixture() -> tuple[dict, BinaryNode]:
    alice_identity = identity_key.IdentityKeyPair.generate()
    bob_identity = identity_key.IdentityKeyPair.generate()
    alice_store = storage.InMemSignalProtocolStore(alice_identity, 1111)

    pre_key_id = 61
    signed_pre_key_id = 62
    pre_key_pair = _signal_key_pair()
    signed_pre_key_pair = _signal_key_pair()
    signed_pre_key_signature = bob_identity.private_key().calculate_signature(
        signed_pre_key_pair.public_key().serialize()
    )
    bob_creds = creds_from_generated_signal_material(
        identity_pair=bob_identity,
        registration_id=2222,
        pre_keys={pre_key_id: pre_key_pair},
        signed_pre_key_id=signed_pre_key_id,
        signed_pre_key_pair=signed_pre_key_pair,
        signed_pre_key_signature=signed_pre_key_signature,
    )
    bob_creds["me"] = {"id": "bob:1@s.whatsapp.net"}

    alice_addr = address.ProtocolAddress("alice", 1)
    bob_addr = address.ProtocolAddress("bob", 1)
    bob_bundle = state.PreKeyBundle(
        2222,
        1,
        pre_key_id,
        pre_key_pair.public_key(),
        signed_pre_key_id,
        signed_pre_key_pair.public_key(),
        signed_pre_key_signature,
        bob_identity.identity_key(),
    )
    session.process_prekey_bundle(bob_addr, alice_store, bob_bundle)

    bob_store = build_signal_store(bob_creds)
    first = session_cipher.message_encrypt(alice_store, bob_addr, _conversation_payload("open session"))
    session_cipher.message_decrypt_prekey(
        bob_store,
        alice_addr,
        protocol.PreKeySignalMessage.try_from(first.serialize()),
    )
    export_session(bob_creds, bob_store, alice_addr)

    bob_reply = session_cipher.message_encrypt(bob_store, alice_addr, _conversation_payload("ack"))
    session_cipher.message_decrypt_signal(
        alice_store,
        bob_addr,
        protocol.SignalMessage.try_from(bob_reply.serialize()),
    )

    ciphertext = session_cipher.message_encrypt(alice_store, bob_addr, _conversation_payload("hello upsert"))
    enc_type = "pkmsg" if ciphertext.message_type() == 3 else "msg"
    node = BinaryNode(
        "message",
        {"id": "msg-1", "from": "alice:1@s.whatsapp.net", "t": "123", "notify": "Alice"},
        [BinaryNode("enc", {"type": enc_type}, ciphertext.serialize())],
    )
    return bob_creds, node


def test_build_message_upsert_decrypts_text_node():
    creds, node = _encrypted_message_fixture()

    upsert = build_message_upsert(node, creds)

    assert upsert is not None
    assert upsert.type == "notify"
    message = upsert.messages[0]
    assert message.key.remote_jid == "alice:1@s.whatsapp.net"
    assert message.key.id == "msg-1"
    assert message.message_timestamp == 123
    assert message.push_name == "Alice"
    assert message.message is not None
    assert message.message.conversation == "hello upsert"
    web_info = message.to_web_message_info()
    assert web_info.key.remoteJid == "alice:1@s.whatsapp.net"
    assert web_info.message.conversation == "hello upsert"


def test_socket_dispatch_emits_messages_upsert_for_decrypted_message(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.sent = []

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        creds, node = _encrypted_message_fixture()
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(creds)
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        seen = []
        client.ev.on("messages.upsert", lambda payload: seen.append(payload))

        kind = await client.dispatch_node(node)

        assert kind.value == "message"
        assert len(seen) == 1
        assert seen[0].messages[0].message.conversation == "hello upsert"
        assert client.store.load_messages("alice:1@s.whatsapp.net")[0].message.conversation == "hello upsert"
        assert client._web.sent[0].tag == "ack"
        assert client._web.sent[0].attrs == {
            "id": "msg-1",
            "to": "alice:1@s.whatsapp.net",
            "class": "message",
            "from": "bob:1@s.whatsapp.net",
        }

    asyncio.run(scenario())
