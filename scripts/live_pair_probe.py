from __future__ import annotations

import argparse
import asyncio
import base64
import hmac
import json
import os
import sys
from pathlib import Path
from typing import Any

import qrcode
import websockets


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.crypto import decompress_if_required, hmac_sign  # noqa: E402
from baileys.generated import WAProto_pb2 as proto  # noqa: E402
from baileys.noise import NoiseHandshake, generate_noise_key_pair  # noqa: E402
from baileys.registration import build_registration_payload  # noqa: E402
from baileys.signal_crypto import sign, verify  # noqa: E402
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node  # noqa: E402


WA_WEBSOCKET_URL = "wss://web.whatsapp.com/ws/chat"
DEFAULT_ORIGIN = "https://web.whatsapp.com"
S_WHATSAPP_NET = "s.whatsapp.net"
COMPANION_PLATFORM_CHROME = "1"

WA_ADV_ACCOUNT_SIG_PREFIX = bytes([6, 0])
WA_ADV_DEVICE_SIG_PREFIX = bytes([6, 1])
WA_ADV_HOSTED_ACCOUNT_SIG_PREFIX = bytes([6, 5])


def log(message: str) -> None:
    print(message, flush=True)


def find_child(node: BinaryNode | None, tag: str) -> BinaryNode | None:
    if node is None or not isinstance(node.content, list):
        return None
    for child in node.content:
        if child.tag == tag:
            return child
    return None


def find_children(node: BinaryNode | None, tag: str) -> list[BinaryNode]:
    if node is None or not isinstance(node.content, list):
        return []
    return [child for child in node.content if child.tag == tag]


def node_content_bytes(node: BinaryNode | None) -> bytes:
    if node is None:
        raise ValueError("missing node")
    if isinstance(node.content, bytes):
        return node.content
    if isinstance(node.content, str):
        return node.content.encode("utf-8")
    raise TypeError(f"expected bytes/text content in {node.tag!r}, got {type(node.content)!r}")


def node_content_text(node: BinaryNode) -> str:
    return node_content_bytes(node).decode("utf-8")


def summarize_node(node: BinaryNode) -> str:
    child_tags: list[str] = []
    if isinstance(node.content, list):
        child_tags = [child.tag for child in node.content]
    return f"tag={node.tag!r} attrs={node.attrs!r} children={child_tags!r}"


def is_server_ping(node: BinaryNode) -> bool:
    return node.tag == "iq" and node.attrs.get("type") == "get" and node.attrs.get("xmlns") == "urn:xmpp:ping"


def server_ping_reply(node: BinaryNode) -> BinaryNode:
    attrs = {"to": S_WHATSAPP_NET, "type": "result"}
    if node.attrs.get("id"):
        attrs["id"] = node.attrs["id"]
    if node.attrs.get("t"):
        attrs["t"] = node.attrs["t"]
    return BinaryNode("iq", attrs)


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


