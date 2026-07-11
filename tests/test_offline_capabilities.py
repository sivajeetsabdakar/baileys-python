import base64
import pytest

from baileys.crypto import (
    aes_decrypt_gcm,
    aes_encrypt_gcm,
    decompress_if_required,
    derive_pairing_code_key,
    generate_x25519_key_pair,
    hkdf,
    md5,
    sha256,
    x25519_shared_key,
)
from baileys.auth_store import (
    b64,
    build_signal_store,
    creds_from_generated_signal_material,
    export_session,
    mark_pre_key_consumed,
    protocol_address_key,
)
from baileys.group_sender_probe import run_group_sender_round_trip
from baileys.generated import WAProto_pb2 as proto
from baileys.message_decrypt import decrypt_message_node, pad_random_max_16
from baileys.message_decrypt import parse_plaintext_message, process_sender_key_distribution_message
from baileys.message_send import build_text_message_node
from baileys.media import decrypt_media, encrypt_media, media_conn_node, parse_media_conn, upload_token
from baileys.pairing_code import (
    LINK_CODE_KEY_BUNDLE_INFO,
    bytes_to_crockford,
    decrypt_link_public_key,
    generate_pairing_key,
    normalize_phone_number,
    pairing_code_finish_node,
    pairing_code_hello_node,
    phone_jid,
)
from baileys.prekeys import build_prekey_upload_node, digest_key_bundle_node, rotate_signed_pre_key_node
from baileys.registration import encode_big_endian
from baileys.session_assert import encrypt_session_query_node, inject_sessions_from_encrypt_result
from baileys.socket_nodes import SocketNodeKind, classify_node, encrypt_count, server_ping_reply
from baileys.noise import NOISE_MODE, NOISE_WA_HEADER, NoiseHandshake, generate_noise_key_pair
from baileys.retry import (
    extract_retry_session_bundle,
    inject_retry_session_from_receipt,
    retry_count_from_receipt,
    retry_receipt_node,
)
from baileys.routing import base64url_no_padding, websocket_url_with_routing
from baileys.signal_crypto import shared_key, sign, signal_public_from_private, verify
from baileys.signal_session_probe import run_signal_session_round_trip
from baileys.usync import (
    conversation_identities,
    extract_device_jids,
    parse_usync_bot_profiles,
    parse_usync_contacts,
    parse_usync_disappearing_modes,
    parse_usync_result,
    parse_usync_side_list,
    parse_usync_statuses,
    parse_usync_usernames,
    split_own_and_other_devices,
    usync_devices_query_node,
    usync_query_node,
)
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node
from baileys.whatsapp_keys import derive_media_keys, expand_app_state_keys
from signal_protocol import address, curve, group_cipher, identity_key, protocol, sender_keys, session, session_cipher, state, storage


def _signal_key_pair() -> curve.KeyPair:
    public_key, private_key = curve.generate_keypair()
    return curve.KeyPair.from_public_and_private(public_key, private_key)


def _conversation_payload(text: str) -> bytes:
    message = proto.Message()
    message.conversation = text
    return pad_random_max_16(message.SerializeToString())


def _encrypted_node(stanza_id: str, enc_type: str, ciphertext: bytes) -> dict:
    return {
        "tag": "message",
        "attrs": {"id": stanza_id, "from": "alice:1@s.whatsapp.net"},
        "content": [{"tag": "enc", "attrs": {"type": enc_type}, "content": {"base64": b64(ciphertext)}}],
    }


def test_binary_node_round_trip_with_nested_bytes():
    node = BinaryNode(
        tag="iq",
        attrs={"id": "1", "to": "s.whatsapp.net"},
        content=[BinaryNode(tag="query", attrs={"xmlns": "test"}, content=b"payload")],
    )

    decoded = decode_binary_node(encode_binary_node(node))

    assert decoded.tag == "iq"
    assert decoded.attrs == {"id": "1", "to": "s.whatsapp.net"}
    assert isinstance(decoded.content, list)
    assert decoded.content[0].tag == "query"
    assert decoded.content[0].attrs == {"xmlns": "test"}
    assert decoded.content[0].content == b"payload"


def test_aes_gcm_round_trip():
    plaintext = b"hello"
    key = b"0" * 32
    iv = b"1" * 12
    aad = b"aad"

    ciphertext = aes_encrypt_gcm(plaintext, key, iv, aad)

    assert aes_decrypt_gcm(ciphertext, key, iv, aad) == plaintext


def test_x25519_shared_secret_matches():
    alice = generate_x25519_key_pair()
    bob = generate_x25519_key_pair()

    assert x25519_shared_key(alice.private, bob.public) == x25519_shared_key(bob.private, alice.public)


def test_signal_curve_matches_libsignal_vectors():
    private_a = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
    private_b = bytes.fromhex("202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f")
    public_a = bytes.fromhex("058f40c5adb68f25624ae5b214ea767a6ec94d829d3d7b5e1ad1ba6f3e2138285f")
    public_b = bytes.fromhex("05358072d6365880d1aeea329adf9121383851ed21a28e3b75e965d0d2cd166254")
    shared_ab = bytes.fromhex("9663aa1da97e848a914a436d04163dfbb89178f107f1b5b77ed3854203382854")
    node_signature = bytes.fromhex(
        "9046777f9e290aaaf57f70a49e588e855e0d72b9a27a6e7800c625c1289dcdda36cdc6db4677d895b1b441433385900b62f6ffee56465779df9588fc68e2a004"
    )
    message = b"hello signal"

    assert signal_public_from_private(private_a) == public_a
    assert signal_public_from_private(private_b) == public_b
    assert shared_key(private_a, public_b) == shared_ab
    assert shared_key(private_b, public_a) == shared_ab
    assert verify(public_a, message, node_signature)
    assert verify(public_a, message, sign(private_a, message))


def test_signal_session_prekey_and_reply_round_trip():
    result = run_signal_session_round_trip()

    assert result.alice_to_bob == b"hello bob"
    assert result.bob_to_alice == b"hi alice"
    assert result.prekey_message_type == 3
    assert result.signal_message_type == 2


