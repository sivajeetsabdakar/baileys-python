from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

import websockets


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.auth_store import load_creds, save_creds, unb64  # noqa: E402
from baileys.crypto import decompress_if_required  # noqa: E402
from baileys.generated import WAProto_pb2 as proto  # noqa: E402
from baileys.noise import NoiseHandshake, generate_noise_key_pair  # noqa: E402
from baileys.registration import build_login_payload  # noqa: E402
from baileys.routing import websocket_url_with_routing  # noqa: E402
from baileys.signal_crypto import SignalKeyPair  # noqa: E402
from baileys.socket_nodes import (  # noqa: E402
    SocketNodeKind,
    classify_node,
    find_child,
    node_content_bytes,
    server_ping_reply,
    summarize_node,
)
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node  # noqa: E402


WA_WEBSOCKET_URL = "wss://web.whatsapp.com/ws/chat"
DEFAULT_ORIGIN = "https://web.whatsapp.com"
USER_AGENT = "Mozilla/5.0 baileys-python"


class TagGenerator:
    def __init__(self) -> None:
        self.prefix = f"{int(time.time() * 1000)}."
        self.epoch = 1

    def next(self) -> str:
        tag = f"{self.prefix}{self.epoch}"
        self.epoch += 1
        return tag


def persist_edge_routing_if_present(creds_path: Path, creds: dict, node: BinaryNode) -> bool:
    routing_info = find_child(find_child(node, "edge_routing"), "routing_info")
    content = node_content_bytes(routing_info)
    if not content:
        return False
    import base64

    creds["routing_info"] = base64.b64encode(content).decode("ascii")
    save_creds(creds_path, creds)
    return True


async def send_node(websocket, noise: NoiseHandshake, node: BinaryNode, label: str) -> None:
    await websocket.send(noise.encode_frame(encode_binary_node(node)))
    print(f"SENT {label} {summarize_node(node)}", flush=True)


async def receive_nodes(websocket, noise: NoiseHandshake, timeout: float) -> list[BinaryNode]:
    raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
    if isinstance(raw, str):
        raw = raw.encode("latin1")
    nodes: list[BinaryNode] = []
    for plaintext in noise.decode_transport_frames(raw):
        nodes.append(decode_binary_node(decompress_if_required(plaintext), has_stream_prefix=False))
    return nodes


async def reconnect_cycle(creds_path: Path, cycle: int, use_routing: bool, settle_seconds: int) -> bool:
    creds = load_creds(creds_path)
    me = creds["me"]["id"]
    routing_info = unb64(creds["routing_info"]) if use_routing and creds.get("routing_info") else None
    url = websocket_url_with_routing(WA_WEBSOCKET_URL, routing_info)
    ephemeral = generate_noise_key_pair()
    static_noise = SignalKeyPair(private=unb64(creds["noise_private"]), public=unb64(creds["noise_public"]))
    noise = NoiseHandshake(ephemeral, routing_info=routing_info)

    async with websockets.connect(
        url,
        origin=DEFAULT_ORIGIN,
        open_timeout=20,
        close_timeout=5,
        ping_interval=None,
        additional_headers={"User-Agent": USER_AGENT},
    ) as websocket:
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

        tag_gen = TagGenerator()
        deadline = asyncio.get_running_loop().time() + settle_seconds
        saw_success = False
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                nodes = await receive_nodes(websocket, noise, min(10, remaining))
            except TimeoutError:
                continue
            for node in nodes:
                kind = classify_node(node)
                print(f"CYCLE={cycle} RECV kind={kind.value} {summarize_node(node)}", flush=True)
                if kind == SocketNodeKind.LOGIN_SUCCESS:
                    saw_success = True
                    await send_node(
                        websocket,
                        noise,
                        BinaryNode(
                            "iq",
                            {"to": "s.whatsapp.net", "xmlns": "passive", "type": "set", "id": tag_gen.next()},
                            [BinaryNode("active", {})],
                        ),
                        "passive-active",
                    )
                    continue
                if kind == SocketNodeKind.SERVER_PING:
                    await send_node(websocket, noise, server_ping_reply(node), "server-ping-reply")
                    continue
                if kind == SocketNodeKind.EDGE_ROUTING:
                    if persist_edge_routing_if_present(creds_path, creds, node):
                        print(f"CYCLE={cycle} SAVED_EDGE_ROUTING", flush=True)
                    continue
                if kind in {SocketNodeKind.FAILURE, SocketNodeKind.STREAM_ERROR, SocketNodeKind.IQ_ERROR}:
                    raise ValueError(f"reconnect failed: {node!r}")
                if saw_success:
                    break
            if saw_success:
                break

        if not saw_success:
            raise TimeoutError(f"cycle {cycle} timed out before login success")
        print(f"RECONNECT_CYCLE_OK cycle={cycle} routed={routing_info is not None}", flush=True)
        return routing_info is not None


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "live_pair_creds.json"))
    parser.add_argument("--cycles", type=int, default=2)
    parser.add_argument("--settle-seconds", type=int, default=12)
    parser.add_argument("--no-routing", action="store_true")
    args = parser.parse_args()

    creds_path = Path(args.creds_path)
    routed_cycles = 0
    for cycle in range(1, args.cycles + 1):
        if await reconnect_cycle(creds_path, cycle, not args.no_routing, args.settle_seconds):
            routed_cycles += 1
        await asyncio.sleep(1)

    print(f"RECONNECT_PROBE_OK cycles={args.cycles} routed_cycles={routed_cycles}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
