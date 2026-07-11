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


def _parse_participants(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _phone_to_jid(value: str) -> str:
    value = value.strip()
    if "@" in value:
        return value
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return f"{digits}@s.whatsapp.net"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run explicit Phase 5 write probes with confirmation guard")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--apply", action="store_true", help="perform writes against WhatsApp")
    parser.add_argument("--presence", choices=["available", "unavailable", "composing", "paused", "recording"])
    parser.add_argument("--presence-to", dest="presence_to", help="optional recipient jid for chatstate presence")
    parser.add_argument("--set-profile-name", help="set this profile name")
    parser.add_argument("--set-profile-status", help="set this status text")
    parser.add_argument("--block-jid", help="jid or phone number for blocklist mutation")
    parser.add_argument("--block-action", choices=["block", "unblock", "cycle"], default="cycle")
    parser.add_argument("--group-jid", help="group jid for participant updates")
    parser.add_argument("--group-action", choices=["add", "remove", "promote", "demote"], help="group participant action")
    parser.add_argument("--group-participants", default="", help="comma separated participant jids")
    parser.add_argument("--send-group-invite-to", help="jid or phone number that should receive a structured group invite")
    args = parser.parse_args()

    pending = []
    if args.presence:
        pending.append(f"presence={args.presence}{f',to={args.presence_to}' if args.presence_to else ''}")
    if args.set_profile_name:
        pending.append("profile_name")
    if args.set_profile_status:
        pending.append("profile_status")
    if args.block_jid:
        pending.append(f"blocklist {args.block_action} {args.block_jid}")
    if args.group_jid and args.group_action and args.group_participants:
        participants = _parse_participants(args.group_participants)
        if participants:
            pending.append(f"group_participants {args.group_action} in {args.group_jid}")
    if args.group_jid and args.send_group_invite_to:
        pending.append(f"group_invite to {args.send_group_invite_to}")

    if not pending:
        print("NO_WRITE_OPS selected. Use --presence, --set-profile-name, --set-profile-status, or group flags.")
        return 0

    print("PENDING_WRITE_OPS " + ", ".join(pending), flush=True)
    if not args.apply:
        print("DRY_RUN set. Add --apply to execute.", flush=True)
        return 0

    client = make_socket(args.creds_path)
    try:
        await client.connect_and_wait(success_timeout=args.timeout)
        if args.presence:
            await client.send_presence_update(args.presence, args.presence_to)
            print(f"PRESENCE_SENT type={args.presence} to={args.presence_to or 'broadcast'}", flush=True)

        if args.set_profile_name:
            await client.update_profile_name(args.set_profile_name)
            print(f"PROFILE_NAME_SET value={args.set_profile_name!r}", flush=True)

        if args.set_profile_status:
            await client.update_profile_status(args.set_profile_status)
            print(f"PROFILE_STATUS_SET value={args.set_profile_status!r}", flush=True)

        if args.block_jid:
            block_jid = _phone_to_jid(args.block_jid)
            def is_listed(items: list[str]) -> bool:
                candidates = {block_jid}
                lid_jid = client.auth_state.credentials.get("pn_lid_mappings", {}).get(block_jid)
                if lid_jid:
                    candidates.add(lid_jid)
                return any(item in candidates for item in items)

            if args.block_action == "cycle":
                before = await client.fetch_blocklist(timeout=args.timeout)
                await client.update_block_status(block_jid, "block", timeout=args.timeout)
                blocked = await client.fetch_blocklist(timeout=args.timeout)
                await client.update_block_status(block_jid, "unblock", timeout=args.timeout)
                after = await client.fetch_blocklist(timeout=args.timeout)
                print(
                    f"BLOCKLIST_CYCLE jid={block_jid} "
                    f"before={is_listed(before)} blocked={is_listed(blocked)} after={is_listed(after)}",
                    flush=True,
                )
            else:
                await client.update_block_status(block_jid, args.block_action, timeout=args.timeout)
                blocklist = await client.fetch_blocklist(timeout=args.timeout)
                print(
                    f"BLOCKLIST_UPDATE jid={block_jid} action={args.block_action} present={is_listed(blocklist)}",
                    flush=True,
                )

        if args.group_jid and args.group_action and args.group_participants:
            participants = _parse_participants(args.group_participants)
            if participants:
                await client.group_participants_update(
                    args.group_jid,
                    participants,
                    args.group_action,
                    timeout=args.timeout,
                )
                print(
                    f"GROUP_PARTICIPANTS_UPDATE jid={args.group_jid} action={args.group_action} "
                    f"count={len(participants)}",
                    flush=True,
                )

        if args.group_jid and args.send_group_invite_to:
            invite_to = _phone_to_jid(args.send_group_invite_to)
            result = await client.send_group_invite(
                invite_to,
                args.group_jid,
                text="Join the test group",
                timeout=args.timeout,
                wait_for_ack=args.timeout,
            )
            print(
                f"GROUP_INVITE_SENT to={invite_to} group={args.group_jid} "
                f"id={result.message_id} related_response={result.acked}",
                flush=True,
            )

        print("PHASE5_WRITE_PROBE_DONE", flush=True)
    finally:
        await client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
