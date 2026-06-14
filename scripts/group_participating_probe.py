from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

import websockets
from websockets.exceptions import ConnectionClosed


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.auth_store import unb64  # noqa: E402
from baileys.crypto import decompress_if_required  # noqa: E402
from baileys.generated import WAProto_pb2 as proto  # noqa: E402
from baileys.noise import NoiseHandshake, generate_noise_key_pair  # noqa: E402
from baileys.registration import build_login_payload  # noqa: E402
from baileys.signal_crypto import SignalKeyPair  # noqa: E402
from baileys.socket_nodes import (  # noqa: E402
    SocketNodeKind,
    classify_node,
    find_child,
    server_ping_reply,
    summarize_node,
)
from baileys.usync import TagGenerator  # noqa: E402
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node  # noqa: E402


WA_WEBSOCKET_URL = "wss://web.whatsapp.com/ws/chat"
DEFAULT_ORIGIN = "https://web.whatsapp.com"


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
            kind = classify_node(node)
            print(f"RECV kind={kind.value} {summarize_node(node)}", flush=True)
            if kind == SocketNodeKind.SERVER_PING:
                await send_node(websocket, noise, server_ping_reply(node), "server-ping-reply")
            elif kind == SocketNodeKind.LOGIN_SUCCESS:
                return
            elif kind in {SocketNodeKind.FAILURE, SocketNodeKind.STREAM_ERROR, SocketNodeKind.IQ_ERROR}:
                raise ValueError(f"login failed: {node!r}")


def group_fetch_all_node(tag_id: str) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": "g.us", "xmlns": "w:g2", "type": "get"},
        [
            BinaryNode(
                "participating",
                {},
                [BinaryNode("participants", {}), BinaryNode("description", {})],
            )
        ],
    )


async def query_for_id(websocket, noise: NoiseHandshake, query_node: BinaryNode, label: str, timeout: float) -> BinaryNode:
    query_id = query_node.attrs["id"]
    await send_node(websocket, noise, query_node, label)
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise TimeoutError(f"timed out waiting for {label} result")
        try:
            nodes = await receive_nodes(websocket, noise, min(10, remaining))
        except TimeoutError:
            continue
        except ConnectionClosed as exc:
            raise TimeoutError(f"socket closed before {label} result") from exc
        for node in nodes:
            kind = classify_node(node)
            print(f"RECV kind={kind.value} {summarize_node(node)}", flush=True)
            if kind == SocketNodeKind.SERVER_PING:
                await send_node(websocket, noise, server_ping_reply(node), "server-ping-reply")
                continue
            if node.attrs.get("id") == query_id:
                if kind == SocketNodeKind.IQ_ERROR:
                    raise ValueError(f"{label} returned error: {node!r}")
                return node
            if kind in {SocketNodeKind.FAILURE, SocketNodeKind.STREAM_ERROR}:
                raise ValueError(f"socket failed during {label}: {node!r}")


def summarize_groups(result: BinaryNode) -> list[dict[str, object]]:
    groups_node = find_child(result, "groups")
    if not isinstance(groups_node.content if groups_node else None, list):
        return []
    groups: list[dict[str, object]] = []
    for group in groups_node.content:
        if group.tag != "group":
            continue
        participants = [child for child in group.content] if isinstance(group.content, list) else []
        participant_count = len([child for child in participants if child.tag == "participant"])
        group_id = group.attrs.get("id", "")
        groups.append(
            {
                "id": group_id if "@" in group_id else f"{group_id}@g.us",
                "size": int(group.attrs["size"]) if group.attrs.get("size") else participant_count,
                "participant_count": participant_count,
                "addressing_mode": group.attrs.get("addressing_mode"),
            }
        )
    return groups


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "live_pair_creds.json"))
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()

    creds = json.loads(Path(args.creds_path).read_text(encoding="utf-8"))
    tag_gen = TagGenerator()
    websocket, noise = await login_socket(creds)
    try:
        await wait_for_success(websocket, noise, args.timeout)
        result = await query_for_id(websocket, noise, group_fetch_all_node(tag_gen.next()), "group-participating", args.timeout)
        groups = summarize_groups(result)
        print(f"GROUPS_FOUND count={len(groups)}", flush=True)
        print("GROUPS_SUMMARY " + json.dumps(groups, separators=(",", ":")), flush=True)
    finally:
        await websocket.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
