from __future__ import annotations

import argparse
import asyncio
import io
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable, Any


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import IQError, MexError, WAMBinaryInfo, WAMEvent, make_socket  # noqa: E402
from baileys.generated import WAProto_pb2 as proto  # noqa: E402
from baileys.socket_nodes import find_child  # noqa: E402
from baileys.wabinary import BinaryNode  # noqa: E402


Probe = Callable[[], Awaitable[object]]


def probe_cover_image() -> bytes:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise RuntimeError("cover-photo probe requires Pillow") from exc

    output = io.BytesIO()
    image = Image.new("RGB", (1200, 675), (248, 248, 240))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 1120, 595), outline=(18, 95, 91), width=18)
    draw.rectangle((150, 170, 1050, 505), fill=(66, 160, 142))
    draw.text((190, 300), "Baileys Python Cover Probe", fill=(20, 20, 20))
    image.save(output, format="JPEG", quality=92)
    return output.getvalue()


async def run_step(label: str, probe: Probe, *, allow_limits: bool = False) -> bool:
    try:
        result = await probe()
    except (IQError, MexError, TimeoutError, asyncio.TimeoutError) as exc:
        print(f"{label}_ACCOUNT_OR_SERVER_LIMIT {type(exc).__name__}: {exc}", flush=True)
        return allow_limits
    except Exception as exc:
        print(f"{label}_ERROR {type(exc).__name__}: {exc}", flush=True)
        return False
    print(f"{label}_OK {result!r}", flush=True)
    return True


def node_summary(node: BinaryNode | None) -> dict[str, Any] | None:
    if node is None:
        return None
    child_tags = [child.tag for child in node.content if isinstance(child, BinaryNode)] if isinstance(node.content, list) else []
    return {"tag": node.tag, "attrs": dict(node.attrs), "children": child_tags}


