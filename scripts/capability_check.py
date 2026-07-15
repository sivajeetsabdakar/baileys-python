from __future__ import annotations

import importlib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.crypto import (  # noqa: E402
    decompress_if_required,
    derive_pairing_code_key,
    aes_decrypt_gcm,
    aes_encrypt_gcm,
    generate_x25519_key_pair,
    hmac_sign,
    sha256,
    x25519_shared_key,
)
from baileys.group_sender_probe import run_group_sender_round_trip  # noqa: E402
from baileys.signal_crypto import (  # noqa: E402
    shared_key as signal_shared_key,
    sign as signal_sign,
    signal_public_from_private,
    verify as signal_verify,
)
from baileys.signal_session_probe import run_signal_session_round_trip  # noqa: E402
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node  # noqa: E402
from baileys.whatsapp_keys import derive_media_keys, expand_app_state_keys  # noqa: E402


def check_proto() -> None:
    module_path = "baileys.generated.WAProto_pb2"
    try:
        wa_proto = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        raise SystemExit("Run scripts/generate_proto.py before capability_check.py") from exc

    message = wa_proto.Message(conversation="hello from python")
    encoded = message.SerializeToString()
    decoded = wa_proto.Message()
    decoded.ParseFromString(encoded)
    assert decoded.conversation == "hello from python"
    print("OK proto generation/import/round-trip")


def check_binary_node() -> None:
    node = BinaryNode(
        tag="message",
        attrs={"id": "abc123", "to": "12345@s.whatsapp.net"},
        content=[BinaryNode(tag="body", content=b"hello")],
    )
    encoded = encode_binary_node(node)
    decoded = decode_binary_node(encoded)
    assert decoded.tag == node.tag
    assert decoded.attrs == node.attrs
    assert isinstance(decoded.content, list)
    assert decoded.content[0].tag == "body"
    assert decoded.content[0].content == b"hello"
    tokenized_node = BinaryNode(
        tag="iq",
        attrs={"id": "1", "to": "s.whatsapp.net", "type": "get"},
        content=[BinaryNode(tag="query", attrs={"xmlns": "test"}, content=b"payload")],
    )
    tokenized = encode_binary_node(tokenized_node)
    assert tokenized.hex() == "00f80819085511030429f801f8046d16fc0474657374fc077061796c6f6164"
    assert decode_binary_node(tokenized).attrs == tokenized_node.attrs

    edge_vectors = [
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
    for edge_node, expected_hex in edge_vectors:
        assert encode_binary_node(edge_node).hex() == expected_hex
        assert decode_binary_node(bytes.fromhex(expected_hex)).attrs == edge_node.attrs

    assert decode_binary_node(
        bytes.fromhex("00f803fc0465646765fc026662f6fc0531323334350007fc0866616365626f6f6b")
    ).attrs == {"fb": "12345:7@facebook"}
    assert decode_binary_node(
        bytes.fromhex("00f803fc0465646765fc07696e7465726f70f5fc036162630009002afc07696e7465726f70")
    ).attrs == {"interop": "42-abc:9@interop"}
    print("OK binary node raw/tokenized/packed/JID edge round-trips")


def check_crypto() -> None:
    key = b"k" * 32
    iv = b"i" * 12
    plaintext = b"baileys-python"
    aad = b"wa"
    ciphertext = aes_encrypt_gcm(plaintext, key, iv, aad)
    assert aes_decrypt_gcm(ciphertext, key, iv, aad) == plaintext
    assert len(sha256(plaintext)) == 32
    assert len(hmac_sign(plaintext, key)) == 32

    alice = generate_x25519_key_pair()
    bob = generate_x25519_key_pair()
    assert x25519_shared_key(alice.private, bob.public) == x25519_shared_key(bob.private, alice.public)
    print("OK crypto primitives")


def check_signal_primitives() -> None:
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
    assert signal_shared_key(private_a, public_b) == shared_ab
    assert signal_shared_key(private_b, public_a) == shared_ab
    assert signal_verify(public_a, message, node_signature)
    assert signal_verify(public_a, message, signal_sign(private_a, message))
    print("OK Signal Curve25519/XEdDSA libsignal-compatible primitives")


def check_signal_session() -> None:
    result = run_signal_session_round_trip()
    assert result.alice_to_bob == b"hello bob"
    assert result.bob_to_alice == b"hi alice"
    assert result.prekey_message_type == 3
    assert result.signal_message_type == 2
    print("OK Signal prekey session + reply round-trip")


def check_whatsapp_key_derivations() -> None:
    app_keys = expand_app_state_keys(bytes([7]) * 32)
    assert app_keys.index_key.hex() == "a3c20564c4744dc336223b76a374ac369fb1bc2062969b26bd0104cba5149e7a"
    assert app_keys.patch_mac_key.hex() == "3b9efe15c717b5da8b85c45200bb6ce8af59c72d62f4c203909c53749b54cd04"

    media_keys = derive_media_keys(bytes([9]) * 32, "image")
    assert media_keys.iv.hex() == "3d5fe066de4dc55e3f832891ae03661f"
    assert media_keys.cipher_key.hex() == "5e6aefd482e67e3973dc969c24899445a5802c07fc08b3053e12a623b17b1fab"

    assert (
        derive_pairing_code_key(
            "ABCD-1234",
            bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"),
        ).hex()
        == "4be88795e912d406dc59ad09c78ec27e65ed7d4230d78c5719ec5c0eff5faa70"
    )

    assert decompress_if_required(b"\x00abc") == b"abc"
    compressed_node = decode_binary_node(
        decompress_if_required(bytes.fromhex("02789cfbc12ac911caa2090008ba01a1")),
        has_stream_prefix=False,
    )
    assert compressed_node.attrs == {"id": "1", "type": "get"}
    print("OK WhatsApp app-state/media/pairing key derivations")


def check_group_sender_keys() -> None:
    result = run_group_sender_round_trip()
    assert result.plaintext == b"hello group"
    print("OK Signal group sender-key round-trip")


def main() -> int:
    check_proto()
    check_binary_node()
    check_crypto()
    check_signal_primitives()
    check_signal_session()
    check_whatsapp_key_derivations()
    check_group_sender_keys()
    print("Capability check passed for offline primitives.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
