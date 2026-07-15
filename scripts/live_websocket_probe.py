from __future__ import annotations

import asyncio

import websockets


WA_WEBSOCKET_URL = "wss://web.whatsapp.com/ws/chat"
DEFAULT_ORIGIN = "https://web.whatsapp.com"


async def main() -> int:
    async with websockets.connect(
        WA_WEBSOCKET_URL,
        origin=DEFAULT_ORIGIN,
        open_timeout=20,
        close_timeout=5,
        additional_headers={
            "User-Agent": "Mozilla/5.0 baileys-python",
        },
    ) as websocket:
        print(f"connected {websocket.remote_address}")
        await websocket.close()
        print("closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
