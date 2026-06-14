from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for path in (SRC, SCRIPTS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from baileys.auth_store import save_creds  # noqa: E402
from baileys.media import (  # noqa: E402
    decrypt_media,
    download_media,
    encrypt_media,
    image_message,
    media_conn_node,
    parse_media_conn,
    upload_media,
)
from baileys.message_send import build_proto_message_node  # noqa: E402
from baileys.usync import TagGenerator  # noqa: E402
from send_text_probe import login_socket, query_for_id, send_node, wait_for_success, watch_after_send  # noqa: E402


FALLBACK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKElEQVR4nGNk+M+ABzAxMDBU"
    "gTqG0aMGjB4weMDgAQAAAP//AwCG4QLgJ5I7NwAAAABJRU5ErkJggg=="
)


def probe_image_bytes() -> tuple[bytes, int, int]:
    try:
        from PIL import Image

        image = Image.new("RGB", (32, 32), (32, 114, 229))
        out = BytesIO()
        image.save(out, format="PNG")
        return out.getvalue(), 32, 32
    except Exception:
        return FALLBACK_PNG, 32, 32


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "live_pair_creds.json"))
    parser.add_argument("--to", default="51213374591183@lid")
    parser.add_argument("--caption", default="Python Baileys image test")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--watch", type=int, default=35)
    args = parser.parse_args()

    creds_path = Path(args.creds_path)
    creds = json.loads(creds_path.read_text(encoding="utf-8"))
    tag_gen = TagGenerator()
    image_bytes, width, height = probe_image_bytes()

    websocket, noise = await login_socket(creds)
    try:
        await wait_for_success(websocket, noise, args.timeout)
        media_conn_result = await query_for_id(
            websocket,
            noise,
            media_conn_node(tag_gen.next()),
            "media-conn",
            args.timeout,
        )
        media_conn = parse_media_conn(media_conn_result)
        encrypted = encrypt_media(image_bytes, "image")
        upload = await upload_media(encrypted.encrypted, media_conn, encrypted.file_enc_sha256, "image", timeout=args.timeout)
        downloaded = await download_media(upload, timeout=args.timeout)
        if decrypt_media(downloaded, encrypted.media_key, "image") != image_bytes:
            raise ValueError("downloaded encrypted media did not decrypt to original bytes")
        print(
            f"MEDIA_UPLOAD_OK bytes={len(image_bytes)} enc_bytes={len(encrypted.encrypted)} "
            f"direct_path={upload.direct_path}",
            flush=True,
        )

        message = image_message(
            encrypted,
            upload,
            mimetype="image/png",
            width=width,
            height=height,
            caption=args.caption,
        )
        outbound = build_proto_message_node(creds, args.to, message, message_type="media")
        print(
            f"OUTBOUND_READY id={outbound.message_id} to={args.to} signal_type={outbound.signal_type} "
            f"participants={outbound.participant_jids}",
            flush=True,
        )
        await send_node(websocket, noise, outbound.node, "image-message")
        related = await watch_after_send(websocket, noise, outbound.message_id, args.watch)
        if related:
            save_creds(creds_path, creds)
        print(f"SEND_IMAGE_PROBE_DONE id={outbound.message_id} related_response={related}", flush=True)
    finally:
        await websocket.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
