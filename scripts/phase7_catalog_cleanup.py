from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import make_socket  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser(description="Delete temporary catalog probe products by name prefix.")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--business-jid")
    parser.add_argument("--prefix", default="Baileys Python Probe")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    client = make_socket(Path(args.creds_path))
    try:
        await client.connect_and_wait(success_timeout=args.timeout)
        catalog = await client.get_catalog(args.business_jid, limit=50, timeout=args.timeout)
        matches = [product for product in catalog.products if product.id and (product.name or "").startswith(args.prefix)]
        print("CATALOG_PRODUCTS", [(product.id, product.name) for product in catalog.products], flush=True)
        print("MATCHED_PRODUCTS", [(product.id, product.name) for product in matches], flush=True)
        if matches and not args.dry_run:
            deleted = await client.product_delete([product.id for product in matches if product.id], timeout=args.timeout)
            print(f"DELETE_OK {deleted}", flush=True)
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
