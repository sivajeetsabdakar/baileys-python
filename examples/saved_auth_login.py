from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from baileys import configure_logging, make_socket


async def run(creds_path: Path, duration: float) -> None:
    configure_logging("INFO")
    client = make_socket(creds_path)
    client.ev.on("connection.update", lambda payload: print(f"connection.update {payload}"))

    try:
        await client.connect_and_wait(start_receive_loop=True)
        print("login success")
        if duration > 0:
            await asyncio.sleep(duration)
    finally:
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Connect with saved auth credentials.")
    parser.add_argument("--creds-path", type=Path, default=Path("auth/product_qr_creds.json"))
    parser.add_argument("--duration", type=float, default=10)
    args = parser.parse_args()

    asyncio.run(run(args.creds_path, args.duration))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
