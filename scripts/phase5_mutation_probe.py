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


def matching_participant(metadata: object, jid: str) -> object | None:
    for item in getattr(metadata, "participants", []):
        if item.jid == jid or item.phone_number == jid:
            return item
    return None


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


async def participant_step(label: str, probe: Probe) -> bool:
    async def checked() -> object:
        result = await probe()
        if not result:
            raise RuntimeError("empty participant update result")
        failures = [item for item in result if getattr(item, "status", "200") != "200"]
        if failures:
            statuses = ", ".join(f"{item.jid}:{item.status}" for item in failures)
            raise RuntimeError(f"participant update failed: {statuses}")
        return result

    return await run_step(label, checked)


async def add_or_invite_step(label: str, probe: Probe) -> bool:
    async def checked() -> object:
        result = await probe()
        updates = result.get("results", []) if isinstance(result, dict) else result
        if updates:
            failures = [item for item in updates if getattr(item, "status", "200") != "200"]
            if failures:
                statuses = ", ".join(f"{item.jid}:{item.status}" for item in failures)
                raise RuntimeError(f"participant update failed: {statuses}")
        return result

    return await run_step(label, checked)


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
    parser.add_argument("--include-group-details", action="store_true", help="update and revert group subject/description")
    parser.add_argument("--group-add-remove", action="store_true", help="add and remove a participant from --group-jid")
    parser.add_argument("--add-remove-participant", help="participant used only for group add/remove checks")
    parser.add_argument("--restore-after-remove", action="store_true", help="add the add/remove participant back after remove")
    parser.add_argument("--create-leave-group", action="store_true", help="create a temporary group and leave it")
    parser.add_argument("--create-subject", default="Baileys Python Probe")
    parser.add_argument("--skip-profile", action="store_true")
    parser.add_argument("--skip-profile-picture", action="store_true")
    args = parser.parse_args()

    selected = []
    if args.group_jid:
        selected.append("group settings/invite")
    if args.group_jid and args.include_group_details:
        selected.append("group subject/description")
    if args.group_jid and args.participant:
        selected.append("group promote/demote")
    if args.group_jid and (args.add_remove_participant or args.participant) and args.group_add_remove:
        selected.append("group add/remove")
    if args.create_leave_group:
        selected.append("temporary group create/leave")
    if args.chat_jid:
        selected.append("chat archive/mute/pin/star")
    if not args.skip_profile:
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
        add_remove_participant_jid = phone_to_jid(args.add_remove_participant) if args.add_remove_participant else participant_jid
        chat_jid = phone_to_jid(args.chat_jid) if args.chat_jid else ""

        if args.group_jid:
            async def group_metadata():
                metadata = await client.group_metadata(args.group_jid, timeout=args.timeout)
                participants = [(item.jid, item.admin, item.phone_number) for item in metadata.participants]
                return {
                    "id": metadata.id,
                    "subject": metadata.subject,
                    "size": metadata.size,
                    "addressing_mode": metadata.addressing_mode,
                    "participants": participants,
                }

            ok &= await run_step("GROUP_METADATA", group_metadata)
            metadata = await client.group_metadata(args.group_jid, timeout=args.timeout)
            ok &= await run_step(
                "GROUP_SETTING_ANNOUNCEMENT",
                lambda: client.group_setting_update(args.group_jid, "announcement", timeout=args.timeout),
            )
            ok &= await run_step(
                "GROUP_SETTING_NOT_ANNOUNCEMENT",
                lambda: client.group_setting_update(args.group_jid, "not_announcement", timeout=args.timeout),
            )
            ok &= await run_step("GROUP_REVOKE_INVITE", lambda: client.group_revoke_invite(args.group_jid, timeout=args.timeout))

            if args.include_group_details:
                original_subject = metadata.subject or "Baileys Python Test"
                original_desc = metadata.desc
                probe_subject = f"{original_subject} probe"
                probe_desc = f"Baileys Python description probe {int(time.time())}"
                ok &= await run_step(
                    "GROUP_SUBJECT_SET",
                    lambda: client.group_update_subject(args.group_jid, probe_subject, timeout=args.timeout),
                )
                ok &= await run_step(
                    "GROUP_SUBJECT_REVERT",
                    lambda: client.group_update_subject(args.group_jid, original_subject, timeout=args.timeout),
                )
                ok &= await run_step(
                    "GROUP_DESCRIPTION_SET",
                    lambda: client.group_update_description(args.group_jid, probe_desc, timeout=args.timeout),
                )
                ok &= await run_step(
                    "GROUP_DESCRIPTION_REVERT",
                    lambda: client.group_update_description(args.group_jid, original_desc, timeout=args.timeout),
                )

        if args.group_jid and participant_jid:
            ok &= await participant_step(
                "GROUP_PROMOTE",
                lambda: client.group_participants_update(args.group_jid, [participant_jid], "promote", timeout=args.timeout),
            )
            ok &= await participant_step(
                "GROUP_DEMOTE",
                lambda: client.group_participants_update(args.group_jid, [participant_jid], "demote", timeout=args.timeout),
            )

        if args.group_jid and args.group_add_remove and add_remove_participant_jid:
            metadata = await client.group_metadata(args.group_jid, timeout=args.timeout)
            member = matching_participant(metadata, add_remove_participant_jid)
            mutation_jid = member.jid if member is not None else add_remove_participant_jid
            if member is not None:
                ok &= await participant_step(
                    "GROUP_REMOVE",
                    lambda: client.group_participants_update(args.group_jid, [mutation_jid], "remove", timeout=args.timeout),
                )
                ok &= await add_or_invite_step(
                    "GROUP_ADD_RESTORE",
                    lambda: client.group_participants_update_or_invite(
                        args.group_jid,
                        [mutation_jid],
                        "add",
                        timeout=args.timeout,
                        wait_for_ack=args.timeout,
                    ),
                )
            else:
                ok &= await add_or_invite_step(
                    "GROUP_ADD",
                    lambda: client.group_participants_update_or_invite(
                        args.group_jid,
                        [add_remove_participant_jid],
                        "add",
                        timeout=args.timeout,
                        wait_for_ack=args.timeout,
                    ),
                )
                ok &= await participant_step(
                    "GROUP_REMOVE",
                    lambda: client.group_participants_update(args.group_jid, [add_remove_participant_jid], "remove", timeout=args.timeout),
                )
                if args.restore_after_remove:
                    ok &= await add_or_invite_step(
                        "GROUP_ADD_RESTORE",
                        lambda: client.group_participants_update_or_invite(
                            args.group_jid,
                            [add_remove_participant_jid],
                            "add",
                            timeout=args.timeout,
                            wait_for_ack=args.timeout,
                        ),
                    )

        if args.create_leave_group:
            create_participants = [participant_jid] if participant_jid else []

            async def create_and_leave():
                metadata = await client.group_create(args.create_subject, create_participants, timeout=args.timeout)
                if args.include_group_details:
                    await client.group_update_subject(metadata.id, f"{args.create_subject} Updated", timeout=args.timeout)
                    await client.group_update_description(
                        metadata.id,
                        f"Baileys Python temporary group probe {int(time.time())}",
                        timeout=args.timeout,
                    )
                if args.group_add_remove and participant_jid:
                    await client.group_participants_update(metadata.id, [participant_jid], "remove", timeout=args.timeout)
                    await client.group_participants_update(metadata.id, [participant_jid], "add", timeout=args.timeout)
                    await client.group_participants_update(metadata.id, [participant_jid], "remove", timeout=args.timeout)
                await client.group_leave(metadata.id, timeout=args.timeout)
                return {"id": metadata.id, "subject": metadata.subject, "size": metadata.size}

            ok &= await run_step("GROUP_CREATE_LEAVE", create_and_leave)

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

        if not args.skip_profile:
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
