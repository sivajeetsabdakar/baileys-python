from __future__ import annotations

import argparse
import asyncio
import base64
import sys
from io import BytesIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import make_socket  # noqa: E402


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

    image_bytes, width, height = probe_image_bytes()
    client = make_socket(args.creds_path)
    try:
        await client.connect_and_wait(success_timeout=args.timeout)
        result = await client.send_media_message(
            args.to,
            image_bytes,
            "image",
            mimetype="image/png",
            caption=args.caption,
            width=width,
            height=height,
            timeout=args.timeout,
            wait_for_ack=args.watch,
        )
        print(
            f"SEND_IMAGE_PROBE_DONE id={result.send.message_id} to={result.send.remote_jid} "
            f"bytes={len(image_bytes)} direct_path={result.direct_path} related_response={result.send.acked}",
            flush=True,
        )
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
