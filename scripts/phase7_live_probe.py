from __future__ import annotations

import argparse
import asyncio
import io
import sys
from pathlib import Path
from typing import Awaitable, Callable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import IQError, MexError, WAMBinaryInfo, WAMEvent, make_socket  # noqa: E402


Probe = Callable[[], Awaitable[object]]


def probe_product_image() -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("catalog write probe requires Pillow") from exc

    output = io.BytesIO()
    image = Image.new("RGB", (640, 640), (245, 245, 235))
    draw = ImageDraw.Draw(image)
    draw.rectangle((70, 70, 570, 570), outline=(28, 94, 86), width=12)
    draw.ellipse((190, 150, 450, 410), fill=(67, 160, 142))
    draw.text((150, 475), "Baileys Python Probe", fill=(20, 20, 20))
    image.save(output, format="JPEG", quality=92)
    return output.getvalue()


async def run_step(label: str, probe: Probe) -> bool:
    try:
        result = await probe()
    except (IQError, MexError, TimeoutError, asyncio.TimeoutError) as exc:
        print(f"{label}_ACCOUNT_OR_SERVER_LIMIT {type(exc).__name__}: {exc}", flush=True)
        return False
    except Exception as exc:
        print(f"{label}_ERROR {type(exc).__name__}: {exc}", flush=True)
        return False
    print(f"{label}_OK {result!r}", flush=True)
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only Phase 7 product API probes.")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument("--business-jid", help="Business JID to use for catalog reads. Defaults to own JID.")
    parser.add_argument("--newsletter-kind", default="jid", help="Newsletter metadata key type, such as jid, invite, or name.")
    parser.add_argument("--newsletter-key", help="Newsletter metadata key to fetch.")
    parser.add_argument("--community-jid", help="Community JID to fetch metadata for.")
    parser.add_argument("--skip-catalog", action="store_true")
    parser.add_argument("--skip-mex", action="store_true")
    parser.add_argument("--send-wam", action="store_true", help="Send a minimal WAM stats buffer through w:stats.")
    parser.add_argument("--apply-catalog-write", action="store_true", help="Create and delete a temporary catalog product.")
    parser.add_argument("--force-generated-catalog-image", action="store_true", help="Use a freshly generated upload for catalog writes.")
    parser.add_argument("--catalog-update-product-id", help="Temporarily rename an existing catalog product, then revert it.")
    parser.add_argument("--allow-limits", action="store_true", help="Exit successfully when account/server limits are reported.")
    args = parser.parse_args()

    creds_path = Path(args.creds_path)
    if not creds_path.exists():
        print(f"MISSING_CREDS {creds_path}", flush=True)
        return 2

    client = make_socket(creds_path)
    updates = []
    client.ev.on("connection.update", lambda payload: updates.append({key: value for key, value in payload.items() if key != "qr"}))

    try:
        await client.connect_and_wait(success_timeout=args.timeout)
        ok = True

        if not args.skip_catalog:
            async def business_profile_step() -> object:
                jid = args.business_jid or client.auth_state.credentials.get("me", {}).get("id")
                profile = await client.get_business_profile(jid, timeout=args.timeout)
                if profile is None:
                    return None
                return {
                    "wid": profile.wid,
                    "description": profile.description,
                    "category": profile.category,
                    "websites": len(profile.websites),
                }

            ok = await run_step("BUSINESS_PROFILE", business_profile_step) and ok

            async def catalog_step() -> object:
                catalog = await client.get_catalog(args.business_jid, limit=5, timeout=args.timeout)
                return {"products": len(catalog.products), "next_cursor": catalog.next_cursor}

            ok = await run_step("CATALOG", catalog_step) and ok

            if args.apply_catalog_write:
                async def catalog_write_step() -> object:
                    product_id = None
                    product_name = f"Baileys Python Probe {client.queries.next_tag()}"
                    image_url = None
                    if not args.force_generated_catalog_image:
                        catalog_before_create = await client.get_catalog(args.business_jid, limit=5, timeout=args.timeout)
                        image_url = next(
                            (
                                product.image_urls.get("original") or product.image_urls.get("requested")
                                for product in catalog_before_create.products
                                if product.image_urls
                            ),
                            None,
                        )
                    images = [{"url": image_url}] if image_url else [probe_product_image()]
                    try:
                        created = await client.product_create(
                            {
                                "name": product_name,
                                "description": "Temporary product for protocol verification. Safe to delete.",
                                "currency": "INR",
                                "price": "10000",
                                "retailerId": "baileys-python-probe",
                                "originCountryCode": None,
                                "isHidden": True,
                                "images": images,
                            },
                            timeout=args.timeout,
                        )
                        product_id = getattr(created, "id", None)
                        catalog_after_create = await client.get_catalog(args.business_jid, limit=5, timeout=args.timeout)
                        deleted = None
                        if product_id:
                            deleted = await client.product_delete([product_id], timeout=args.timeout)
                        return {
                            "created_id": product_id,
                            "created_name": getattr(created, "name", None),
                            "image_source": "existing_catalog" if image_url else "generated_upload",
                            "catalog_products_after_create": len(catalog_after_create.products),
                            "deleted": deleted,
                        }
                    finally:
                        if product_id:
                            try:
                                await client.product_delete([product_id], timeout=args.timeout)
                            except Exception:
                                pass

                ok = await run_step("CATALOG_WRITE", catalog_write_step) and ok

            if args.catalog_update_product_id:
                async def catalog_update_step() -> object:
                    catalog = await client.get_catalog(args.business_jid, limit=25, timeout=args.timeout)
                    product = next((item for item in catalog.products if item.id == args.catalog_update_product_id), None)
                    if product is None:
                        raise ValueError(f"catalog product not found: {args.catalog_update_product_id}")
                    image_url = product.image_urls.get("original") or product.image_urls.get("requested")
                    base_payload = {
                        "name": product.name or "Catalog Probe Product",
                        "description": product.description or product.name or "Catalog Probe Product",
                        "currency": product.currency or "INR",
                        "price": product.price or 0,
                        "isHidden": product.hidden if product.hidden is not None else False,
                    }
                    if image_url:
                        base_payload["images"] = [{"url": image_url}]

                    updated = None
                    try:
                        updated = await client.product_update(
                            args.catalog_update_product_id,
                            {**base_payload, "name": f"{base_payload['name']} Probe"},
                            timeout=args.timeout,
                        )
                        reverted = await client.product_update(args.catalog_update_product_id, base_payload, timeout=args.timeout)
                        return {
                            "product_id": args.catalog_update_product_id,
                            "updated_name": getattr(updated, "name", None),
                            "reverted_name": getattr(reverted, "name", None),
                        }
                    finally:
                        if updated is not None:
                            try:
                                await client.product_update(args.catalog_update_product_id, base_payload, timeout=args.timeout)
                            except Exception:
                                pass

                ok = await run_step("CATALOG_UPDATE", catalog_update_step) and ok

        if not args.skip_mex:
            ok = await run_step("REACHOUT_TIMELOCK", lambda: client.fetch_account_reachout_timelock(timeout=args.timeout)) and ok
            ok = await run_step("MESSAGE_CAPPING", lambda: client.fetch_message_capping_info(timeout=args.timeout)) and ok

        if args.newsletter_key:
            ok = await run_step(
                "NEWSLETTER_METADATA",
                lambda: client.newsletter_metadata(args.newsletter_kind, args.newsletter_key, timeout=args.timeout),
            ) and ok

        if args.community_jid:
            async def community_step() -> object:
                metadata = await client.community_metadata(args.community_jid, timeout=args.timeout)
                return {"id": metadata.id, "subject": metadata.subject, "participants": len(metadata.participants)}

            ok = await run_step("COMMUNITY_METADATA", community_step) and ok

        if args.send_wam:
            ok = await run_step(
                "WAM_STATS",
                lambda: client.send_wam(
                    WAMBinaryInfo(
                        sequence=1,
                        events=[
                            WAMEvent(
                                "WamDroppedEvent",
                                props={"droppedEventCode": 1, "droppedEventCount": 0, "isFromWamsys": False},
                                globals={"sequenceNumber": 1},
                            )
                        ],
                    ),
                    timeout=args.timeout,
                ),
            ) and ok

        print(f"CONNECTION_UPDATES {updates}", flush=True)
        print(f"PHASE7_LIVE_PROBE_DONE ok={ok}", flush=True)
        return 0 if ok or args.allow_limits else 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
