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
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
