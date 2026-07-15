from __future__ import annotations

import argparse
import asyncio
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
from baileys.pairing_code import (  # noqa: E402
    generate_pairing_code,
    pairing_code_finish_node,
    pairing_code_hello_node,
    phone_jid,
)
from baileys.registration import build_registration_payload  # noqa: E402
from baileys.signal_crypto import SignalKeyPair  # noqa: E402
from baileys.socket_nodes import find_child, node_content_bytes, server_ping_reply, summarize_node  # noqa: E402
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node  # noqa: E402
from live_pair_probe import configure_successful_pairing, save_credentials  # noqa: E402


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


def infer_phone_from_creds(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    me = data.get("me") or {}
    jid = me.get("id") or me.get("lid")
    if not jid:
        raise ValueError(f"cannot infer phone from {path}")
    return jid


def find_children(node: BinaryNode | None, tag: str) -> list[BinaryNode]:
    if node is None or not isinstance(node.content, list):
        return []
    return [child for child in node.content if child.tag == tag]


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


def is_server_ping(node: BinaryNode) -> bool:
    return node.tag == "iq" and node.attrs.get("type") == "get" and node.attrs.get("xmlns") == "urn:xmpp:ping"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phone", help="Phone number with country code, digits or WhatsApp JID.")
    parser.add_argument("--infer-phone-creds", default=str(ROOT / "auth" / "live_pair_creds.json"))
    parser.add_argument("--custom-code")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "pairing_code_creds.json"))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--code-only-timeout", type=int, default=0)
    args = parser.parse_args()

    phone_number = args.phone or infer_phone_from_creds(Path(args.infer_phone_creds))
    pairing_code = generate_pairing_code(args.custom_code)
    tag_gen = TagGenerator()
    ephemeral = generate_noise_key_pair()
    static_noise = generate_noise_key_pair()
    pairing_ephemeral = generate_noise_key_pair()
    noise = NoiseHandshake(ephemeral)

    async with websockets.connect(
        WA_WEBSOCKET_URL,
        origin=DEFAULT_ORIGIN,
        open_timeout=20,
        close_timeout=5,
        ping_interval=None,
        additional_headers={"User-Agent": "Mozilla/5.0 baileys-python"},
    ) as websocket:
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
        print(f"OK sent clientFinish registration_id={meta['registration_id']}", flush=True)

        initial = await receive_nodes(websocket, noise, 25)
        for node in initial:
            print(f"RECV {summarize_node(node)}", flush=True)
            pair_device = find_child(node, "pair-device")
            refs = find_children(pair_device, "ref")
            if node.tag == "iq" and node.attrs.get("type") == "set" and refs:
                await send_node(
                    websocket,
                    noise,
                    BinaryNode("iq", {"to": S_WHATSAPP_NET, "type": "result", "id": node.attrs["id"]}),
                    "pair-device-ack",
                )

        hello = pairing_code_hello_node(
            phone_number=phone_number,
            tag_id=tag_gen.next(),
            pairing_code=pairing_code,
            companion_ephemeral_public=pairing_ephemeral.public,
            noise_public=static_noise.public,
        )
        await send_node(websocket, noise, hello, "pairing-code-hello")
        print(f"PAIRING_CODE_READY code={pairing_code} jid={phone_jid(phone_number)}", flush=True)
        if args.code_only_timeout:
            print(f"CODE_ONLY_WAIT seconds={args.code_only_timeout}", flush=True)

        deadline = asyncio.get_running_loop().time() + (args.code_only_timeout or args.timeout)
        sent_finish = False
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                if args.code_only_timeout:
                    print("PAIRING_CODE_REQUEST_ONLY_OK", flush=True)
                    return 0
                raise TimeoutError("timed out waiting for pairing-code companion response/pair-success")

            try:
                nodes = await receive_nodes(websocket, noise, min(30, remaining))
            except TimeoutError:
                continue
            for node in nodes:
                print(f"RECV {summarize_node(node)}", flush=True)
                if is_server_ping(node):
                    await send_node(websocket, noise, server_ping_reply(node), "server-ping-reply")
                    continue

                reg = find_child(node, "link_code_companion_reg")
                if reg is not None and not sent_finish:
                    ref = node_content_bytes(find_child(reg, "link_code_pairing_ref"))
                    primary_identity = node_content_bytes(find_child(reg, "primary_identity_pub"))
                    wrapped_primary = node_content_bytes(
                        find_child(reg, "link_code_pairing_wrapped_primary_ephemeral_pub")
                    )
                    if ref is None or primary_identity is None or wrapped_primary is None:
                        if ref is not None:
                            print(
                                f"PAIRING_CODE_REF stage={reg.attrs.get('stage')} ref_len={len(ref)}",
                                flush=True,
                            )
                            continue
                        raise ValueError(f"incomplete link_code_companion_reg: {node!r}")
                    identity = SignalKeyPair(private=bytes(meta["identity_private"]), public=bytes(meta["identity_public"]))
                    finish_result = pairing_code_finish_node(
                        phone_number=phone_number,
                        tag_id=tag_gen.next(),
                        pairing_code=pairing_code,
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

                if find_child(node, "pair-success"):
                    reply, update, account = configure_successful_pairing(node, meta)
                    await send_node(websocket, noise, reply, "pair-device-sign")
                    creds_path = Path(args.creds_path).resolve()
                    save_credentials(creds_path, static_noise=static_noise, meta=meta, account=account, update=update)
                    print(f"PAIRING_CODE_PAIR_SUCCESS {update}", flush=True)
                    print(f"SAVED_CREDS {creds_path}", flush=True)
                    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
