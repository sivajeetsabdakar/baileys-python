from __future__ import annotations

import asyncio
from pathlib import Path

from baileys import WhatsAppWebClient


async def main() -> None:
    creds_path = Path(__file__).resolve().parents[1] / "auth" / "live_pair_creds.json"
    async with WhatsAppWebClient(creds_path) as client:
        success = await client.wait_for_success(timeout=60)
        print(f"login success: {success.attrs}")


if __name__ == "__main__":
    asyncio.run(main())
