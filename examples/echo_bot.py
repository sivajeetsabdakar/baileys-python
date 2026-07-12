from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from baileys import MessageUpsert, configure_logging, make_socket


def first_text(upsert: MessageUpsert) -> tuple[str, str] | None:
    if not upsert.messages:
        return None
    item = upsert.messages[0]
    if item.message is None or item.key.from_me:
        return None
    text = None
    if item.message.conversation:
        text = item.message.conversation
    elif item.message.HasField("extendedTextMessage"):
        text = item.message.extendedTextMessage.text
    if not text or not item.key.remote_jid:
        return None
    return item.key.remote_jid, text


async def run(creds_path: Path, duration: float) -> None:
    configure_logging("INFO")
    client = make_socket(creds_path)

    async def on_message(upsert: MessageUpsert) -> None:
        parsed = first_text(upsert)
        if parsed is None:
            return
        remote_jid, text = parsed
        if text.strip().lower() == "!ping":
            await client.send_message(remote_jid, {"text": "pong"})

    client.ev.on("messages.upsert", on_message)

    try:
        await client.connect_and_wait(start_receive_loop=True)
        print("echo bot ready")
        await asyncio.sleep(duration)
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Reply with pong when an inbound message says !ping.")
    parser.add_argument("--creds-path", type=Path, default=Path("auth/product_qr_creds.json"))
    parser.add_argument("--duration", type=float, default=300)
    args = parser.parse_args()

    asyncio.run(run(args.creds_path, args.duration))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
