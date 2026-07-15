from __future__ import annotations

import asyncio
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
from baileys.wabinary import BinaryNode, decode_binary_node  # noqa: E402


WA_WEBSOCKET_URL = "wss://web.whatsapp.com/ws/chat"
DEFAULT_ORIGIN = "https://web.whatsapp.com"


def summarize_node(node: BinaryNode) -> str:
    child_tags = []
    if isinstance(node.content, list):
        child_tags = [child.tag for child in node.content]
    return f"tag={node.tag!r} attrs={node.attrs!r} children={child_tags!r}"


async def main() -> int:
    ephemeral = generate_noise_key_pair()
    static_noise = generate_noise_key_pair()
    noise = NoiseHandshake(ephemeral)

    async with websockets.connect(
        WA_WEBSOCKET_URL,
        origin=DEFAULT_ORIGIN,
        open_timeout=20,
        close_timeout=5,
        additional_headers={"User-Agent": "Mozilla/5.0 baileys-python"},
    ) as websocket:
        await websocket.send(noise.client_hello_frame())
        response = await asyncio.wait_for(websocket.recv(), timeout=20)
        if isinstance(response, str):
            response = response.encode("latin1")
        size = int.from_bytes(response[:3], "big")
        server_hello_payload = response[3 : 3 + size]
        info = noise.process_server_hello(server_hello_payload, static_noise)

        registration_payload, meta = build_registration_payload()
        encrypted_payload = noise.encrypt(registration_payload)
        finish = proto.HandshakeMessage()
        finish.clientFinish.static = info.encrypted_static_key
        finish.clientFinish.payload = encrypted_payload
        await websocket.send(noise.encode_frame(finish.SerializeToString()))
        noise.finish_init()

        print(f"OK sent clientFinish registration_id={meta['registration_id']}")

        raw = await asyncio.wait_for(websocket.recv(), timeout=25)
        if isinstance(raw, str):
            raw = raw.encode("latin1")
        plaintext_frames = noise.decode_transport_frames(raw)
        print(f"OK decrypted post-handshake frames: {len(plaintext_frames)}")
        for index, plaintext in enumerate(plaintext_frames):
            decompressed = decompress_if_required(plaintext)
            node = decode_binary_node(decompressed, has_stream_prefix=False)
            print(f"frame[{index}] {summarize_node(node)}")
        await websocket.close()

    print("Registration bootstrap probe reached encrypted post-handshake node.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
