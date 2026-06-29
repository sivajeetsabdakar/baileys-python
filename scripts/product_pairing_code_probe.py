from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import websockets


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.auth_state import JsonCredentialStore  # noqa: E402
from baileys.crypto import decompress_if_required  # noqa: E402
from baileys.generated import WAProto_pb2 as proto  # noqa: E402
from baileys.noise import NoiseHandshake, generate_noise_key_pair  # noqa: E402
from baileys.pairing_code import pairing_code_finish_node, pairing_code_request_node, phone_jid  # noqa: E402
from baileys.registration import build_registration_payload  # noqa: E402
from baileys.signal_crypto import SignalKeyPair  # noqa: E402
from baileys.socket_nodes import find_child, node_content_bytes, server_ping_reply, summarize_node  # noqa: E402
from baileys.socket import make_socket  # noqa: E402
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node  # noqa: E402


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


def find_children(node: BinaryNode | None, tag: str) -> list[BinaryNode]:
    if node is None or not isinstance(node.content, list):
        return []
    return [child for child in node.content if child.tag == tag]


def is_server_ping(node: BinaryNode) -> bool:
    return node.tag == "iq" and node.attrs.get("type") == "get" and node.attrs.get("xmlns") == "urn:xmpp:ping"


def describe_companion_reg(node: BinaryNode) -> str:
    reg = find_child(node, "link_code_companion_reg")
    if reg is None:
        return "missing"
    child_tags = [child.tag for child in reg.content] if isinstance(reg.content, list) else []
    return f"attrs={reg.attrs} children={child_tags}"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Pair a device with a phone-number pairing code.")
    parser.add_argument("--phone", required=True, help="Phone number with country code, digits or WhatsApp JID.")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "pairing_code_creds.json"))
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--request-timeout", type=float, default=30)
    parser.add_argument("--custom-code")
    args = parser.parse_args()

    creds_path = Path(args.creds_path).resolve()
    client = make_socket(creds_path)
    ephemeral = generate_noise_key_pair()
    static_noise = generate_noise_key_pair()
    pairing_ephemeral = generate_noise_key_pair()
    noise = NoiseHandshake(ephemeral)

    await client.ev.emit("connection.update", {"connection": "connecting", "pairing": "code"})
    websocket = await websockets.connect(
        client.websocket_url,
        origin=client.origin,
        open_timeout=20,
        close_timeout=5,
        ping_interval=None,
        additional_headers={"User-Agent": client.config.user_agent},
    )
    try:
        await websocket.send(noise.client_hello_frame())
        response = await asyncio.wait_for(websocket.recv(), timeout=20)
        if isinstance(response, str):
            response = response.encode("latin1")
        server_hello_payload = response[3 : 3 + int.from_bytes(response[:3], "big")]
        info = noise.process_server_hello(server_hello_payload, static_noise)

        registration_payload, meta = build_registration_payload()
        finish = proto.HandshakeMessage()
        finish.clientFinish.static = info.encrypted_static_key
        finish.clientFinish.payload = noise.encrypt(registration_payload)
        await websocket.send(noise.encode_frame(finish.SerializeToString()))
        noise.finish_init()
        print(f"REGISTRATION_SENT jid={phone_jid(args.phone)}", flush=True)

        deadline = asyncio.get_running_loop().time() + args.request_timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            try:
                nodes = await receive_nodes(websocket, noise, min(10, remaining))
            except asyncio.TimeoutError:
                continue
            for node in nodes:
                print(f"RECV {summarize_node(node)}", flush=True)
                pair_device = find_child(node, "pair-device")
                refs = find_children(pair_device, "ref")
                if node.tag == "iq" and node.attrs.get("type") == "set" and refs:
                    await send_node(
                        websocket,
                        noise,
                        BinaryNode("iq", {"to": "s.whatsapp.net", "type": "result", "id": node.attrs["id"]}),
                        "pair-device-ack",
                    )
                elif is_server_ping(node):
                    await send_node(websocket, noise, server_ping_reply(node), "server-ping-reply")

        request = pairing_code_request_node(
            phone_number=args.phone,
            tag_id=client.queries.next_tag(),
            companion_ephemeral_public=pairing_ephemeral.public,
            noise_public=static_noise.public,
            custom_pairing_code=args.custom_code,
        )
        client.auth_state.credentials.update(
            {
                "pairing_code": request.code,
                "pairingCode": request.code,
                "pairing_ephemeral_private": pairing_ephemeral.private.hex(),
                "pairing_ephemeral_public": pairing_ephemeral.public.hex(),
                "me": {"id": request.jid, "name": "~"},
            }
        )
        await send_node(websocket, noise, request.node, "pairing-code-request")
        await client.ev.emit("connection.update", {"pairing_code": request.code, "pairing_jid": request.jid})
        print(f"PAIRING_CODE_READY code={request.code} jid={request.jid}", flush=True)
        print("ENTER_CODE_ON_PHONE", flush=True)

        sent_finish = False
        deadline = asyncio.get_running_loop().time() + args.timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                print(f"PAIRING_CODE_TIMEOUT seconds={args.timeout}", flush=True)
                return 2
            try:
                nodes = await receive_nodes(websocket, noise, min(30, remaining))
            except asyncio.TimeoutError:
                continue
            for node in nodes:
                print(f"RECV {summarize_node(node)}", flush=True)
                if is_server_ping(node):
                    await send_node(websocket, noise, server_ping_reply(node), "server-ping-reply")
                    continue

                reg = find_child(node, "link_code_companion_reg")
                if reg is not None and not sent_finish:
                    print(f"PAIRING_CODE_CALLBACK {describe_companion_reg(node)}", flush=True)
                    ref = node_content_bytes(find_child(reg, "link_code_pairing_ref"))
                    primary_identity = node_content_bytes(find_child(reg, "primary_identity_pub"))
                    wrapped_primary = node_content_bytes(
                        find_child(reg, "link_code_pairing_wrapped_primary_ephemeral_pub")
                    )
                    if ref is None or primary_identity is None or wrapped_primary is None:
                        if ref is not None:
                            print(f"PAIRING_CODE_REF stage={reg.attrs.get('stage')} ref_len={len(ref)}", flush=True)
                            continue
                        print("PAIRING_CODE_INCOMPLETE_COMPANION_REG", flush=True)
                        return 3

                    identity = SignalKeyPair(
                        private=bytes(meta["identity_private"]),
                        public=bytes(meta["identity_public"]),
                    )
                    finish_result = pairing_code_finish_node(
                        phone_number=args.phone,
                        tag_id=client.queries.next_tag(),
                        pairing_code=request.code,
                        pairing_ephemeral=pairing_ephemeral,
                        identity=identity,
                        ref=ref,
                        primary_identity_public=primary_identity,
                        wrapped_primary_ephemeral_public=wrapped_primary,
                    )
                    meta["adv_secret_key"] = finish_result.adv_secret_key
                    await send_node(websocket, noise, finish_result.node, "pairing-code-finish")
                    sent_finish = True
                    continue

                if find_child(node, "pair-success") is not None:
                    client._web = type("PairingWeb", (), {"send_node": lambda _, reply: send_node(websocket, noise, reply, "pair-device-sign")})()
                    success = await client.finalize_pair_success(node, static_noise=static_noise, meta=meta)
                    JsonCredentialStore(creds_path).save_credentials(client.auth_state.credentials)
                    print(f"PAIRING_CODE_PAIR_SUCCESS {success.update}", flush=True)
                    print(f"SAVED_CREDS {creds_path}", flush=True)
                    return 0
    finally:
        await websocket.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