def test_auth_store_persists_prekey_session_for_rehydration():
    alice_identity = identity_key.IdentityKeyPair.generate()
    bob_identity = identity_key.IdentityKeyPair.generate()
    alice_store = storage.InMemSignalProtocolStore(alice_identity, 1111)

    pre_key_id = 7
    signed_pre_key_id = 8
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
    prekey_ciphertext = session_cipher.message_encrypt(alice_store, bob_addr, b"first")
    prekey_message = protocol.PreKeySignalMessage.try_from(prekey_ciphertext.serialize())
    plaintext = session_cipher.message_decrypt_prekey(bob_store, alice_addr, prekey_message)
    assert plaintext == b"first"
    assert export_session(bob_creds, bob_store, alice_addr)
    assert mark_pre_key_consumed(bob_creds, prekey_message.pre_key_id())

    assert str(pre_key_id) not in bob_creds["pre_keys"]
    assert protocol_address_key(alice_addr) in bob_creds["signal_sessions"]

    rehydrated_bob_store = build_signal_store(bob_creds)
    signal_ciphertext = session_cipher.message_encrypt(rehydrated_bob_store, alice_addr, b"second")
    signal_message = protocol.SignalMessage.try_from(signal_ciphertext.serialize())
    assert session_cipher.message_decrypt_signal(alice_store, bob_addr, signal_message) == b"second"


def test_message_decrypt_handles_pkmsg_then_persisted_msg_node():
    alice_identity = identity_key.IdentityKeyPair.generate()
    bob_identity = identity_key.IdentityKeyPair.generate()
    alice_store = storage.InMemSignalProtocolStore(alice_identity, 1111)

    pre_key_id = 9
    signed_pre_key_id = 10
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

    pk_ciphertext = session_cipher.message_encrypt(alice_store, bob_addr, _conversation_payload("first"))
    pk_result = decrypt_message_node(_encrypted_node("pk1", "pkmsg", pk_ciphertext.serialize()), bob_creds)
    assert pk_result is not None
    assert pk_result.message.conversation == "first"
    assert protocol_address_key(alice_addr) in bob_creds["signal_sessions"]

    bob_store = build_signal_store(bob_creds)
    bob_reply = session_cipher.message_encrypt(bob_store, alice_addr, _conversation_payload("ack"))
    bob_reply_message = protocol.SignalMessage.try_from(bob_reply.serialize())
    session_cipher.message_decrypt_signal(alice_store, bob_addr, bob_reply_message)

    msg_ciphertext = session_cipher.message_encrypt(alice_store, bob_addr, _conversation_payload("second"))
    msg_result = decrypt_message_node(_encrypted_node("msg1", "msg", msg_ciphertext.serialize()), bob_creds)
    assert msg_result is not None
    assert msg_result.enc_type == "msg"
    assert msg_result.message.conversation == "second"


def test_message_send_builds_decryptable_one_to_one_stanza():
    alice_identity = identity_key.IdentityKeyPair.generate()
    bob_identity = identity_key.IdentityKeyPair.generate()
    alice_store = storage.InMemSignalProtocolStore(alice_identity, 1111)

    pre_key_id = 11
    signed_pre_key_id = 12
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

    alice_addr = address.ProtocolAddress("alice", 0)
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
    session_cipher.message_decrypt_prekey(bob_store, alice_addr, protocol.PreKeySignalMessage.try_from(first.serialize()))
    export_session(bob_creds, bob_store, alice_addr)

    outbound = build_text_message_node(
        bob_creds,
        "alice@s.whatsapp.net",
        "python send",
        direct_enc=False,
        include_phash=True,
    )
    assert outbound.node.tag == "message"
    assert outbound.node.attrs["to"] == "alice@s.whatsapp.net"
    assert outbound.node.attrs["type"] == "text"
    assert outbound.node.attrs["phash"].startswith("2:")
    assert outbound.participant_jids == ["alice@s.whatsapp.net"]
    participants = outbound.node.content[0]
    assert len(participants.content) == 1
    enc = participants.content[0].content[0]
    assert enc.attrs["type"] == "msg"

    signal_message = protocol.SignalMessage.try_from(enc.content)
    plaintext = session_cipher.message_decrypt_signal(alice_store, bob_addr, signal_message)
    assert parse_plaintext_message(plaintext).conversation == "python send"


