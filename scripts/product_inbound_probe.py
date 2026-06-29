from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import MessageUpsert, make_socket  # noqa: E402


def message_summary(upsert: MessageUpsert) -> str:
    item = upsert.messages[0]
    text = message_text(upsert)
    return (
        f"type={upsert.type} "
        f"id={item.key.id!r} "
        f"remote={item.key.remote_jid!r} "
        f"participant={item.key.participant!r} "
        f"push={item.push_name!r} "
        f"fields={[field.name for field, _ in item.message.ListFields()] if item.message else []} "
        f"text={text!r}"
    )


def message_text(upsert: MessageUpsert) -> str | None:
    item = upsert.messages[0]
    if item.message is None:
        return None
    if item.message.HasField("extendedTextMessage"):
        return item.message.extendedTextMessage.text
    if item.message.conversation:
        return item.message.conversation
    return None


async def main() -> int:
    parser = argparse.ArgumentParser(description="Wait for a live inbound messages.upsert event.")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--require-text", action="store_true", help="ignore non-text upserts until a text message arrives")
    parser.add_argument("--require-group", action="store_true", help="ignore upserts unless the remote JID is a group")
    parser.add_argument("--group-jid", help="only accept messages from this group JID")
    args = parser.parse_args()

    creds_path = Path(args.creds_path).resolve()
    if not creds_path.exists():
        print(f"MISSING_CREDS {creds_path}", flush=True)
        return 2

    client = make_socket(creds_path)
    loop = asyncio.get_running_loop()
    future = loop.create_future()

    def on_update(payload: dict) -> None:
        safe = {key: value for key, value in payload.items() if key != "qr"}
        print(f"EVENT connection.update {safe}", flush=True)

    def on_upsert(payload: MessageUpsert) -> None:
        print(f"MESSAGES_UPSERT {message_summary(payload)}", flush=True)
        if args.require_text and message_text(payload) is None:
            return
        remote_jid = payload.messages[0].key.remote_jid
        if args.require_group and not str(remote_jid or "").endswith("@g.us"):
            return
        if args.group_jid and remote_jid != args.group_jid:
            return
        if not future.done():
            future.set_result(payload)

    def on_decrypt_error(payload: dict) -> None:
        print(f"MESSAGES_DECRYPT_ERROR {payload['error']!r} node={payload['node']!r}", flush=True)

    client.ev.on("connection.update", on_update)
    client.ev.on("messages.upsert", on_upsert)
    client.ev.on("messages.decrypt_error", on_decrypt_error)

    try:
        await client.connect_and_wait(success_timeout=60)
        client.start_receive_loop(timeout=30)
        print(f"WAITING_FOR_MESSAGE seconds={args.timeout}", flush=True)
        await asyncio.wait_for(future, timeout=args.timeout)
    except asyncio.TimeoutError:
        print(f"MESSAGE_TIMEOUT seconds={args.timeout}", flush=True)
        return 2
    finally:
        await client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
