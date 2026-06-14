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

from baileys.auth_store import save_creds, unb64  # noqa: E402
from baileys.crypto import decompress_if_required  # noqa: E402
from baileys.generated import WAProto_pb2 as proto  # noqa: E402
from baileys.message_send import build_text_message_node, jid_decode, jid_encode  # noqa: E402
from baileys.noise import NoiseHandshake, generate_noise_key_pair  # noqa: E402
from baileys.registration import build_login_payload  # noqa: E402
from baileys.session_assert import (  # noqa: E402
    encrypt_session_query_node,
    inject_sessions_from_encrypt_result,
    summarize_encrypt_user_shapes,
)
from baileys.signal_crypto import SignalKeyPair  # noqa: E402
from baileys.socket_nodes import (  # noqa: E402
    S_WHATSAPP_NET,
    SocketNodeKind,
    classify_node,
    server_ping_reply,
    summarize_node,
)
from baileys.usync import (  # noqa: E402
    TagGenerator,
    conversation_identities,
    extract_device_jids,
    parse_usync_result,
    split_own_and_other_devices,
    usync_devices_query_node,
)
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


async def watch_after_send(websocket, noise: NoiseHandshake, message_id: str, timeout: float) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    saw_related = False
    while True:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return saw_related
        try:
            nodes = await receive_nodes(websocket, noise, min(10, remaining))
        except TimeoutError:
            continue
        except ConnectionClosed:
            return saw_related
        for node in nodes:
            kind = classify_node(node)
            print(f"RECV kind={kind.value} {summarize_node(node)}", flush=True)
            if kind == SocketNodeKind.SERVER_PING:
                await send_node(websocket, noise, server_ping_reply(node), "server-ping-reply")
                continue
            if node.attrs.get("id") == message_id:
                saw_related = True
                if kind == SocketNodeKind.ACK:
                    return True
            if kind in {SocketNodeKind.FAILURE, SocketNodeKind.STREAM_ERROR, SocketNodeKind.IQ_ERROR}:
                raise ValueError(f"socket returned error after send: {node!r}")


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


def missing_session_jids(creds: dict, jids: list[str], *, force: bool) -> list[str]:
    if force:
        return jids
    sessions = creds.get("signal_sessions") or {}
    missing = []
    for jid in jids:
        left = jid.split("@", 1)[0]
        user, _, device = left.partition(":")
        key = f"{user}:{int(device) if device else 0}"
        if key not in sessions:
            missing.append(jid)
    return missing


async def prepare_usync_fanout(
    websocket,
    noise: NoiseHandshake,
    creds: dict,
    recipient_jid: str,
    tag_gen: TagGenerator,
    timeout: float,
    *,
    force_sessions: bool,
) -> tuple[list[str], list[str]]:
    identities = conversation_identities(creds, recipient_jid)
    print(f"USYNC_IDENTITIES {identities}", flush=True)
    usync_result_node = await query_for_id(
        websocket,
        noise,
        usync_devices_query_node(identities, tag_gen.next()),
        "usync-devices",
        timeout,
    )
    parsed = parse_usync_result(usync_result_node)
    devices = extract_device_jids(parsed, creds["me"]["id"], creds.get("me", {}).get("lid"))
    me_recipients, other_recipients = split_own_and_other_devices(creds, devices)
    all_recipients = me_recipients + other_recipients
    print(f"USYNC_DEVICE_JIDS {[device.jid for device in devices]}", flush=True)
    print(f"USYNC_ME_RECIPIENTS {me_recipients}", flush=True)
    print(f"USYNC_OTHER_RECIPIENTS {other_recipients}", flush=True)

    to_fetch = missing_session_jids(creds, all_recipients, force=force_sessions)
    print(f"ASSERT_SESSION_JIDS {to_fetch if to_fetch else 'already-present'}", flush=True)
    if to_fetch:
        encrypt_result = await query_for_id(
            websocket,
            noise,
            encrypt_session_query_node(to_fetch, tag_gen.next(), force=force_sessions),
            "encrypt-session",
            timeout,
        )
        shapes = summarize_encrypt_user_shapes(encrypt_result)
        print(
            "ENCRYPT_USER_SHAPES " + json.dumps([shape.__dict__ for shape in shapes], separators=(",", ":")),
            flush=True,
        )
        injected = inject_sessions_from_encrypt_result(creds, encrypt_result)
        print(f"INJECTED_SESSIONS {[item.address_key for item in injected]}", flush=True)
    return me_recipients, other_recipients


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "live_pair_creds.json"))
    parser.add_argument("--to", default="51213374591183@lid")
    parser.add_argument("--text", default="Python Baileys test message")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--watch", type=int, default=30)
    parser.add_argument("--direct-enc", action="store_true", help="use direct enc content; default unless --participants-wrapper is set")
    parser.add_argument("--participants-wrapper", action="store_true", help="diagnostic fanout shape; live LID 1:1 tests returned 479")
    parser.add_argument("--fanout-own-pn", action="store_true")
    parser.add_argument("--usync-fanout", action="store_true", help="discover devices with USync and send Baileys-style participants fanout")
    parser.add_argument("--force-usync-sessions", action="store_true", help="force encrypt session refresh for USync recipients")
    parser.add_argument("--include-phash", action="store_true", help="diagnostic: attach participant hash to outbound message attrs")
    args = parser.parse_args()

    creds_path = Path(args.creds_path)
    creds = json.loads(creds_path.read_text(encoding="utf-8"))
    websocket, noise = await login_socket(creds)
    try:
        await wait_for_success(websocket, noise, args.timeout)
        tag_gen = TagGenerator()
        recipient_device_jids = None
        own_fanout_jids = []
        if args.fanout_own_pn:
            own_user, _, _ = jid_decode(creds["me"]["id"])
            own_fanout_jids.append(jid_encode(own_user, "s.whatsapp.net", 0))
        if args.usync_fanout:
            own_fanout_jids, recipient_device_jids = await prepare_usync_fanout(
                websocket,
                noise,
                creds,
                args.to,
                tag_gen,
                args.timeout,
                force_sessions=args.force_usync_sessions,
            )
            save_creds(creds_path, creds)
        outbound = build_text_message_node(
            creds,
            args.to,
            args.text,
            direct_enc=args.direct_enc or not (args.participants_wrapper or args.usync_fanout),
            recipient_device_jids=recipient_device_jids,
            own_fanout_jids=own_fanout_jids,
            include_phash=args.include_phash,
        )
        print(
            f"OUTBOUND_READY id={outbound.message_id} to={args.to} signal_type={outbound.signal_type} "
            f"addr={outbound.recipient_address} participants={outbound.participant_jids} "
            f"signal_types={outbound.signal_types}",
            flush=True,
        )
        await send_node(websocket, noise, outbound.node, "text-message")
        related = await watch_after_send(websocket, noise, outbound.message_id, args.watch)
        if related:
            save_creds(creds_path, creds)
        print(f"SEND_TEXT_PROBE_DONE id={outbound.message_id} related_response={related}", flush=True)
    finally:
        await websocket.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
