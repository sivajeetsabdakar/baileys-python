from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import qrcode


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import make_socket  # noqa: E402


def write_qr_png(payload: str, output_path: Path) -> None:
    qr = qrcode.QRCode(border=2, box_size=10)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


async def wait_for_pair_success(client, timeout: float) -> dict:
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def on_update(payload: dict) -> None:
        if payload.get("pairing") == "success" and not future.done():
            future.set_result(payload)

    ref = client.ev.on("connection.update", on_update)
    try:
        return await asyncio.wait_for(future, timeout=timeout)
    finally:
        client.ev.off("connection.update", ref)


async def main() -> int:
    parser = argparse.ArgumentParser(description="QR pair through the product WhatsAppClient API.")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--qr-path", default=str(ROOT / "product_qr.png"))
    parser.add_argument("--qr-timeout", type=float, default=60)
    parser.add_argument("--scan-timeout", type=float, default=180)
    parser.add_argument("--qr-only", action="store_true", help="generate QR and exit without waiting for phone scan")
    parser.add_argument("--open", action="store_true", help="open the QR PNG after generating it")
    parser.add_argument("--reconnect-check", action="store_true", help="after pair success, reconnect with saved credentials")
    args = parser.parse_args()

    creds_path = Path(args.creds_path).resolve()
    qr_path = Path(args.qr_path).resolve()
    client = make_socket(creds_path)

    def log_update(payload: dict) -> None:
        safe = {key: value for key, value in payload.items() if key != "qr"}
        print(f"EVENT connection.update {safe}", flush=True)

    client.ev.on("connection.update", log_update)
    try:
        request = await client.connect_for_qr_pairing(qr_timeout=args.qr_timeout)
        write_qr_png(request.qr, qr_path)
        print(f"SCAN_QR {qr_path}", flush=True)
        print(f"QR_REFS {len(request.refs)}", flush=True)
        print(f"QR_PAYLOAD {request.qr}", flush=True)
        if args.open:
            os.startfile(qr_path)  # type: ignore[attr-defined]

        if args.qr_only:
            print("QR_ONLY_OK", flush=True)
            return 0

        client.start_receive_loop()
        try:
            update = await wait_for_pair_success(client, args.scan_timeout)
        except asyncio.TimeoutError:
            print(f"PAIR_TIMEOUT seconds={args.scan_timeout}", flush=True)
            return 2
        print(f"PAIR_SUCCESS {update}", flush=True)
    finally:
        await client.close()

    if args.reconnect_check:
        reconnect_client = make_socket(creds_path)
        try:
            success = await reconnect_client.connect_and_wait(success_timeout=60)
            print(f"RECONNECT_SUCCESS {success.attrs}", flush=True)
        finally:
            await reconnect_client.close()

    print(f"SAVED_CREDS {creds_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
