from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

import websockets


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.crypto import decompress_if_required  # noqa: E402
from baileys.generated import WAProto_pb2 as proto  # noqa: E402
from baileys.noise import NoiseHandshake, generate_noise_key_pair  # noqa: E402
from baileys.prekeys import MIN_PREKEY_COUNT, build_prekey_upload_node  # noqa: E402
from baileys.registration import build_login_payload  # noqa: E402
from baileys.signal_crypto import SignalKeyPair  # noqa: E402
from baileys.socket_nodes import (  # noqa: E402
    SocketNodeKind,
    classify_node,
    encrypt_count,
    find_child,
    node_content_bytes,
    offline_batch_node,
    server_ping_reply,
    summarize_node,
)
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node  # noqa: E402


WA_WEBSOCKET_URL = "wss://web.whatsapp.com/ws/chat"
DEFAULT_ORIGIN = "https://web.whatsapp.com"
S_WHATSAPP_NET = "s.whatsapp.net"
TIME_MS_DAY = 24 * 60 * 60 * 1000
TIME_MS_WEEK = 7 * TIME_MS_DAY


class TagGenerator:
    def __init__(self) -> None:
        self.prefix = f"{int(time.time() * 1000)}."
        self.epoch = 1

    def next(self) -> str:
        tag = f"{self.prefix}{self.epoch}"
        self.epoch += 1
        return tag


def unb64(value: str) -> bytes:
    return base64.b64decode(value)


def node_to_json(node: BinaryNode) -> dict:
    if isinstance(node.content, bytes):
        content: object = {"type": "bytes", "base64": b64(node.content), "length": len(node.content)}
    elif isinstance(node.content, list):
        content = [node_to_json(child) for child in node.content]
    else:
        content = node.content
    return {"tag": node.tag, "attrs": node.attrs, "content": content}


def append_capture(path: Path | None, node: BinaryNode) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(node_to_json(node), separators=(",", ":")) + "\n")


def unified_session_id(server_time_offset_ms: int) -> str:
    now_ms = int(time.time() * 1000) + server_time_offset_ms
    return str((now_ms + 3 * TIME_MS_DAY) % TIME_MS_WEEK)


def passive_active_node(tag_gen: TagGenerator) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"to": S_WHATSAPP_NET, "xmlns": "passive", "type": "set", "id": tag_gen.next()},
        [BinaryNode("active", {})],
    )


def unified_session_node(server_time_offset_ms: int) -> BinaryNode:
    return BinaryNode("ib", {}, [BinaryNode("unified_session", {"id": unified_session_id(server_time_offset_ms)})])


def client_ping_node(tag_gen: TagGenerator) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"id": tag_gen.next(), "to": S_WHATSAPP_NET, "type": "get", "xmlns": "w:p"},
        [BinaryNode("ping", {})],
    )


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def persist_creds(path: Path, creds: dict) -> None:
    path.write_text(json.dumps(creds, indent=2), encoding="utf-8")


def persist_edge_routing_if_present(creds_path: Path, creds: dict, node: BinaryNode) -> bool:
    routing_info = find_child(find_child(node, "edge_routing"), "routing_info")
    content = node_content_bytes(routing_info)
    if not content:
        return False
    creds["routing_info"] = b64(content)
    persist_creds(creds_path, creds)
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


async def keepalive_loop(websocket, noise: NoiseHandshake, tag_gen: TagGenerator, interval: int) -> None:
    try:
        while True:
            await asyncio.sleep(interval)
            await send_node(websocket, noise, client_ping_node(tag_gen), "client-ping")
    except asyncio.CancelledError:
        return


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "live_pair_creds.json"))
    parser.add_argument("--duration", type=int, default=90)
    parser.add_argument("--keepalive-interval", type=int, default=30)
    parser.add_argument("--prekey-upload-count", type=int, default=MIN_PREKEY_COUNT)
    parser.add_argument("--capture-messages")
    args = parser.parse_args()

    creds_path = Path(args.creds_path)
    creds = json.loads(creds_path.read_text(encoding="utf-8"))
    me = creds["me"]["id"]
    if not me:
        raise ValueError("creds file has no me.id")

    tag_gen = TagGenerator()
    ephemeral = generate_noise_key_pair()
    static_noise = SignalKeyPair(private=unb64(creds["noise_private"]), public=unb64(creds["noise_public"]))
    noise = NoiseHandshake(ephemeral)
    server_time_offset_ms = 0
    saw_success = False
    keepalive_task: asyncio.Task[None] | None = None
    capture_path = Path(args.capture_messages) if args.capture_messages else None
    if capture_path and capture_path.exists():
        capture_path.unlink()

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

        finish = proto.HandshakeMessage()
        finish.clientFinish.static = info.encrypted_static_key
        finish.clientFinish.payload = noise.encrypt(build_login_payload(me))
        await websocket.send(noise.encode_frame(finish.SerializeToString()))
        noise.finish_init()
        print(f"OK sent login clientFinish for {me}", flush=True)

        deadline = asyncio.get_running_loop().time() + args.duration
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
                print(f"RECV kind={kind.value} {summarize_node(node)}", flush=True)
                if kind == SocketNodeKind.MESSAGE:
                    append_capture(capture_path, node)
                if kind == SocketNodeKind.SERVER_PING:
                    await send_node(websocket, noise, server_ping_reply(node), "server-ping-reply")
                    continue
                if kind == SocketNodeKind.ENCRYPT_COUNT:
                    count = encrypt_count(node)
                    print(f"PREKEY_COUNT value={count}", flush=True)
                    if count < MIN_PREKEY_COUNT:
                        upload = build_prekey_upload_node(creds, args.prekey_upload_count, tag_gen.next()).node
                        persist_creds(creds_path, creds)
                        await send_node(websocket, noise, upload, f"prekey-upload count={args.prekey_upload_count}")
                    continue
                if kind == SocketNodeKind.EDGE_ROUTING:
                    if persist_edge_routing_if_present(creds_path, creds, node):
                        print("SAVED_EDGE_ROUTING", flush=True)
                    continue
                if kind == SocketNodeKind.OFFLINE_PREVIEW:
                    await send_node(websocket, noise, offline_batch_node(), "offline-batch")
                    continue
                if kind == SocketNodeKind.LOGIN_SUCCESS:
                    saw_success = True
                    if node.attrs.get("t"):
                        server_time_offset_ms = int(node.attrs["t"]) * 1000 - int(time.time() * 1000)
                    await send_node(websocket, noise, passive_active_node(tag_gen), "passive-active")
                    await send_node(websocket, noise, unified_session_node(server_time_offset_ms), "unified-session")
                    keepalive_task = asyncio.create_task(
                        keepalive_loop(websocket, noise, tag_gen, args.keepalive_interval)
                    )
                    continue
                if kind in {SocketNodeKind.FAILURE, SocketNodeKind.STREAM_ERROR, SocketNodeKind.IQ_ERROR}:
                    raise ValueError(f"login/socket failed: {node!r}")

        if keepalive_task:
            keepalive_task.cancel()
            await asyncio.gather(keepalive_task, return_exceptions=True)
        if not saw_success:
            raise TimeoutError("timed out before login success")
        print(f"PERSISTENT_LOGIN_OK duration={args.duration}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
