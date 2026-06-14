from __future__ import annotations

import asyncio
import base64
import sys
from pathlib import Path

import websockets


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.crypto import decompress_if_required  # noqa: E402
from baileys.generated import WAProto_pb2 as proto  # noqa: E402
from baileys.noise import NoiseHandshake, generate_noise_key_pair  # noqa: E402
from baileys.registration import build_registration_payload  # noqa: E402
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node  # noqa: E402


WA_WEBSOCKET_URL = "wss://web.whatsapp.com/ws/chat"
DEFAULT_ORIGIN = "https://web.whatsapp.com"
S_WHATSAPP_NET = "s.whatsapp.net"
COMPANION_PLATFORM_CHROME = "1"


def find_child(node: BinaryNode, tag: str) -> BinaryNode | None:
    if not isinstance(node.content, list):
        return None
    for child in node.content:
        if child.tag == tag:
            return child
    return None


def find_children(node: BinaryNode | None, tag: str) -> list[BinaryNode]:
    if node is None or not isinstance(node.content, list):
        return []
    return [child for child in node.content if child.tag == tag]


def node_content_text(node: BinaryNode) -> str:
    if isinstance(node.content, bytes):
        return node.content.decode("utf-8")
    if isinstance(node.content, str):
        return node.content
    raise TypeError(f"expected text content in {node.tag!r}, got {type(node.content)!r}")


def build_pairing_qr_data(ref: str, noise_key: bytes, identity_key: bytes, adv_secret_key: str) -> str:
    return "https://wa.me/settings/linked_devices#" + ",".join(
        [
            ref,
            base64.b64encode(noise_key).decode("ascii"),
            base64.b64encode(identity_key).decode("ascii"),
            adv_secret_key,
            COMPANION_PLATFORM_CHROME,
        ]
    )


async def receive_node(websocket, noise: NoiseHandshake) -> BinaryNode:
    raw = await asyncio.wait_for(websocket.recv(), timeout=25)
    if isinstance(raw, str):
        raw = raw.encode("latin1")
    plaintext_frames = noise.decode_transport_frames(raw)
    if not plaintext_frames:
        raise ValueError("server returned no transport frames")
    return decode_binary_node(decompress_if_required(plaintext_frames[0]), has_stream_prefix=False)


async def main() -> int:
    ephemeral = generate_noise_key_pair()
    static_noise = generate_noise_key_pair()
    noise = NoiseHandshake(ephemeral)

    async with websockets.connect(
        WA_WEBSOCKET_URL,
        origin=DEFAULT_ORIGIN,
        open_timeout=20,
        close_timeout=5,
        additional_headers={"User-Agent": "Mozilla/5.0 baileys-python-test"},
    ) as websocket:
        await websocket.send(noise.client_hello_frame())
        response = await asyncio.wait_for(websocket.recv(), timeout=20)
        if isinstance(response, str):
            response = response.encode("latin1")
        server_hello_payload = response[3 : 3 + int.from_bytes(response[:3], "big")]
        info = noise.process_server_hello(server_hello_payload, static_noise)

        registration_payload, meta = build_registration_payload()
        encrypted_payload = noise.encrypt(registration_payload)
        finish = proto.HandshakeMessage()
        finish.clientFinish.static = info.encrypted_static_key
        finish.clientFinish.payload = encrypted_payload
        await websocket.send(noise.encode_frame(finish.SerializeToString()))
        noise.finish_init()

        node = await receive_node(websocket, noise)
        pair_device = find_child(node, "pair-device")
        refs = find_children(pair_device, "ref")
        if node.tag != "iq" or node.attrs.get("type") != "set" or not refs:
            raise ValueError(f"expected pair-device iq with refs, got {node!r}")

        ack = BinaryNode("iq", {"to": S_WHATSAPP_NET, "type": "result", "id": node.attrs["id"]})
        await websocket.send(noise.encode_frame(encode_binary_node(ack)))

        first_ref = node_content_text(refs[0])
        qr = build_pairing_qr_data(
            first_ref,
            static_noise.public,
            meta["identity_public"],
            str(meta["adv_secret_key"]),
        )
        print(f"OK pair-device refs: {len(refs)}")
        print(f"OK acknowledged pair-device id={node.attrs['id']}")
        print(f"OK first ref length: {len(first_ref)}")
        print(f"QR payload: {qr}")
        await websocket.close()

    print("QR ref probe generated a Baileys-compatible pairing payload.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
