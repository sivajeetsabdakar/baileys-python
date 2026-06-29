from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import MessageUpsert, make_socket  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Keep a saved-auth product socket online for a timed soak.")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--duration", type=float, default=3600)
    parser.add_argument("--receive-timeout", type=float, default=30)
    parser.add_argument("--keepalive-interval", type=float, default=25)
    args = parser.parse_args()

    creds_path = Path(args.creds_path).resolve()
    if not creds_path.exists():
        print(f"MISSING_CREDS {creds_path}", flush=True)
        return 2

    counters = {
        "connection_update": 0,
        "messages_upsert": 0,
        "messages_update": 0,
        "message_receipt_update": 0,
        "decrypt_error": 0,
        "retry": 0,
        "ack_error": 0,
    }

    client = make_socket(creds_path)

    def on_connection(payload: dict) -> None:
        counters["connection_update"] += 1
        safe = {key: value for key, value in payload.items() if key != "qr"}
        print(f"EVENT connection.update {safe}", flush=True)

    def on_upsert(payload: MessageUpsert) -> None:
        counters["messages_upsert"] += len(payload.messages)
        print(f"EVENT messages.upsert count={len(payload.messages)} type={payload.type}", flush=True)

    client.ev.on("connection.update", on_connection)
    client.ev.on("messages.upsert", on_upsert)
    client.ev.on("messages.update", lambda payload: counters.__setitem__("messages_update", counters["messages_update"] + len(payload)))
    client.ev.on(
        "message-receipt.update",
        lambda payload: counters.__setitem__("message_receipt_update", counters["message_receipt_update"] + len(payload)),
    )
    client.ev.on("messages.decrypt_error", lambda payload: counters.__setitem__("decrypt_error", counters["decrypt_error"] + 1))
    client.ev.on("messages.retry", lambda payload: counters.__setitem__("retry", counters["retry"] + 1))
    client.ev.on("ack.error", lambda payload: counters.__setitem__("ack_error", counters["ack_error"] + 1))

    try:
        await client.connect_and_wait(success_timeout=60)
        client.start_receive_loop(timeout=args.receive_timeout, keepalive_interval=args.keepalive_interval)
        print(f"SOAK_STARTED seconds={args.duration}", flush=True)
        await asyncio.sleep(args.duration)
        print(f"SOAK_OK counters={counters}", flush=True)
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
