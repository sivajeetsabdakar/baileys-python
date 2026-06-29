from __future__ import annotations

from baileys import (
    AuthCredentials,
    areJidsSameUser,
    jidDecode,
    jidEncode,
    jid_decode,
    jid_encode,
    jid_normalized_user,
    phone_number_to_jid,
    transferDevice,
)
from baileys.defaults import KEY_BUNDLE_TYPE, S_WHATSAPP_NET, VERSION
from baileys.jid import (
    DOMAIN_HOSTED,
    DOMAIN_HOSTED_LID,
    DOMAIN_LID,
    is_hosted_lid_user,
    is_hosted_pn_user,
    is_jid_bot,
    is_jid_broadcast,
    is_jid_group,
    is_jid_meta_ai,
    is_jid_status,
    is_lid,
    is_newsletter,
    is_pn,
    server_from_domain_type,
)
from baileys.pairing_code import build_pairing_qr_data, extract_pair_device_refs, pair_device_ack_node
from baileys.registration import build_login_payload, parse_jid_device
from baileys.wabinary import BinaryNode


def test_defaults_are_shared_with_registration_layer():
    assert VERSION == (2, 3000, 1035194821)
    assert KEY_BUNDLE_TYPE == b"\x05"
    assert S_WHATSAPP_NET == "s.whatsapp.net"


def test_jid_decode_encode_common_and_edge_vectors():
    direct = jid_decode("12345@s.whatsapp.net")
    assert (direct.user, direct.server, direct.device, direct.agent, direct.integrator, direct.domain_type) == (
        "12345",
        "s.whatsapp.net",
        0,
        None,
        None,
        0,
    )
    assert jid_encode(direct.user, direct.server, direct.device) == "12345@s.whatsapp.net"

    device = jid_decode("12345:7@s.whatsapp.net")
    assert (device.user, device.server, device.device) == ("12345", "s.whatsapp.net", 7)
    assert jid_encode(device.user, device.server, device.device) == "12345:7@s.whatsapp.net"

    agent = jid_decode("12345_4:7@s.whatsapp.net")
    assert (agent.user, agent.agent, agent.device) == ("12345", 4, 7)
    assert jid_encode(agent.user, agent.server, agent.device, agent=agent.agent) == "12345_4:7@s.whatsapp.net"

    interop = jid_decode("42-abc:9@interop")
    assert (interop.user, interop.server, interop.device) == ("42-abc", "interop", 9)

    integrated = jid_decode("fbid-1@lid.6")
    assert (integrated.user, integrated.server, integrated.integrator) == ("fbid-1", "lid", 6)
    assert jid_encode(integrated.user, integrated.server, integrator=integrated.integrator) == "fbid-1@lid.6"

    hosted = jid_decode("555:99@hosted")
    assert hosted.domain_type == DOMAIN_HOSTED
    assert jid_decode("555:99@hosted.lid").domain_type == DOMAIN_HOSTED_LID
    assert jid_decode("999:3@lid").domain_type == DOMAIN_LID


def test_jid_classification_and_normalization_helpers():
    assert is_pn("12345@s.whatsapp.net")
    assert is_lid("999:3@lid")
    assert is_jid_group("12345-678@g.us")
    assert is_jid_broadcast("status@broadcast")
    assert is_jid_status("status@broadcast")
    assert is_newsletter("abcd@newsletter")
    assert is_hosted_pn_user("555:99@hosted")
    assert is_hosted_lid_user("555:99@hosted.lid")
    assert is_jid_meta_ai("13135550002@bot")
    assert is_jid_bot("13135550002@c.us")
    assert areJidsSameUser("12345:7@s.whatsapp.net", "12345@s.whatsapp.net")
    assert not areJidsSameUser("12345@s.whatsapp.net", "67890@s.whatsapp.net")
    assert jidDecode("12345@s.whatsapp.net") == jid_decode("12345@s.whatsapp.net")
    assert jidEncode("12345", "s.whatsapp.net") == "12345@s.whatsapp.net"
    assert jid_normalized_user("12345:7@c.us") == "12345@s.whatsapp.net"
    assert transferDevice("12345:7@s.whatsapp.net", "999@lid") == "999:7@lid"
    assert server_from_domain_type("s.whatsapp.net", DOMAIN_LID) == "lid"
    assert phone_number_to_jid("+1 (234) 567-8900") == "12345678900@s.whatsapp.net"


def test_login_jid_device_parser_uses_shared_jid_decode():
    assert parse_jid_device("12345:7@s.whatsapp.net") == (12345, 7)
    assert parse_jid_device("12345@s.whatsapp.net") == (12345, None)
    assert build_login_payload("12345:7@s.whatsapp.net")


def test_auth_credentials_round_trip_preserves_known_and_extra_fields(tmp_path):
    raw = {
        "identity_public": "id-pub",
        "identity_private": "id-priv",
        "registration_id": 123,
        "signed_pre_key_id": 4,
        "signed_pre_key_public": "spk-pub",
        "signed_pre_key_private": "spk-priv",
        "signed_pre_key_signature": "spk-sig",
        "noise_public": "noise-pub",
        "noise_private": "noise-priv",
        "adv_secret_key": "adv",
        "signed_pre_key_timestamp": 99,
        "me": {"id": "123:7@s.whatsapp.net", "lid": "999:7@lid", "name": "Test"},
        "pre_keys": {"1": {"public": "pre-pub", "private": "pre-priv"}},
        "signal_sessions": {"alice:0": "session"},
        "sender_keys": {"group|alice:0": "sender"},
        "next_pre_key_id": 2,
        "first_unuploaded_pre_key_id": 1,
        "custom_future_field": {"ok": True},
    }

    creds = AuthCredentials.from_dict(raw)
    assert creds.me is not None
    assert creds.me.id == "123:7@s.whatsapp.net"
    assert creds.pre_keys["1"].public == "pre-pub"
    assert creds.to_dict()["custom_future_field"] == {"ok": True}

    path = tmp_path / "creds.json"
    creds.save_json_file(path)
    loaded = AuthCredentials.from_json_file(path)
    assert loaded.to_dict() == creds.to_dict()


def test_pairing_qr_payload_and_pair_device_ref_helpers():
    payload = build_pairing_qr_data(
        ref="ref-1",
        noise_key=b"n" * 32,
        identity_key=b"i" * 32,
        adv_secret_key="adv-secret",
    )
    assert payload.startswith("https://wa.me/settings/linked_devices#ref-1,")
    assert payload.endswith(",adv-secret,1")

    node = BinaryNode(
        "iq",
        {"id": "pair-1", "type": "set"},
        [BinaryNode("pair-device", {}, [BinaryNode("ref", {}, "ref-1"), BinaryNode("ref", {}, b"ref-2")])],
    )
    refs = extract_pair_device_refs(node)
    assert refs.refs == ["ref-1", "ref-2"]
    assert pair_device_ack_node(node).attrs == {"to": "s.whatsapp.net", "type": "result", "id": "pair-1"}