def test_usync_device_query_and_parser_match_baileys_shape():
    creds = {"me": {"id": "123:4@s.whatsapp.net", "lid": "999:4@lid"}}
    identities = conversation_identities(creds, "555@lid")
    assert identities == ["999@lid", "555@lid"]

    query = usync_devices_query_node(identities, "tag-1")
    assert query.attrs == {"id": "tag-1", "to": "s.whatsapp.net", "type": "get", "xmlns": "usync"}
    usync = query.content[0]
    assert usync.attrs == {"context": "message", "mode": "query", "sid": "tag-1", "last": "true", "index": "0"}
    assert usync.content[0].content[0].tag == "devices"
    assert usync.content[0].content[0].attrs == {"version": "2"}
    assert usync.content[0].content[1].tag == "lid"
    assert [user.attrs["jid"] for user in usync.content[1].content] == identities

    result = BinaryNode(
        "iq",
        {"id": "tag-1", "type": "result"},
        [
            BinaryNode(
                "usync",
                {},
                [
                    BinaryNode(
                        "list",
                        {},
                        [
                            BinaryNode(
                                "user",
                                {"jid": "999@lid"},
                                [
                                    BinaryNode(
                                        "devices",
                                        {},
                                        [
                                            BinaryNode(
                                                "device-list",
                                                {},
                                                [
                                                    BinaryNode("device", {"id": "0"}),
                                                    BinaryNode("device", {"id": "4", "key-index": "7"}),
                                                ],
                                            )
                                        ],
                                    )
                                ],
                            ),
                            BinaryNode(
                                "user",
                                {"jid": "555@lid"},
                                [
                                    BinaryNode("lid", {"val": "555@lid"}),
                                    BinaryNode(
                                        "devices",
                                        {},
                                        [
                                            BinaryNode(
                                                "device-list",
                                                {},
                                                [BinaryNode("device", {"id": "0"})],
                                            )
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    )
                ],
            )
        ],
    )

    parsed = parse_usync_result(result)
    devices = extract_device_jids(parsed, "123:4@s.whatsapp.net", "999:4@lid")
    assert [device.jid for device in devices] == ["999@lid", "555@lid"]
    assert split_own_and_other_devices(creds, devices) == (["999@lid"], ["555@lid"])


def test_usync_device_parser_accepts_alt_device_layout_and_id_key():
    result = BinaryNode(
        "iq",
        {"id": "tag-2", "type": "result"},
        [
            BinaryNode(
                "usync",
                {},
                [
                    BinaryNode(
                        "list",
                        {},
                        [
                            BinaryNode(
                                "user",
                                {"id": "123@lid"},
                                [BinaryNode("devices", {}, [BinaryNode("device", {"id": "0"})])],
                            ),
                            BinaryNode(
                                "user",
                                {"id": "321@lid"},
                                [
                                    BinaryNode(
                                        "devices",
                                        {},
                                        [BinaryNode("device-list", {}, [BinaryNode("device", {"id": "0"})])],
                                    )
                                ],
                            ),
                        ],
                    )
                ],
            )
        ],
    )
    parsed = parse_usync_result(result)
    assert [item["id"] for item in parsed] == ["123@lid", "321@lid"]
    assert all("devices" in item for item in parsed)


def test_usync_generic_parser_preserves_common_protocol_values():
    parsed = parse_usync_result(
        BinaryNode(
            "iq",
            {"id": "tag-3", "type": "result"},
            [
                BinaryNode(
                    "usync",
                    {},
                    [
                        BinaryNode(
                            "list",
                            {},
                            [
                                BinaryNode(
                                    "user",
                                    {"jid": "123@s.whatsapp.net"},
                                    [
                                        BinaryNode("contact", {"type": "in"}),
                                        BinaryNode("status", {"t": "101"}, b"available"),
                                        BinaryNode("disappearing_mode", {"duration": "86400", "t": "102"}),
                                        BinaryNode("username", {}, b"alice"),
                                        BinaryNode("business", {"verified": "true"}, b"payload"),
                                    ],
                                ),
                                BinaryNode(
                                    "user",
                                    {"jid": "456@s.whatsapp.net"},
                                    [BinaryNode("contact", {"value": "0"}), BinaryNode("status", {"code": "401"})],
                                ),
                            ],
                        )
                    ],
                )
            ],
        )
    )

    assert parsed[0]["contact"] is True
    assert parsed[0]["status"]["status"] == "available"
    assert parsed[0]["status"]["set_at"] == 101
    assert parsed[0]["disappearing_mode"]["duration"] == 86400
    assert parsed[0]["disappearing_mode"]["set_at"] == 102
    assert parsed[0]["username"] == "alice"
    assert parsed[0]["business"]["attrs"] == {"verified": "true"}
    assert parsed[0]["business"]["content"] == b"payload"
    assert parsed[1]["contact"] is False
    assert parsed[1]["status"]["status"] == ""


def test_usync_typed_protocol_parsers_cover_common_node_protocols():
    result = BinaryNode(
        "iq",
        {"id": "tag-typed", "type": "result"},
        [
            BinaryNode(
                "usync",
                {},
                [
                    BinaryNode(
                        "list",
                        {},
                        [
                            BinaryNode(
                                "user",
                                {"jid": "123@s.whatsapp.net"},
                                [
                                    BinaryNode("contact", {"type": "in"}),
                                    BinaryNode("status", {"t": "101"}, b"available"),
                                    BinaryNode("disappearing_mode", {"duration": "86400", "t": "102"}),
                                    BinaryNode("username", {}, b"alice"),
                                    BinaryNode(
                                        "bot",
                                        {},
                                        [
                                            BinaryNode(
                                                "profile",
                                                {"persona_id": "persona-1"},
                                                [
                                                    BinaryNode("name", {}, b"Helper"),
                                                    BinaryNode("attributes", {}, b"useful"),
                                                    BinaryNode("description", {}, b"answers questions"),
                                                    BinaryNode("category", {}, b"utility"),
                                                    BinaryNode("default", {}),
                                                    BinaryNode(
                                                        "prompts",
                                                        {},
                                                        [
                                                            BinaryNode(
                                                                "prompt",
                                                                {},
                                                                [BinaryNode("emoji", {}, b"?"), BinaryNode("text", {}, b"Ask")],
                                                            )
                                                        ],
                                                    ),
                                                    BinaryNode(
                                                        "commands",
                                                        {},
                                                        [
                                                            BinaryNode("description", {}, b"available commands"),
                                                            BinaryNode(
                                                                "command",
                                                                {},
                                                                [
                                                                    BinaryNode("name", {}, b"help"),
                                                                    BinaryNode("description", {}, b"show help"),
                                                                ],
                                                            ),
                                                        ],
                                                    ),
                                                ],
                                            )
                                        ],
                                    ),
                                ],
                            ),
                            BinaryNode(
                                "user",
                                {"jid": "456@s.whatsapp.net"},
                                [BinaryNode("contact", {"value": "0"}), BinaryNode("status", {"code": "401"})],
                            ),
                        ],
                    ),
                    BinaryNode(
                        "side_list",
                        {},
                        [
                            BinaryNode(
                                "user",
                                {"jid": "789@s.whatsapp.net"},
                                [BinaryNode("username", {}, b"side")],
                            )
                        ],
                    ),
                ],
            )
        ],
    )

    assert parse_usync_contacts(result)[0].exists is True
    assert parse_usync_contacts(result)[1].exists is False
    assert parse_usync_statuses(result)[0].status == "available"
    assert parse_usync_statuses(result)[1].status == ""
    assert parse_usync_disappearing_modes(result)[0].duration == 86400
    assert parse_usync_usernames(result)[0].username == "alice"
    profile = parse_usync_bot_profiles(result)[0]
    assert profile.jid == "123@s.whatsapp.net"
    assert profile.name == "Helper"
    assert profile.attributes == "useful"
    assert profile.description == "answers questions"
    assert profile.category == "utility"
    assert profile.is_default is True
    assert profile.prompts == ("? Ask",)
    assert profile.persona_id == "persona-1"
    assert profile.commands_description == "available commands"
    assert profile.commands[0].name == "help"
    assert profile.commands[0].description == "show help"
    assert parse_usync_side_list(result)[0]["username"] == "side"


def test_usync_generic_query_builder_accepts_named_protocols():
    query = usync_query_node(
        ["123@s.whatsapp.net"],
        ["devices", "contact", "status", "disappearing_mode", "username", "bot"],
        "tag-generic",
    )
    usync = query.content[0]
    protocol_nodes = usync.content[0].content
    assert [node.tag for node in protocol_nodes] == ["devices", "contact", "status", "disappearing_mode", "username", "bot"]
    assert protocol_nodes[0].attrs == {"version": "2"}
    assert protocol_nodes[-1].content[0].tag == "profile"
    assert [user.attrs["jid"] for user in usync.content[1].content] == ["123@s.whatsapp.net"]


def test_usync_parser_skips_malformed_user_id():
    parsed = parse_usync_result(
        BinaryNode(
            "iq",
            {"type": "result"},
            [
                BinaryNode(
                    "usync",
                    {},
                    [
                        BinaryNode(
                            "list",
                            {},
                            [
                                BinaryNode("user", {"jid": "919272419368:s.whatsapp.net"}, [BinaryNode("devices", {}, [])]),
                                BinaryNode("user", {"jid": "321@lid"}, [BinaryNode("devices", {}, [BinaryNode("device", {"id": "0"})])]),
                            ],
                        )
                    ],
                )
            ],
        )
    )
    extracted = extract_device_jids(parsed, "111@lid", "999@lid")
    assert [device.jid for device in extracted] == ["321@lid"]
    assert len(parsed) == 2


def test_encrypt_session_query_and_injection_builds_signal_session():
    alice_identity = identity_key.IdentityKeyPair.generate()
    bob_identity = identity_key.IdentityKeyPair.generate()
    bob_pre_key_id = 31
    bob_signed_pre_key_id = 32
    bob_pre_key_pair = _signal_key_pair()
    bob_signed_pre_key_pair = _signal_key_pair()
    bob_signed_pre_key_signature = bob_identity.private_key().calculate_signature(
        bob_signed_pre_key_pair.public_key().serialize()
    )
    charlie_identity = identity_key.IdentityKeyPair.generate()
    charlie_signed_pre_key_pair = _signal_key_pair()
    charlie_signed_pre_key_id = 42
    charlie_signed_pre_key_signature = charlie_identity.private_key().calculate_signature(
        charlie_signed_pre_key_pair.public_key().serialize()
    )
    alice_creds = creds_from_generated_signal_material(
        identity_pair=alice_identity,
        registration_id=1111,
        signed_pre_key_id=1,
        signed_pre_key_pair=_signal_key_pair(),
        signed_pre_key_signature=alice_identity.private_key().calculate_signature(_signal_key_pair().public_key().serialize()),
    )
    bob_creds = creds_from_generated_signal_material(
        identity_pair=bob_identity,
        registration_id=2222,
        pre_keys={bob_pre_key_id: bob_pre_key_pair},
        signed_pre_key_id=bob_signed_pre_key_id,
        signed_pre_key_pair=bob_signed_pre_key_pair,
        signed_pre_key_signature=bob_signed_pre_key_signature,
    )
    bob_creds["me"] = {"id": "bob:1@lid"}

    query = encrypt_session_query_node(["bob:1@lid"], "enc-1", force=True)
    assert query.attrs == {"id": "enc-1", "xmlns": "encrypt", "type": "get", "to": "s.whatsapp.net"}
    assert query.content[0].content[0].attrs == {"jid": "bob:1@lid", "reason": "identity"}

    malformed_query = encrypt_session_query_node(["919272419368:s.whatsapp.net"], "enc-2")
    assert malformed_query.content[0].content[0].attrs == {"jid": "919272419368@s.whatsapp.net"}

    result = BinaryNode(
        "iq",
        {"id": "enc-1", "type": "result"},
        [
            BinaryNode(
                "list",
                {},
                [
                    BinaryNode(
                        "user",
                        {"jid": "bob:1@lid"},
                        [
                            BinaryNode("registration", {}, encode_big_endian(2222, 4)),
                            BinaryNode("identity", {}, bob_identity.identity_key().serialize()[1:]),
                            BinaryNode(
                                "skey",
                                {},
                                [
                                    BinaryNode("id", {}, encode_big_endian(bob_signed_pre_key_id, 3)),
                                    BinaryNode("value", {}, bob_signed_pre_key_pair.public_key().serialize()[1:]),
                                    BinaryNode("signature", {}, bob_signed_pre_key_signature),
                                ],
                            ),
                            BinaryNode(
                                "key",
                                {},
                                [
                                    BinaryNode("id", {}, encode_big_endian(bob_pre_key_id, 3)),
                                    BinaryNode("value", {}, bob_pre_key_pair.public_key().serialize()[1:]),
                                ],
                            ),
                        ],
                    ),
                    BinaryNode(
                        "user",
                        {"jid": "charlie:2@lid"},
                        [
                            BinaryNode("registration", {}, encode_big_endian(3333, 4)),
                            BinaryNode("identity", {}, charlie_identity.identity_key().serialize()[1:]),
                            BinaryNode(
                                "skey",
                                {},
                                [
                                    BinaryNode("id", {}, encode_big_endian(charlie_signed_pre_key_id, 3)),
                                    BinaryNode("value", {}, charlie_signed_pre_key_pair.public_key().serialize()[1:]),
                                    BinaryNode("signature", {}, charlie_signed_pre_key_signature),
                                ],
                            ),
                        ],
                    ),
                ],
            )
        ],
    )

    injected = inject_sessions_from_encrypt_result(alice_creds, result)
    assert [item.address_key for item in injected] == ["bob:1", "charlie:2"]
    assert [item.pre_key_id for item in injected] == [bob_pre_key_id, None]
    assert "bob:1" in alice_creds["signal_sessions"]
    assert "charlie:2" in alice_creds["signal_sessions"]

    alice_store = build_signal_store(alice_creds)
    bob_store = build_signal_store(bob_creds)
    ciphertext = session_cipher.message_encrypt(alice_store, address.ProtocolAddress("bob", 1), b"session works")
    plaintext = session_cipher.message_decrypt_prekey(
        bob_store,
        address.ProtocolAddress("alice", 1),
        protocol.PreKeySignalMessage.try_from(ciphertext.serialize()),
    )
    assert plaintext == b"session works"


def test_encrypt_session_query_partial_errors():
    alice_identity = identity_key.IdentityKeyPair.generate()
    bob_identity = identity_key.IdentityKeyPair.generate()
    bob_pre_key_id = 31
    bob_signed_pre_key_id = 32
    bob_pre_key_pair = _signal_key_pair()
    bob_signed_pre_key_pair = _signal_key_pair()
    bob_signed_pre_key_signature = bob_identity.private_key().calculate_signature(
        bob_signed_pre_key_pair.public_key().serialize()
    )
    alice_creds = creds_from_generated_signal_material(
        identity_pair=alice_identity,
        registration_id=1111,
        signed_pre_key_id=1,
        signed_pre_key_pair=_signal_key_pair(),
        signed_pre_key_signature=alice_identity.private_key().calculate_signature(_signal_key_pair().public_key().serialize()),
    )

    result = BinaryNode(
        "iq",
        {"id": "enc-1", "type": "result"},
        [
            BinaryNode(
                "list",
                {},
                [
                    BinaryNode(
                        "user",
                        {"jid": "bob:1@lid", "error": "missing"},
                    ),
                    BinaryNode(
                        "user",
                        {"jid": "charlie:2@lid"},
                        [
                            BinaryNode("registration", {}, encode_big_endian(2222, 4)),
                            BinaryNode("identity", {}, bob_identity.identity_key().serialize()[1:]),
                            BinaryNode(
                                "skey",
                                {},
                                [
                                    BinaryNode("id", {}, encode_big_endian(bob_signed_pre_key_id, 3)),
                                    BinaryNode("value", {}, bob_signed_pre_key_pair.public_key().serialize()[1:]),
                                    BinaryNode("signature", {}, bob_signed_pre_key_signature),
                                ],
                            ),
                            BinaryNode(
                                "key",
                                {},
                                [
                                    BinaryNode("id", {}, encode_big_endian(bob_pre_key_id, 3)),
                                    BinaryNode("value", {}, bob_signed_pre_key_pair.public_key().serialize()[1:]),
                                ],
                            ),
                        ],
                    ),
                ],
            )
        ],
    )

    with pytest.raises(ValueError):
        inject_sessions_from_encrypt_result(alice_creds, result)

    injected = inject_sessions_from_encrypt_result(alice_creds, result, allow_partial=True)
    assert [item.jid for item in injected] == ["charlie:2@lid"]
    assert "charlie:2" in alice_creds["signal_sessions"]
    assert "bob:1" not in alice_creds["signal_sessions"]



def test_prekey_upload_digest_and_rotation_nodes():
    identity = identity_key.IdentityKeyPair.generate()
    signed_pair = _signal_key_pair()
    signed_signature = identity.private_key().calculate_signature(signed_pair.public_key().serialize())
    creds = creds_from_generated_signal_material(
        identity_pair=identity,
        registration_id=3333,
        signed_pre_key_id=1,
        signed_pre_key_pair=signed_pair,
        signed_pre_key_signature=signed_signature,
    )
    creds["next_pre_key_id"] = 1
    creds["first_unuploaded_pre_key_id"] = 1

    digest = digest_key_bundle_node("digest-1")
    assert digest.tag == "iq"
    assert digest.attrs == {"to": "s.whatsapp.net", "type": "get", "xmlns": "encrypt", "id": "digest-1"}
    assert isinstance(digest.content, list)
    assert digest.content[0].tag == "digest"

    upload = build_prekey_upload_node(creds, count=2, tag_id="upload-1")
    assert upload.uploaded_ids == [1, 2]
    assert creds["next_pre_key_id"] == 3
    assert creds["first_unuploaded_pre_key_id"] == 3
    assert set(creds["pre_keys"]) == {"1", "2"}
    assert upload.node.attrs == {"xmlns": "encrypt", "type": "set", "to": "s.whatsapp.net", "id": "upload-1"}
    assert isinstance(upload.node.content, list)
    assert [child.tag for child in upload.node.content] == ["registration", "type", "identity", "list", "skey"]
    key_list = upload.node.content[3]
    assert isinstance(key_list.content, list)
    assert [int.from_bytes(key.content[0].content, "big") for key in key_list.content] == [1, 2]

    rotation = rotate_signed_pre_key_node(creds, "rotate-1")
    assert rotation.key_id == 2
    assert creds["signed_pre_key_id"] == 2
    assert rotation.node.attrs == {"to": "s.whatsapp.net", "type": "set", "xmlns": "encrypt", "id": "rotate-1"}
    assert isinstance(rotation.node.content, list)
    assert rotation.node.content[0].tag == "rotate"


def test_socket_node_classifier_covers_post_login_handlers():
    ping = BinaryNode("iq", {"type": "get", "xmlns": "urn:xmpp:ping", "id": "p1", "t": "123"})
    assert classify_node(ping) == SocketNodeKind.SERVER_PING
    assert server_ping_reply(ping).attrs == {"to": "s.whatsapp.net", "type": "result", "id": "p1", "t": "123"}

    count = BinaryNode("notification", {"type": "encrypt"}, [BinaryNode("count", {"value": "4"})])
    assert classify_node(count) == SocketNodeKind.ENCRYPT_COUNT
    assert encrypt_count(count) == 4

    vectors = [
        (BinaryNode("success", {}), SocketNodeKind.LOGIN_SUCCESS),
        (BinaryNode("message", {}), SocketNodeKind.MESSAGE),
        (BinaryNode("receipt", {}), SocketNodeKind.RECEIPT),
        (BinaryNode("ack", {"id": "1"}), SocketNodeKind.ACK),
        (BinaryNode("ack", {"id": "1", "error": "479"}), SocketNodeKind.IQ_ERROR),
        (BinaryNode("notification", {"type": "server"}), SocketNodeKind.NOTIFICATION),
        (BinaryNode("iq", {"type": "result"}), SocketNodeKind.IQ_RESULT),
        (BinaryNode("iq", {"type": "error"}), SocketNodeKind.IQ_ERROR),
        (BinaryNode("failure", {}), SocketNodeKind.FAILURE),
        (BinaryNode("stream:error", {}), SocketNodeKind.STREAM_ERROR),
        (BinaryNode("ib", {}, [BinaryNode("edge_routing", {})]), SocketNodeKind.EDGE_ROUTING),
        (BinaryNode("ib", {}, [BinaryNode("offline_preview", {})]), SocketNodeKind.OFFLINE_PREVIEW),
        (BinaryNode("ib", {}, [BinaryNode("offline", {})]), SocketNodeKind.OFFLINE),
        (BinaryNode("ib", {}, [BinaryNode("dirty", {})]), SocketNodeKind.DIRTY),
        (BinaryNode("presence", {}), SocketNodeKind.UNKNOWN),
    ]
    for node, expected in vectors:
        assert classify_node(node) == expected


def test_whatsapp_bridge_hkdf_md5_vectors():
    assert md5(b"hello").hex() == "5d41402abc4b2a76b9719d911017c592"
    assert (
        hkdf(
            bytes.fromhex("000102030405060708090a0b0c0d0e0f"),
            112,
            salt=bytes.fromhex("101112131415161718191a1b1c1d1e1f"),
            info=b"WhatsApp Image Keys",
        ).hex()
        == "4ca6263a611f6ae08fc73300a9fafe79178eef0719c61ddbdc5ec2b2bec893dce099faf6ee0494ec253484ad864d69d9662512634e19dbfc51fe87c185ac78ccd3a28b9299fbe10ef7c4f60dbe201b592ca76a4f773da7d8ae7ad7a19c9b9a7f44600ed42f9516d60ce4ce18f22f5cc5"
    )


def test_app_state_and_media_key_vectors():
    app_keys = expand_app_state_keys(bytes([7]) * 32)
    assert app_keys.index_key.hex() == "a3c20564c4744dc336223b76a374ac369fb1bc2062969b26bd0104cba5149e7a"
    assert app_keys.value_encryption_key.hex() == "28f9ac3865f5c0d77441c361c8eb0c40435487e1fca973df3828cbe320faa07f"
    assert app_keys.value_mac_key.hex() == "e2b9c9aaebb04ac52b5c04c449a8af48945e63af3e4b8e2b3f8266753675bc3e"
    assert app_keys.snapshot_mac_key.hex() == "c49519c1aa1718c8f1c1f14c546fb2dedfcc58cace2b5fba9de15f9c084bd04b"
    assert app_keys.patch_mac_key.hex() == "3b9efe15c717b5da8b85c45200bb6ce8af59c72d62f4c203909c53749b54cd04"

    media_keys = derive_media_keys(bytes([9]) * 32, "image")
    assert media_keys.iv.hex() == "3d5fe066de4dc55e3f832891ae03661f"
    assert media_keys.cipher_key.hex() == "5e6aefd482e67e3973dc969c24899445a5802c07fc08b3053e12a623b17b1fab"
    assert media_keys.mac_key.hex() == "21dc5fe9ef057e69ba7ca2da62fffc3cc3fdc086f6971c514e0a2fc4fd5ec897"


def test_media_encrypt_decrypt_and_media_conn_parser():
    media_key = bytes(range(32))
    encrypted = encrypt_media(b"image-bytes", "image", media_key=media_key)

    assert encrypted.file_length == len(b"image-bytes")
    assert encrypted.file_sha256 == sha256(b"image-bytes")
    assert decrypt_media(encrypted.encrypted, media_key, "image") == b"image-bytes"
    assert upload_token(b"\xfb\xff") == "-_8"

    query = media_conn_node("media-1")
    assert query.attrs == {"id": "media-1", "type": "set", "xmlns": "w:m", "to": "s.whatsapp.net"}
    response = BinaryNode(
        "iq",
        {"id": "media-1", "type": "result"},
        [
            BinaryNode(
                "media_conn",
                {"auth": "auth-token", "ttl": "3600"},
                [BinaryNode("host", {"hostname": "mmg.whatsapp.net", "maxContentLengthBytes": "1048576"})],
            )
        ],
    )
    parsed = parse_media_conn(response)
    assert parsed.auth == "auth-token"
    assert parsed.ttl == 3600
    assert parsed.hosts[0].hostname == "mmg.whatsapp.net"


def test_pairing_key_and_binary_frame_decompression():
    assert (
        derive_pairing_code_key(
            "ABCD-1234",
            bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"),
        ).hex()
        == "4be88795e912d406dc59ad09c78ec27e65ed7d4230d78c5719ec5c0eff5faa70"
    )

    import zlib

    payload = b"<iq id='1'/>"
    assert decompress_if_required(b"\x00" + payload) == payload
    assert decompress_if_required(b"\x02" + zlib.compress(payload)) == payload

    compressed_frame = bytes.fromhex("02789cfbc12ac911caa2090008ba01a1")
    compressed_decoded = decode_binary_node(decompress_if_required(compressed_frame), has_stream_prefix=False)
    assert compressed_decoded.tag == "iq"
    assert compressed_decoded.attrs == {"id": "1", "type": "get"}


def test_pairing_code_hello_and_finish_payloads_match_baileys_shape():
    pairing_code = "ABCDEFGH"
    companion_ephemeral = generate_noise_key_pair()
    primary_ephemeral = generate_noise_key_pair()
    companion_identity = generate_noise_key_pair()
    primary_identity = generate_noise_key_pair()

    assert bytes_to_crockford(bytes.fromhex("0001020304")) == "111H51R5"
    assert normalize_phone_number("+1 (234) 567-8900:4@s.whatsapp.net") == "12345678900"
    assert phone_jid("+1 (234) 567-8900") == "12345678900@s.whatsapp.net"

    wrapped_companion = generate_pairing_key(
        pairing_code,
        companion_ephemeral.public,
        salt=bytes(range(32)),
        iv=bytes(range(32, 48)),
    )
    assert len(wrapped_companion) == 80
    assert decrypt_link_public_key(pairing_code, wrapped_companion) == companion_ephemeral.public

    hello = pairing_code_hello_node(
        phone_number="12345678900",
        tag_id="pair-hello-1",
        pairing_code=pairing_code,
        companion_ephemeral_public=companion_ephemeral.public,
        noise_public=bytes([7]) * 32,
    )
    assert hello.attrs == {"to": "s.whatsapp.net", "type": "set", "id": "pair-hello-1", "xmlns": "md"}
    hello_reg = hello.content[0]
    assert hello_reg.attrs == {
        "jid": "12345678900@s.whatsapp.net",
        "stage": "companion_hello",
        "should_show_push_notification": "true",
    }
    assert [child.tag for child in hello_reg.content] == [
        "link_code_pairing_wrapped_companion_ephemeral_pub",
        "companion_server_auth_key_pub",
        "companion_platform_id",
        "companion_platform_display",
        "link_code_pairing_nonce",
    ]

    wrapped_primary = generate_pairing_key(
        pairing_code,
        primary_ephemeral.public,
        salt=bytes(range(64, 96)),
        iv=bytes(range(96, 112)),
    )
    finish = pairing_code_finish_node(
        phone_number="12345678900",
        tag_id="pair-finish-1",
        pairing_code=pairing_code,
        pairing_ephemeral=companion_ephemeral,
        identity=companion_identity,
        ref=b"ref-1",
        primary_identity_public=primary_identity.public,
        wrapped_primary_ephemeral_public=wrapped_primary,
        link_code_salt=bytes(range(112, 144)),
        encrypt_iv=bytes(range(144, 156)),
        random=bytes(range(156, 188)),
    )

    finish_reg = finish.node.content[0]
    assert finish_reg.attrs == {"jid": "12345678900@s.whatsapp.net", "stage": "companion_finish"}
    assert [child.tag for child in finish_reg.content] == [
        "link_code_pairing_wrapped_key_bundle",
        "companion_identity_public",
        "link_code_pairing_ref",
    ]
    wrapped_key_bundle = finish_reg.content[0].content
    expanded = hkdf(
        finish.companion_shared_key,
        32,
        salt=wrapped_key_bundle[:32],
        info=LINK_CODE_KEY_BUNDLE_INFO,
    )
    decrypted = aes_decrypt_gcm(wrapped_key_bundle[44:], expanded, wrapped_key_bundle[32:44], b"")
    assert decrypted == companion_identity.public + primary_identity.public + bytes(range(156, 188))
    assert base64.b64decode(finish.adv_secret_key) == hkdf(
        finish.companion_shared_key + finish.identity_shared_key + bytes(range(156, 188)),
        32,
        info=b"adv_secret",
    )


def test_tokenized_binary_node_matches_bridge_vector():
    bridge_tokenized = bytes.fromhex("00f80819085511030429f801f8046d16fc0474657374fc077061796c6f6164")
    node = BinaryNode(
        "iq",
        {"id": "1", "to": "s.whatsapp.net", "type": "get"},
        [BinaryNode("query", {"xmlns": "test"}, b"payload")],
    )

    assert encode_binary_node(node) == bridge_tokenized
    decoded = decode_binary_node(bridge_tokenized)
    assert decoded.tag == "iq"
    assert decoded.attrs == {"id": "1", "to": "s.whatsapp.net", "type": "get"}
    assert isinstance(decoded.content, list)
    assert decoded.content[0].tag == "query"
    assert decoded.content[0].attrs == {"xmlns": "test"}
    assert decoded.content[0].content == b"payload"


def test_packed_and_jid_edge_vectors_match_bridge():
    vectors = [
        (BinaryNode("edge", {"code": "12345-67.89"}), "00f803fc046564676570ff8612345a67b89f"),
        (BinaryNode("edge", {"hexv": "A1B2C3F"}), "00f803fc0465646765fc0468657876fb84a1b2c3ff"),
        (
            BinaryNode(
                "edge",
                {
                    "jid": "12345:7@s.whatsapp.net",
                    "lid": "999:3@lid",
                    "hosted": "555:99@hosted",
                },
            ),
            "00f807fc04656467650cf70007ff8312345f76f70103ff82999ffc06686f73746564f78063ff82555f",
        ),
    ]

    for node, expected_hex in vectors:
        encoded = encode_binary_node(node)
        assert encoded.hex() == expected_hex
        assert decode_binary_node(encoded).attrs == node.attrs


def test_fb_and_interop_jid_decode_vectors():
    fb_decoded = decode_binary_node(
        bytes.fromhex("00f803fc0465646765fc026662f6fc0531323334350007fc0866616365626f6f6b")
    )
    assert fb_decoded.attrs == {"fb": "12345:7@facebook"}

    interop_decoded = decode_binary_node(
        bytes.fromhex("00f803fc0465646765fc07696e7465726f70f5fc036162630009002afc07696e7465726f70")
    )
    assert interop_decoded.attrs == {"interop": "42-abc:9@interop"}


def test_signal_group_sender_key_round_trip():
    result = run_group_sender_round_trip()

    assert result.plaintext == b"hello group"
    assert result.distribution_message_length > 0
    assert result.ciphertext_length > 0


def test_message_decrypt_persists_sender_key_and_decrypts_skmsg():
    sender_store = storage.InMemSignalProtocolStore(identity_key.IdentityKeyPair.generate(), 1111)
    receiver_identity = identity_key.IdentityKeyPair.generate()
    receiver_signed_pair = _signal_key_pair()
    receiver_creds = creds_from_generated_signal_material(
        identity_pair=receiver_identity,
        registration_id=2222,
        signed_pre_key_id=1,
        signed_pre_key_pair=receiver_signed_pair,
        signed_pre_key_signature=receiver_identity.private_key().calculate_signature(
            receiver_signed_pair.public_key().serialize()
        ),
    )
    group_jid = "12345@g.us"
    author_jid = "alice:1@s.whatsapp.net"
    sender_name = sender_keys.SenderKeyName(group_jid, address.ProtocolAddress("alice", 1))

    distribution = group_cipher.create_sender_key_distribution_message(sender_name, sender_store)
    distribution_message = proto.Message()
    distribution_message.senderKeyDistributionMessage.groupId = group_jid
    distribution_message.senderKeyDistributionMessage.axolotlSenderKeyDistributionMessage = distribution.serialize()

    assert process_sender_key_distribution_message(receiver_creds, distribution_message, author_jid)
    assert f"{group_jid}|alice:1" in receiver_creds["sender_keys"]

    ciphertext = group_cipher.group_encrypt(sender_store, sender_name, _conversation_payload("hello live group"))
    node = {
        "tag": "message",
        "attrs": {"id": "g1", "from": group_jid, "participant": author_jid},
        "content": [{"tag": "enc", "attrs": {"type": "skmsg"}, "content": {"base64": b64(ciphertext)}}],
    }

    result = decrypt_message_node(node, receiver_creds)

    assert result is not None
    assert result.enc_type == "skmsg"
    assert result.sender_key_name is not None
    assert result.sender_key_name.group_id() == group_jid
    assert result.message.conversation == "hello live group"


def test_noise_initial_hash_uses_raw_32_byte_protocol_name():
    noise = NoiseHandshake(generate_noise_key_pair())

    assert len(NOISE_MODE) == 32
    assert noise.hash != sha256(NOISE_MODE)


def test_noise_routing_intro_and_websocket_ed_parameter_match_baileys_shape():
    routing_info = b"edge-routing"
    noise = NoiseHandshake(generate_noise_key_pair(), routing_info=routing_info)

    frame = noise.client_hello_frame()

    assert frame.startswith(b"ED\x00\x01")
    assert frame[4:7] == len(routing_info).to_bytes(3, "big")
    assert frame[7 : 7 + len(routing_info)] == routing_info
    assert frame[7 + len(routing_info) : 7 + len(routing_info) + len(NOISE_WA_HEADER)] == NOISE_WA_HEADER
    assert websocket_url_with_routing("wss://web.whatsapp.com/ws/chat", routing_info).endswith(
        "?ED=" + base64url_no_padding(routing_info)
    )
    assert NoiseHandshake(generate_noise_key_pair()).client_hello_frame().startswith(NOISE_WA_HEADER)


def test_retry_receipt_builds_and_injects_session_bundle():
    alice_identity = identity_key.IdentityKeyPair.generate()
    alice_signed_pair = _signal_key_pair()
    alice_creds = creds_from_generated_signal_material(
        identity_pair=alice_identity,
        registration_id=1111,
        signed_pre_key_id=1,
        signed_pre_key_pair=alice_signed_pair,
        signed_pre_key_signature=alice_identity.private_key().calculate_signature(
            alice_signed_pair.public_key().serialize()
        ),
    )

    bob_identity = identity_key.IdentityKeyPair.generate()
    bob_pre_key_id = 51
    bob_signed_pre_key_id = 52
    bob_pre_key_pair = _signal_key_pair()
    bob_signed_pre_key_pair = _signal_key_pair()
    bob_signed_pre_key_signature = bob_identity.private_key().calculate_signature(
        bob_signed_pre_key_pair.public_key().serialize()
    )
    bob_creds = creds_from_generated_signal_material(
        identity_pair=bob_identity,
        registration_id=2222,
        pre_keys={bob_pre_key_id: bob_pre_key_pair},
        signed_pre_key_id=bob_signed_pre_key_id,
        signed_pre_key_pair=bob_signed_pre_key_pair,
        signed_pre_key_signature=bob_signed_pre_key_signature,
    )

    failed_attrs = {"id": "failed-1", "from": "alice@s.whatsapp.net", "t": "123", "participant": "bob:1@s.whatsapp.net"}
    receipt = retry_receipt_node(
        bob_creds,
        failed_attrs,
        receipt_id="retry-1",
        retry_count=2,
        force_include_keys=True,
        pre_key_id=bob_pre_key_id,
    )

    assert receipt.attrs == {
        "id": "retry-1",
        "type": "retry",
        "to": "alice@s.whatsapp.net",
        "participant": "bob:1@s.whatsapp.net",
    }
    assert retry_count_from_receipt(receipt) == 2
    assert [child.tag for child in receipt.content] == ["retry", "registration", "keys"]

    bundle = extract_retry_session_bundle(receipt)
    assert bundle is not None
    assert bundle.registration_id == 2222
    assert bundle.pre_key_id == bob_pre_key_id
    assert bundle.signed_pre_key_id == bob_signed_pre_key_id

    injected = inject_retry_session_from_receipt(alice_creds, receipt, "bob:1@s.whatsapp.net")
    assert injected == bundle
    assert "bob:1" in alice_creds["signal_sessions"]

    alice_store = build_signal_store(alice_creds)
    bob_store = build_signal_store(bob_creds)
    ciphertext = session_cipher.message_encrypt(alice_store, address.ProtocolAddress("bob", 1), b"retry fixed session")
    plaintext = session_cipher.message_decrypt_prekey(
        bob_store,
        address.ProtocolAddress("alice", 1),
        protocol.PreKeySignalMessage.try_from(ciphertext.serialize()),
    )
    assert plaintext == b"retry fixed session"
