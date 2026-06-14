from __future__ import annotations

import argparse
import asyncio
import base64
import json
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
from baileys.registration import build_login_payload  # noqa: E402
from baileys.signal_crypto import SignalKeyPair  # noqa: E402
from baileys.wabinary import BinaryNode, decode_binary_node  # noqa: E402


WA_WEBSOCKET_URL = "wss://web.whatsapp.com/ws/chat"
DEFAULT_ORIGIN = "https://web.whatsapp.com"


def unb64(value: str) -> bytes:
    return base64.b64decode(value)


def summarize_node(node: BinaryNode) -> str:
    child_tags: list[str] = []
    if isinstance(node.content, list):
        child_tags = [child.tag for child in node.content]
    return f"tag={node.tag!r} attrs={node.attrs!r} children={child_tags!r}"


async def receive_nodes(websocket, noise: NoiseHandshake, timeout: float) -> list[BinaryNode]:
    raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    if isinstance(raw, str):
        raw = raw.encode("latin1")
    nodes: list[BinaryNode] = []
    for plaintext in noise.decode_transport_frames(raw):
        nodes.append(decode_binary_node(decompress_if_required(plaintext), has_stream_prefix=False))
    return nodes


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "live_pair_creds.json"))
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    creds = json.loads(Path(args.creds_path).read_text(encoding="utf-8"))
    me = creds["me"]["id"]
    if not me:
        raise ValueError("creds file has no me.id")

    ephemeral = generate_noise_key_pair()
    static_noise = SignalKeyPair(private=unb64(creds["noise_private"]), public=unb64(creds["noise_public"]))
    noise = NoiseHandshake(ephemeral)

    async with websockets.connect(
        WA_WEBSOCKET_URL,
        origin=DEFAULT_ORIGIN,
        open_timeout=20,
        close_timeout=5,
        ping_interval=None,
        additional_headers={"User-Agent": "Mozilla/5.0 baileys-python-test"},
    ) as websocket:
        await websocket.send(noise.client_hello_frame())
        response = await asyncio.wait_for(websocket.recv(), timeout=20)
        if isinstance(response, str):
            response = response.encode("latin1")
        server_hello_payload = response[3 : 3 + int.from_bytes(response[:3], "big")]
        info = noise.process_server_hello(server_hello_payload, static_noise)

        login_payload = build_login_payload(me)
        finish = proto.HandshakeMessage()
        finish.clientFinish.static = info.encrypted_static_key
        finish.clientFinish.payload = noise.encrypt(login_payload)
        await websocket.send(noise.encode_frame(finish.SerializeToString()))
        noise.finish_init()
        print(f"OK sent login clientFinish for {me}", flush=True)

        deadline = asyncio.get_running_loop().time() + args.timeout
        saw_success = False
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            for node in await receive_nodes(websocket, noise, min(30, remaining)):
                print(f"RECV {summarize_node(node)}", flush=True)
                if node.tag == "success":
                    saw_success = True
                    print("LOGIN_SUCCESS", flush=True)
                    return 0
                if node.tag == "failure" or (node.tag == "stream:error"):
                    raise ValueError(f"login failed: {node!r}")

        if not saw_success:
            raise TimeoutError("timed out waiting for login success")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