def count_children(node: BinaryNode | None, tag: str) -> int:
    return sum(1 for child in node.content or [] if isinstance(child, BinaryNode) and child.tag == tag) if node and isinstance(node.content, list) else 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run remaining Phase 7 live checks.")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--business-jid", help="Business JID to use for business/catalog reads. Defaults to own JID.")
    parser.add_argument("--peer-jid", help="Peer JID used for privacy-token probes.")
    parser.add_argument("--community-jid", help="Community JID to fetch metadata for.")
    parser.add_argument("--newsletter-kind", default="jid")
    parser.add_argument("--newsletter-key")
    parser.add_argument("--order-id")
    parser.add_argument("--order-token")
    parser.add_argument("--apply-cover-photo", action="store_true")
    parser.add_argument("--force-cover-overwrite", action="store_true")
    parser.add_argument("--apply-newsletter-create", action="store_true")
    parser.add_argument("--send-peer-data", action="store_true")
    parser.add_argument("--send-wam", action="store_true")
    parser.add_argument("--allow-limits", action="store_true")
    args = parser.parse_args()

    creds_path = Path(args.creds_path)
    if not creds_path.exists():
        print(f"MISSING_CREDS {creds_path}", flush=True)
        return 2

    client = make_socket(creds_path)
    updates: list[dict[str, object]] = []
    client.ev.on("connection.update", lambda payload: updates.append({key: value for key, value in payload.items() if key != "qr"}))

    try:
        await client.connect_and_wait(success_timeout=args.timeout)
        ok = True
        own_jid = client.auth_state.credentials.get("me", {}).get("id")
        business_jid = args.business_jid or own_jid

        async def collections_step() -> object:
            node = await client.get_collections(business_jid, timeout=args.timeout)
            collections = find_child(node, "collections")
            return {"summary": node_summary(collections), "collections": count_children(collections, "collection")}

        ok = await run_step("COLLECTIONS", collections_step, allow_limits=args.allow_limits) and ok

        if args.order_id and args.order_token:
            async def order_step() -> object:
                node = await client.get_order_details(args.order_id, args.order_token, timeout=args.timeout)
                return node_summary(find_child(node, "order") or node)

            ok = await run_step("ORDER_DETAILS", order_step, allow_limits=args.allow_limits) and ok
        else:
            print("ORDER_DETAILS_SKIPPED missing --order-id/--order-token", flush=True)

        if args.apply_cover_photo:
            async def cover_step() -> object:
                profile = await client.get_business_profile(business_jid, timeout=args.timeout)
                existing = find_child(profile.raw if profile else None, "cover_photo")
                if existing is not None and not args.force_cover_overwrite:
                    raise RuntimeError("profile already has cover_photo; rerun with --force-cover-overwrite to replace it")
                fbid = None
                try:
                    fbid = await client.update_cover_photo(probe_cover_image(), timeout=args.timeout)
                    removed = await client.remove_cover_photo(fbid, timeout=args.timeout)
                    return {"updated_fbid": fbid, "removed": node_summary(removed)}
                finally:
                    if fbid:
                        try:
                            await client.remove_cover_photo(fbid, timeout=args.timeout)
                        except Exception:
                            pass

            ok = await run_step("COVER_PHOTO", cover_step, allow_limits=args.allow_limits) and ok
        else:
            print("COVER_PHOTO_SKIPPED pass --apply-cover-photo to run temporary update/remove", flush=True)

        ok = await run_step("BOT_LIST", lambda: client.get_bot_list_v2(timeout=args.timeout), allow_limits=args.allow_limits) and ok

        if args.peer_jid:
            ok = await run_step(
                "PRIVACY_TOKENS",
                lambda: client.issue_privacy_tokens([args.peer_jid], timestamp=int(time.time()), timeout=args.timeout),
                allow_limits=args.allow_limits,
            ) and ok
        else:
            print("PRIVACY_TOKENS_SKIPPED missing --peer-jid", flush=True)

        if args.send_peer_data:
            async def peer_data_step() -> object:
                request = proto.Message.PeerDataOperationRequestMessage()
                request.peerDataOperationRequestType = 1
                result = await client.send_peer_data_operation_message(request, wait_for_ack=15, timeout=args.timeout)
                return {"message_id": result.message_id, "remote_jid": result.remote_jid, "acked": result.acked}

            ok = await run_step("PEER_DATA_OPERATION", peer_data_step, allow_limits=args.allow_limits) and ok
        else:
            print("PEER_DATA_OPERATION_SKIPPED pass --send-peer-data to send self peer-data request", flush=True)

        if args.newsletter_key:
            ok = await run_step(
                "NEWSLETTER_METADATA",
                lambda: client.newsletter_metadata(args.newsletter_kind, args.newsletter_key, timeout=args.timeout),
                allow_limits=args.allow_limits,
            ) and ok
        else:
            print("NEWSLETTER_METADATA_SKIPPED missing --newsletter-key", flush=True)

        if args.apply_newsletter_create:
            async def newsletter_create_step() -> object:
                newsletter = await client.newsletter_create(f"Baileys Python Probe {client.queries.next_tag()}", "Temporary probe", timeout=args.timeout)
                jid = getattr(newsletter, "id", None)
                deleted = None
                if jid:
                    deleted = await client.newsletter_delete(jid, timeout=args.timeout)
                return {"jid": jid, "deleted": deleted}

            ok = await run_step("NEWSLETTER_CREATE_DELETE", newsletter_create_step, allow_limits=args.allow_limits) and ok
        else:
            print("NEWSLETTER_CREATE_DELETE_SKIPPED pass --apply-newsletter-create to run create/delete", flush=True)

        if args.community_jid:
            async def community_step() -> object:
                metadata = await client.community_metadata(args.community_jid, timeout=args.timeout)
                return {"id": metadata.id, "subject": metadata.subject, "participants": len(metadata.participants)}

            ok = await run_step("COMMUNITY_METADATA", community_step, allow_limits=args.allow_limits) and ok
        else:
            print("COMMUNITY_METADATA_SKIPPED missing --community-jid", flush=True)

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
                allow_limits=args.allow_limits,
            ) and ok
        else:
            print("WAM_STATS_SKIPPED pass --send-wam to send w:stats probe", flush=True)

        print(f"CONNECTION_UPDATES {updates}", flush=True)
        print(f"PHASE7_REMAINING_PROBE_DONE ok={ok}", flush=True)
        return 0 if ok or args.allow_limits else 1
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