def write_qr_png(payload: str, output_path: Path) -> None:
    qr = qrcode.QRCode(border=2, box_size=10)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def encode_signed_device_identity(account: proto.ADVSignedDeviceIdentity) -> bytes:
    reply_account = proto.ADVSignedDeviceIdentity()
    reply_account.CopyFrom(account)
    reply_account.ClearField("accountSignatureKey")
    return reply_account.SerializeToString()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def save_credentials(
    output_path: Path,
    *,
    static_noise,
    meta: dict[str, Any],
    account: proto.ADVSignedDeviceIdentity,
    update: dict[str, str | None],
) -> None:
    data = {
        "noise_private": b64(static_noise.private),
        "noise_public": b64(static_noise.public),
        "identity_private": b64(bytes(meta["identity_private"])),
        "identity_public": b64(bytes(meta["identity_public"])),
        "signed_pre_key_private": b64(bytes(meta["signed_pre_key_private"])),
        "signed_pre_key_public": b64(bytes(meta["signed_pre_key_public"])),
        "signed_pre_key_signature": b64(bytes(meta["signed_pre_key_signature"])),
        "signed_pre_key_id": int(meta["signed_pre_key_id"]),
        "registration_id": int(meta["registration_id"]),
        "adv_secret_key": str(meta["adv_secret_key"]),
        "account": b64(account.SerializeToString()),
        "me": {
            "id": update["jid"],
            "lid": update["lid"],
            "name": update["business_name"],
        },
        "platform": update["platform"],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def configure_successful_pairing(
    stanza: BinaryNode, meta: dict[str, Any]
) -> tuple[BinaryNode, dict[str, str | None], proto.ADVSignedDeviceIdentity]:
    pair_success_node = find_child(stanza, "pair-success")
    device_identity_node = find_child(pair_success_node, "device-identity")
    platform_node = find_child(pair_success_node, "platform")
    device_node = find_child(pair_success_node, "device")
    business_node = find_child(pair_success_node, "biz")
    if pair_success_node is None or device_identity_node is None or device_node is None:
        raise ValueError(f"missing pair-success/device-identity/device in {stanza!r}")

    signed_hmac = proto.ADVSignedDeviceIdentityHMAC()
    signed_hmac.ParseFromString(node_content_bytes(device_identity_node))
    hmac_prefix = b""
    if signed_hmac.HasField("accountType") and signed_hmac.accountType == proto.ADVEncryptionType.HOSTED:
        hmac_prefix = WA_ADV_HOSTED_ACCOUNT_SIG_PREFIX

    expected_hmac = hmac_sign(hmac_prefix + signed_hmac.details, base64.b64decode(str(meta["adv_secret_key"])))
    if not hmac.compare_digest(signed_hmac.hmac, expected_hmac):
        raise ValueError("invalid pair-success ADV HMAC")

    account = proto.ADVSignedDeviceIdentity()
    account.ParseFromString(signed_hmac.details)

    device_identity = proto.ADVDeviceIdentity()
    device_identity.ParseFromString(account.details)

    account_prefix = (
        WA_ADV_HOSTED_ACCOUNT_SIG_PREFIX
        if device_identity.HasField("deviceType") and device_identity.deviceType == proto.ADVEncryptionType.HOSTED
        else WA_ADV_ACCOUNT_SIG_PREFIX
    )
    account_message = account_prefix + account.details + bytes(meta["identity_public"])
    if not verify(account.accountSignatureKey, account_message, account.accountSignature):
        raise ValueError("invalid pair-success account signature")

    device_message = WA_ADV_DEVICE_SIG_PREFIX + account.details + bytes(meta["identity_public"]) + account.accountSignatureKey
    account.deviceSignature = sign(bytes(meta["identity_private"]), device_message)
    account_enc = encode_signed_device_identity(account)

    reply = BinaryNode(
        "iq",
        {"to": S_WHATSAPP_NET, "type": "result", "id": stanza.attrs["id"]},
        [
            BinaryNode(
                "pair-device-sign",
                {},
                [
                    BinaryNode(
                        "device-identity",
                        {"key-index": str(device_identity.keyIndex)},
                        account_enc,
                    )
                ],
            )
        ],
    )
    update = {
        "jid": device_node.attrs.get("jid"),
        "lid": device_node.attrs.get("lid"),
        "platform": platform_node.attrs.get("name") if platform_node else None,
        "business_name": business_node.attrs.get("name") if business_node else None,
    }
    return reply, update, account


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
    parser.add_argument("--qr-path", default=str(ROOT / "live_pair_qr.png"))
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "live_pair_creds.json"))
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    qr_path = Path(args.qr_path).resolve()
    ephemeral = generate_noise_key_pair()
    static_noise = generate_noise_key_pair()
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
        log(f"OK sent clientFinish registration_id={meta['registration_id']}")

        first_nodes = await receive_nodes(websocket, noise, 25)
        pair_node = first_nodes[0]
        pair_device = find_child(pair_node, "pair-device")
        refs = find_children(pair_device, "ref")
        if pair_node.tag != "iq" or pair_node.attrs.get("type") != "set" or not refs:
            raise ValueError(f"expected pair-device iq with refs, got {pair_node!r}")

        ack = BinaryNode("iq", {"to": S_WHATSAPP_NET, "type": "result", "id": pair_node.attrs["id"]})
        await websocket.send(noise.encode_frame(encode_binary_node(ack)))
        qr_payload = build_pairing_qr_data(
            node_content_text(refs[0]),
            static_noise.public,
            bytes(meta["identity_public"]),
            str(meta["adv_secret_key"]),
        )
        write_qr_png(qr_payload, qr_path)
        log(f"SCAN_QR {qr_path}")
        log(f"QR_PAYLOAD {qr_payload}")
        if not args.no_open:
            os.startfile(qr_path)  # type: ignore[attr-defined]

        deadline = asyncio.get_running_loop().time() + args.timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for phone scan/pair-success")

            for node in await receive_nodes(websocket, noise, min(30, remaining)):
                log(f"RECV {summarize_node(node)}")
                if is_server_ping(node):
                    await websocket.send(noise.encode_frame(encode_binary_node(server_ping_reply(node))))
                    log("OK replied to server ping")
                    continue
                if find_child(node, "pair-success"):
                    reply, update, account = configure_successful_pairing(node, meta)
                    await websocket.send(noise.encode_frame(encode_binary_node(reply)))
                    creds_path = Path(args.creds_path).resolve()
                    save_credentials(creds_path, static_noise=static_noise, meta=meta, account=account, update=update)
                    log(f"PAIR_SUCCESS {update}")
                    log("OK sent pair-device-sign reply")
                    log(f"SAVED_CREDS {creds_path}")
                    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
