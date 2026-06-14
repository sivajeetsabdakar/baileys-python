from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import time
from pathlib import Path

import websockets


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.auth_store import save_creds, unb64  # noqa: E402
from baileys.crypto import decompress_if_required  # noqa: E402
from baileys.generated import WAProto_pb2 as proto  # noqa: E402
from baileys.noise import NoiseHandshake, generate_noise_key_pair  # noqa: E402
from baileys.prekeys import digest_key_bundle_node, rotate_signed_pre_key_node  # noqa: E402
from baileys.registration import build_login_payload  # noqa: E402
from baileys.signal_crypto import SignalKeyPair  # noqa: E402
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node  # noqa: E402


WA_WEBSOCKET_URL = "wss://web.whatsapp.com/ws/chat"
DEFAULT_ORIGIN = "https://web.whatsapp.com"
S_WHATSAPP_NET = "s.whatsapp.net"


class TagGenerator:
    def __init__(self) -> None:
        self.prefix = f"{int(time.time() * 1000)}."
        self.epoch = 1

    def next(self) -> str:
        tag = f"{self.prefix}{self.epoch}"
        self.epoch += 1
        return tag


def summarize_node(node: BinaryNode) -> str:
    child_tags: list[str] = []
    if isinstance(node.content, list):
        child_tags = [child.tag for child in node.content]
    return f"tag={node.tag!r} attrs={node.attrs!r} children={child_tags!r}"


def find_child(node: BinaryNode | None, tag: str) -> BinaryNode | None:
    if node is None or not isinstance(node.content, list):
        return None
    for child in node.content:
        if child.tag == tag:
            return child
    return None


def is_server_ping(node: BinaryNode) -> bool:
    return node.tag == "iq" and node.attrs.get("type") == "get" and node.attrs.get("xmlns") == "urn:xmpp:ping"


def server_ping_reply(node: BinaryNode) -> BinaryNode:
    attrs = {"to": S_WHATSAPP_NET, "type": "result"}
    if node.attrs.get("id"):
        attrs["id"] = node.attrs["id"]
    if node.attrs.get("t"):
        attrs["t"] = node.attrs["t"]
    return BinaryNode("iq", attrs)


def is_error_node(node: BinaryNode) -> bool:
    return node.tag in {"failure", "stream:error"} or find_child(node, "error") is not None


async def send_node(websocket, noise: NoiseHandshake, node: BinaryNode, label: str) -> None:
    await websocket.send(noise.encode_frame(encode_binary_node(node)))
    print(f"SENT {label} {summarize_node(node)}", flush=True)


async def receive_nodes(websocket, noise: NoiseHandshake, timeout: float) -> list[BinaryNode]:
    raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    if isinstance(raw, str):
        raw = raw.encode("latin1")
    return [
        decode_binary_node(decompress_if_required(plaintext), has_stream_prefix=False)
        for plaintext in noise.decode_transport_frames(raw)
    ]


async def login_socket(creds: dict):
    me = creds["me"]["id"]
    ephemeral = generate_noise_key_pair()
    static_noise = SignalKeyPair(private=unb64(creds["noise_private"]), public=unb64(creds["noise_public"]))
    noise = NoiseHandshake(ephemeral)

    websocket = await websockets.connect(
        WA_WEBSOCKET_URL,
        origin=DEFAULT_ORIGIN,
        open_timeout=20,
        close_timeout=5,
        ping_interval=None,
        additional_headers={"User-Agent": "Mozilla/5.0 baileys-python-test"},
    )
    await websocket.send(noise.client_hello_frame())
    response = await asyncio.wait_for(websocket.recv(), timeout=20)
    if isinstance(response, str):
        response = response.encode("latin1")
    server_hello_payload = response[3 : 3 + int.from_bytes(response[:3], "big")]
    info = noise.process_server_hello(server_hello_payload, static_noise)

    finish = proto.HandshakeMessage()
    finish.clientFinish.static = info.encrypted_static_key
    finish.clientFinish.payload = noise.encrypt(build_login_payload(me))
    await websocket.send(noise.encode_frame(finish.SerializeToString()))
    noise.finish_init()
    print(f"OK sent login clientFinish for {me}", flush=True)
    return websocket, noise


async def wait_for_success(websocket, noise: NoiseHandshake, timeout: float) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError("timed out before login success")
        for node in await receive_nodes(websocket, noise, min(10, remaining)):
            print(f"RECV {summarize_node(node)}", flush=True)
            if is_server_ping(node):
                await send_node(websocket, noise, server_ping_reply(node), "server-ping-reply")
            elif node.tag == "success":
                return
            elif is_error_node(node):
                raise ValueError(f"login failed: {node!r}")


async def query_and_wait(websocket, noise: NoiseHandshake, query: BinaryNode, label: str, timeout: float) -> BinaryNode:
    query_id = query.attrs.get("id")
    await send_node(websocket, noise, query, label)
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"timed out waiting for {label} response")
        for node in await receive_nodes(websocket, noise, min(10, remaining)):
            print(f"RECV {summarize_node(node)}", flush=True)
            if is_server_ping(node):
                await send_node(websocket, noise, server_ping_reply(node), "server-ping-reply")
                continue
            if query_id and node.attrs.get("id") != query_id:
                continue
            if is_error_node(node):
                raise ValueError(f"{label} returned error: {node!r}")
            return node


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "live_pair_creds.json"))
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--rotate", action="store_true", help="also send signed pre-key rotation and persist on success")
    args = parser.parse_args()

    creds_path = Path(args.creds_path)
    creds = json.loads(creds_path.read_text(encoding="utf-8"))
    tag_gen = TagGenerator()

    websocket, noise = await login_socket(creds)
    try:
        await wait_for_success(websocket, noise, args.timeout)

        digest = await query_and_wait(
            websocket,
            noise,
            digest_key_bundle_node(tag_gen.next()),
            "prekey-digest",
            args.timeout,
        )
        if find_child(digest, "digest") is None:
            raise ValueError(f"prekey digest response has no digest child: {digest!r}")
        print("PREKEY_DIGEST_OK", flush=True)

        if args.rotate:
            rotated_creds = copy.deepcopy(creds)
            rotation = rotate_signed_pre_key_node(rotated_creds, tag_gen.next())
            response = await query_and_wait(websocket, noise, rotation.node, "signed-prekey-rotate", args.timeout)
            if response.attrs.get("type") != "result":
                raise ValueError(f"rotation response was not result: {response!r}")
            save_creds(creds_path, rotated_creds)
            print(f"SIGNED_PREKEY_ROTATE_OK key_id={rotation.key_id}", flush=True)
    finally:
        await websocket.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
