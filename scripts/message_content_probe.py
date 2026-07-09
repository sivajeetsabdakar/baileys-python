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
from baileys.jid import jid_normalized_user  # noqa: E402


def message_key(remote_jid: str, message_id: str, *, participant: str | None = None) -> dict[str, object]:
    key: dict[str, object] = {
        "remote_jid": remote_jid,
        "id": message_id,
        "from_me": True,
    }
    if participant:
        key["participant"] = participant
    return key


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--to", required=True, help="destination jid")
    parser.add_argument("--text", default="Python Baileys content probe")
    parser.add_argument("--edited-text", default="Python Baileys content probe edited")
    parser.add_argument("--reaction", default="\N{THUMBS UP SIGN}")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--watch", type=int, default=35)
    parser.add_argument("--use-usync", action="store_true")
    parser.add_argument("--force-sessions", action="store_true")
    parser.add_argument("--include-phash", action="store_true")
    parser.add_argument("--participant", help="message key participant for group operations")
    parser.add_argument("--include-extra", action="store_true", help="also send location, contact, poll, pin, and unpin")
    args = parser.parse_args()

    client = make_socket(args.creds_path)
    try:
        await client.connect_and_wait(success_timeout=args.timeout)
        own_jid = jid_normalized_user(client.auth_state.credentials["me"]["id"])
        participant = args.participant
        if participant is None and args.to.endswith("@g.us"):
            participant = own_jid

        base = await client.send_message(
            args.to,
            args.text,
            use_usync=args.use_usync or args.to.endswith("@g.us"),
            force_sessions=args.force_sessions,
            include_phash=args.include_phash,
            timeout=args.timeout,
            wait_for_ack=args.watch,
        )
        key = message_key(args.to, base.message_id, participant=participant)
        print(
            f"BASE_SENT id={base.message_id} to={base.remote_jid} "
            f"participants={base.participant_jids} related_response={base.acked}",
            flush=True,
        )

        reaction = await client.send_message(
            args.to,
            {"reaction": {"key": key, "text": args.reaction}},
            use_usync=args.use_usync or args.to.endswith("@g.us"),
            force_sessions=args.force_sessions,
            include_phash=args.include_phash,
            timeout=args.timeout,
            wait_for_ack=args.watch,
        )
        print(
            f"REACTION_SENT id={reaction.message_id} target={base.message_id} "
            f"participants={reaction.participant_jids} related_response={reaction.acked}",
            flush=True,
        )

        edit = await client.send_message(
            args.to,
            {"edit": {"key": key, "text": args.edited_text}},
            use_usync=args.use_usync or args.to.endswith("@g.us"),
            force_sessions=args.force_sessions,
            include_phash=args.include_phash,
            timeout=args.timeout,
            wait_for_ack=args.watch,
        )
        print(
            f"EDIT_SENT id={edit.message_id} target={base.message_id} "
            f"participants={edit.participant_jids} related_response={edit.acked}",
            flush=True,
        )

        reaction_remove = await client.send_message(
            args.to,
            {"reaction": {"key": key, "text": ""}},
            use_usync=args.use_usync or args.to.endswith("@g.us"),
            force_sessions=args.force_sessions,
            include_phash=args.include_phash,
            timeout=args.timeout,
            wait_for_ack=args.watch,
        )
        print(
            f"REACTION_REMOVED id={reaction_remove.message_id} target={base.message_id} "
            f"participants={reaction_remove.participant_jids} related_response={reaction_remove.acked}",
            flush=True,
        )

        delete = await client.send_message(
            args.to,
            {"delete": key},
            use_usync=args.use_usync or args.to.endswith("@g.us"),
            force_sessions=args.force_sessions,
            include_phash=args.include_phash,
            timeout=args.timeout,
            wait_for_ack=args.watch,
        )
        print(
            f"DELETE_SENT id={delete.message_id} target={base.message_id} "
            f"participants={delete.participant_jids} related_response={delete.acked}",
            flush=True,
        )

        if args.include_extra:
            location = await client.send_message(
                args.to,
                {
                    "location": {
                        "latitude": 19.0760,
                        "longitude": 72.8777,
                        "name": "Mumbai",
                        "address": "Mumbai, India",
                    }
                },
                use_usync=args.use_usync or args.to.endswith("@g.us"),
                force_sessions=args.force_sessions,
                include_phash=args.include_phash,
                timeout=args.timeout,
                wait_for_ack=args.watch,
            )
            print(
                f"LOCATION_SENT id={location.message_id} participants={location.participant_jids} "
                f"related_response={location.acked}",
                flush=True,
            )

            contact = await client.send_message(
                args.to,
                {
                    "contact": {
                        "display_name": "Baileys Python Test",
                        "vcard": (
                            "BEGIN:VCARD\nVERSION:3.0\nFN:Baileys Python Test\n"
                            "TEL;type=CELL:+910000000000\nEND:VCARD"
                        ),
                    }
                },
                use_usync=args.use_usync or args.to.endswith("@g.us"),
                force_sessions=args.force_sessions,
                include_phash=args.include_phash,
                timeout=args.timeout,
                wait_for_ack=args.watch,
            )
            print(
                f"CONTACT_SENT id={contact.message_id} participants={contact.participant_jids} "
                f"related_response={contact.acked}",
                flush=True,
            )

            poll = await client.send_message(
                args.to,
                {"poll": {"name": "Baileys Python poll", "values": ["One", "Two"], "selectable_count": 1}},
                use_usync=args.use_usync or args.to.endswith("@g.us"),
                force_sessions=args.force_sessions,
                include_phash=args.include_phash,
                timeout=args.timeout,
                wait_for_ack=args.watch,
            )
            poll_key = message_key(args.to, poll.message_id, participant=participant)
            print(
                f"POLL_SENT id={poll.message_id} participants={poll.participant_jids} "
                f"related_response={poll.acked}",
                flush=True,
            )

            pin = await client.send_message(
                args.to,
                {"pin": {"key": poll_key, "pin": True, "duration": 86400}},
                use_usync=args.use_usync or args.to.endswith("@g.us"),
                force_sessions=args.force_sessions,
                include_phash=args.include_phash,
                timeout=args.timeout,
                wait_for_ack=args.watch,
            )
            print(
                f"PIN_SENT id={pin.message_id} target={poll.message_id} "
                f"participants={pin.participant_jids} related_response={pin.acked}",
                flush=True,
            )

            unpin = await client.send_message(
                args.to,
                {"pin": {"key": poll_key, "pin": False}},
                use_usync=args.use_usync or args.to.endswith("@g.us"),
                force_sessions=args.force_sessions,
                include_phash=args.include_phash,
                timeout=args.timeout,
                wait_for_ack=args.watch,
            )
            print(
                f"UNPIN_SENT id={unpin.message_id} target={poll.message_id} "
                f"participants={unpin.participant_jids} related_response={unpin.acked}",
                flush=True,
            )
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
