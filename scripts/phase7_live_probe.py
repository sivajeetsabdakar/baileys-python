from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Awaitable, Callable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import IQError, MexError, WAMBinaryInfo, WAMEvent, make_socket  # noqa: E402


Probe = Callable[[], Awaitable[object]]


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
            async def catalog_step() -> object:
                catalog = await client.get_catalog(args.business_jid, limit=5, timeout=args.timeout)
                return {"products": len(catalog.products), "next_cursor": catalog.next_cursor}

            ok = await run_step("CATALOG", catalog_step) and ok

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
