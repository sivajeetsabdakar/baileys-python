from __future__ import annotations

import sys
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.crypto import decompress_if_required, derive_pairing_code_key, hkdf, md5  # noqa: E402
from baileys.group_sender_probe import run_group_sender_round_trip  # noqa: E402
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node  # noqa: E402
from baileys.whatsapp_keys import derive_media_keys, expand_app_state_keys  # noqa: E402


BRIDGE_TOKENIZED_NODE_HEX = (
    "00f80819085511030429f801f8046d16fc0474657374fc077061796c6f6164"
)


def main() -> int:
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
    print("OK whatsapp-rust-bridge HKDF/MD5 parity vectors")

    app_keys = expand_app_state_keys(bytes([7]) * 32)
    assert app_keys.index_key.hex() == "a3c20564c4744dc336223b76a374ac369fb1bc2062969b26bd0104cba5149e7a"
    assert app_keys.patch_mac_key.hex() == "3b9efe15c717b5da8b85c45200bb6ce8af59c72d62f4c203909c53749b54cd04"
    print("OK app-state key expansion parity")

    media_keys = derive_media_keys(bytes([9]) * 32, "image")
    assert media_keys.iv.hex() == "3d5fe066de4dc55e3f832891ae03661f"
    assert media_keys.cipher_key.hex() == "5e6aefd482e67e3973dc969c24899445a5802c07fc08b3053e12a623b17b1fab"
    assert media_keys.mac_key.hex() == "21dc5fe9ef057e69ba7ca2da62fffc3cc3fdc086f6971c514e0a2fc4fd5ec897"
    print("OK media key derivation parity")

    pairing_key = derive_pairing_code_key(
        "ABCD-1234",
        bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"),
    )
    assert pairing_key.hex() == "4be88795e912d406dc59ad09c78ec27e65ed7d4230d78c5719ec5c0eff5faa70"
    print("OK pairing-code PBKDF2 parity")

    payload = b"<iq id='1'/>"
    assert decompress_if_required(b"\x00" + payload) == payload
    assert decompress_if_required(b"\x02" + zlib.compress(payload)) == payload
    print("OK WA binary frame decompression behavior")

    edge_vectors = {
        "nibble": (
            BinaryNode("edge", {"code": "12345-67.89"}),
            "00f803fc046564676570ff8612345a67b89f",
        ),
        "hex": (
            BinaryNode("edge", {"hexv": "A1B2C3F"}),
            "00f803fc0465646765fc0468657876fb84a1b2c3ff",
        ),
        "ad_jid": (
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
    }
    for name, (edge_node, expected_hex) in edge_vectors.items():
        encoded = encode_binary_node(edge_node)
        assert encoded.hex() == expected_hex, name
        assert decode_binary_node(encoded).attrs == edge_node.attrs
    print("OK packed nibble/hex and AD-JID binary-node parity")

    compressed_frame = bytes.fromhex("02789cfbc12ac911caa2090008ba01a1")
    compressed_decoded = decode_binary_node(decompress_if_required(compressed_frame), has_stream_prefix=False)
    assert compressed_decoded.tag == "iq"
    assert compressed_decoded.attrs == {"id": "1", "type": "get"}
    print("OK compressed incoming binary-node decode")

    fb_decoded = decode_binary_node(
        bytes.fromhex("00f803fc0465646765fc026662f6fc0531323334350007fc0866616365626f6f6b")
    )
    assert fb_decoded.attrs == {"fb": "12345:7@facebook"}

    interop_decoded = decode_binary_node(
        bytes.fromhex("00f803fc0465646765fc07696e7465726f70f5fc036162630009002afc07696e7465726f70")
    )
    assert interop_decoded.attrs == {"interop": "42-abc:9@interop"}
    print("OK FB-JID and interop-JID decode")

    node = BinaryNode(
        "iq",
        {"id": "1", "to": "s.whatsapp.net", "type": "get"},
        [BinaryNode("query", {"xmlns": "test"}, b"payload")],
    )
    python_raw = encode_binary_node(node).hex()
    assert python_raw == BRIDGE_TOKENIZED_NODE_HEX
    decoded = decode_binary_node(bytes.fromhex(BRIDGE_TOKENIZED_NODE_HEX))
    assert decoded.tag == "iq"
    assert decoded.attrs == {"id": "1", "to": "s.whatsapp.net", "type": "get"}
    assert isinstance(decoded.content, list)
    assert decoded.content[0].tag == "query"
    assert decoded.content[0].attrs == {"xmlns": "test"}
    assert decoded.content[0].content == b"payload"
    print("OK tokenized binary-node dictionary parity")

    group_result = run_group_sender_round_trip()
    assert group_result.plaintext == b"hello group"
    print("OK Signal group sender-key round-trip")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
