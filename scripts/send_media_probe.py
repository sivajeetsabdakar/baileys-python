from __future__ import annotations

import argparse
import asyncio
import base64
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import make_socket  # noqa: E402


FALLBACK_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAKElEQVR4nGNk+M+ABzAxMDBU"
    "gTqG0aMGjB4weMDgAQAAAP//AwCG4QLgJ5I7NwAAAABJRU5ErkJggg=="
)


def generated_image() -> tuple[bytes, str, str | None, int, int]:
    try:
        from PIL import Image

        image = Image.new("RGB", (32, 32), (32, 114, 229))
        out = BytesIO()
        image.save(out, format="PNG")
        return out.getvalue(), "image/png", None, 32, 32
    except Exception:
        return FALLBACK_PNG, "image/png", None, 32, 32


def generated_sticker() -> tuple[bytes, str, str | None, int, int]:
    from PIL import Image

    image = Image.new("RGBA", (512, 512), (220, 40, 70, 255))
    out = BytesIO()
    image.save(out, format="WEBP")
    return out.getvalue(), "image/webp", None, 512, 512


def generated_document() -> tuple[bytes, str, str | None, int, int]:
    data = b"Python Baileys document probe\n"
    return data, "text/plain", "baileys-python-probe.txt", 0, 0


def generated_payload(media_type: str) -> tuple[bytes, str, str | None, int, int]:
    if media_type == "image":
        return generated_image()
    if media_type == "sticker":
        return generated_sticker()
    if media_type == "document":
        return generated_document()
    raise ValueError(f"{media_type} requires --file with a real sample")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--to", required=True, help="destination jid")
    parser.add_argument("--type", choices=["image", "video", "audio", "document", "sticker"], required=True)
    parser.add_argument("--file", type=Path, help="optional media file path")
    parser.add_argument("--mimetype")
    parser.add_argument("--filename")
    parser.add_argument("--caption", default="")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--watch", type=int, default=35)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    if args.file:
        source: bytes | str = str(args.file)
        mimetype = args.mimetype
        filename = args.filename
        width = 0
        height = 0
        byte_count = args.file.stat().st_size
    else:
        data, mimetype, filename, width, height = generated_payload(args.type)
        source = data
        filename = args.filename or filename
        byte_count = len(data)

    client = make_socket(args.creds_path)
    try:
        await client.connect_and_wait(success_timeout=args.timeout)
        result = await client.send_media_message(
            args.to,
            source,
            args.type,
            mimetype=args.mimetype or mimetype,
            filename=filename,
            caption=args.caption,
            width=width,
            height=height,
            timeout=args.timeout,
            wait_for_ack=args.watch,
        )
        print(
            f"SEND_MEDIA_PROBE_DONE type={args.type} id={result.send.message_id} to={result.send.remote_jid} "
            f"bytes={byte_count} direct_path={result.direct_path} media_url={result.media_url} "
            f"related_response={result.send.acked}",
            flush=True,
        )
        if args.download:
            upload = SimpleNamespace(media_url=result.media_url, direct_path=result.direct_path, host="")
            downloaded = await client.download_media_message(upload, media_key=result.media_key, media_type=args.type)
            print(f"DOWNLOAD_OK type={args.type} bytes={len(downloaded)}", flush=True)
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
