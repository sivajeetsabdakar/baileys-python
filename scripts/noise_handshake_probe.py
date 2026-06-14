from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import websockets


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.noise import NoiseHandshake, generate_noise_key_pair  # noqa: E402


WA_WEBSOCKET_URL = "wss://web.whatsapp.com/ws/chat"
DEFAULT_ORIGIN = "https://web.whatsapp.com"


async def main() -> int:
    ephemeral = generate_noise_key_pair()
    static_noise = generate_noise_key_pair()
    noise = NoiseHandshake(ephemeral)

    async with websockets.connect(
        WA_WEBSOCKET_URL,
        origin=DEFAULT_ORIGIN,
        open_timeout=20,
        close_timeout=5,
        additional_headers={"User-Agent": "Mozilla/5.0 baileys-python-test"},
    ) as websocket:
        await websocket.send(noise.client_hello_frame())
        response = await asyncio.wait_for(websocket.recv(), timeout=20)
        if isinstance(response, str):
            response = response.encode("latin1")
        if len(response) < 3:
            raise RuntimeError(f"short server frame: {len(response)}")
        size = int.from_bytes(response[:3], "big")
        payload = response[3 : 3 + size]
        if len(payload) != size:
            raise RuntimeError(f"incomplete server frame: expected {size}, got {len(payload)}")

        info = noise.process_server_hello(payload, static_noise)
        print(f"OK serverHello frame size: {size}")
        print(f"OK certificate issuer serial: {info.issuer_serial}")
        print(f"OK intermediate key length: {len(info.intermediate_key)}")
        print(f"OK decrypted static/leaf key length: {len(info.leaf_key)}")
        print(f"OK encrypted client static key length: {len(info.encrypted_static_key)}")
        await websocket.close()

    print("Noise server-hello certificate verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

