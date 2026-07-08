from __future__ import annotations

import argparse
import asyncio
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Awaitable, Callable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import make_socket  # noqa: E402


Probe = Callable[[], Awaitable[object]]


def phone_to_jid(value: str) -> str:
    value = value.strip()
    if "@" in value:
        return value
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 10:
        digits = "91" + digits
    return f"{digits}@s.whatsapp.net"


def generated_profile_picture() -> bytes:
    from PIL import Image

    image = Image.new("RGB", (640, 640), (32, 114, 229))
    out = BytesIO()
    image.save(out, format="JPEG", quality=90)
    return out.getvalue()


async def run_step(label: str, probe: Probe) -> bool:
    try:
        result = await probe()
        print(f"{label}_OK {result!r}", flush=True)
        return True
    except Exception as exc:
        print(f"{label}_ERROR {type(exc).__name__}: {exc}", flush=True)
        return False


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run explicit Phase 5 live mutation checks.")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--apply", action="store_true", help="perform writes against WhatsApp")
    parser.add_argument("--group-jid")
    parser.add_argument("--participant")
    parser.add_argument("--chat-jid")
    parser.add_argument("--profile-name", default="Baileys Python")
    parser.add_argument("--profile-status", default="Testing Baileys Python")
    parser.add_argument("--skip-profile-picture", action="store_true")
    args = parser.parse_args()

    selected = []
    if args.group_jid:
        selected.append("group settings/invite")
    if args.group_jid and args.participant:
        selected.append("group promote/demote")
    if args.chat_jid:
        selected.append("chat archive/mute/pin/star")
    selected.append("profile name/status")
    if not args.skip_profile_picture:
        selected.append("profile picture")

    print("PENDING_MUTATION_OPS " + ", ".join(selected), flush=True)
    if not args.apply:
        print("DRY_RUN set. Add --apply to execute.", flush=True)
        return 0

    client = make_socket(args.creds_path)
    ok = True
    try:
        await client.connect_and_wait(success_timeout=args.timeout)
        me = client.auth_state.credentials.get("me", {}).get("id", "")
        participant_jid = phone_to_jid(args.participant) if args.participant else ""
        chat_jid = phone_to_jid(args.chat_jid) if args.chat_jid else ""

        if args.group_jid:
            async def group_metadata():
                metadata = await client.group_metadata(args.group_jid, timeout=args.timeout)
                participants = [(item.jid, item.admin) for item in metadata.participants]
                return {
                    "id": metadata.id,
                    "subject": metadata.subject,
                    "size": metadata.size,
                    "addressing_mode": metadata.addressing_mode,
                    "participants": participants,
                }

            ok &= await run_step("GROUP_METADATA", group_metadata)
            ok &= await run_step(
                "GROUP_SETTING_ANNOUNCEMENT",
                lambda: client.group_setting_update(args.group_jid, "announcement", timeout=args.timeout),
            )
            ok &= await run_step(
                "GROUP_SETTING_NOT_ANNOUNCEMENT",
                lambda: client.group_setting_update(args.group_jid, "not_announcement", timeout=args.timeout),
            )
            ok &= await run_step("GROUP_REVOKE_INVITE", lambda: client.group_revoke_invite(args.group_jid, timeout=args.timeout))

        if args.group_jid and participant_jid:
            ok &= await run_step(
                "GROUP_PROMOTE",
                lambda: client.group_participants_update(args.group_jid, [participant_jid], "promote", timeout=args.timeout),
            )
            ok &= await run_step(
                "GROUP_DEMOTE",
                lambda: client.group_participants_update(args.group_jid, [participant_jid], "demote", timeout=args.timeout),
            )

        if chat_jid:
            ok &= await run_step("CHAT_ARCHIVE_ON", lambda: client.archive_chat(chat_jid, True, timeout=args.timeout))
            ok &= await run_step("CHAT_ARCHIVE_OFF", lambda: client.archive_chat(chat_jid, False, timeout=args.timeout))
            ok &= await run_step("CHAT_MUTE_ON", lambda: client.mute_chat(chat_jid, int(time.time()) + 3600, timeout=args.timeout))
            ok &= await run_step("CHAT_MUTE_OFF", lambda: client.mute_chat(chat_jid, 0, timeout=args.timeout))
            ok &= await run_step("CHAT_PIN_ON", lambda: client.pin_chat(chat_jid, True, timeout=args.timeout))
            ok &= await run_step("CHAT_PIN_OFF", lambda: client.pin_chat(chat_jid, False, timeout=args.timeout))
            sent = await client.send_message(chat_jid, "Python Baileys star probe", timeout=args.timeout, wait_for_ack=args.timeout)
            key = {"remote_jid": chat_jid, "id": sent.message_id, "from_me": True}
            print(f"CHAT_STAR_TARGET id={sent.message_id} related_response={sent.acked}", flush=True)
            ok &= await run_step("CHAT_STAR_ON", lambda: client.star_message(key, True, timeout=args.timeout))
            ok &= await run_step("CHAT_STAR_OFF", lambda: client.star_message(key, False, timeout=args.timeout))

        ok &= await run_step("PROFILE_NAME", lambda: client.update_profile_name(args.profile_name, timeout=args.timeout))
        ok &= await run_step("PROFILE_STATUS", lambda: client.update_profile_status(args.profile_status, timeout=args.timeout))
        if not args.skip_profile_picture:
            picture = generated_profile_picture()
            ok &= await run_step("PROFILE_PICTURE", lambda: client.update_profile_picture(me, picture, timeout=args.timeout))

        print(f"PHASE5_MUTATION_PROBE_DONE ok={ok}", flush=True)
    finally:
        await client.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
