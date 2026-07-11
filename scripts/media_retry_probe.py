from __future__ import annotations

import argparse
import asyncio
import sys
import traceback
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import MessageUpsert, WAMessage, make_socket  # noqa: E402


MEDIA_FIELDS = ("imageMessage", "videoMessage", "audioMessage", "documentMessage", "stickerMessage")


def media_field(message: WAMessage) -> str | None:
    if message.message is None:
        return None
    for field in MEDIA_FIELDS:
        if message.message.HasField(field):
            return field
    return None


def media_type_from_field(field: str) -> str:
    return field.removesuffix("Message")


def media_content(message: WAMessage):
    field = media_field(message)
    return getattr(message.message, field) if field and message.message is not None else None


def describe_media(message: WAMessage) -> str:
    field = media_field(message)
    content = media_content(message)
    if content is None or field is None:
        return "media=none"
    return (
        f"media={media_type_from_field(field)} id={message.key.id!r} "
        f"remote={message.key.remote_jid!r} participant={message.key.participant!r} "
        f"direct_path={getattr(content, 'directPath', '')!r} url={getattr(content, 'url', '')!r} "
        f"media_key_len={len(bytes(getattr(content, 'mediaKey', b'')))}"
    )


async def wait_for_media(client, *, timeout: float, from_jid: str | None = None, message_id: str | None = None) -> WAMessage:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[WAMessage] = loop.create_future()

    def on_upsert(payload: MessageUpsert) -> None:
        for message in payload.messages:
            if media_field(message) is None:
                print(f"IGNORED_NON_MEDIA id={message.key.id!r} remote={message.key.remote_jid!r}", flush=True)
                continue
            if from_jid and message.key.remote_jid != from_jid and message.key.participant != from_jid:
                print(f"IGNORED_MEDIA_FROM {describe_media(message)}", flush=True)
                continue
            if message_id and message.key.id != message_id:
                print(f"IGNORED_MEDIA_ID {describe_media(message)}", flush=True)
                continue
            print(f"MEDIA_CANDIDATE {describe_media(message)}", flush=True)
            if not future.done():
                future.set_result(message)
            return

    client.ev.on("messages.upsert", on_upsert)
    deadline = loop.time() + timeout
    while not future.done():
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise asyncio.TimeoutError()
        try:
            await client.receive_nodes(timeout=min(10, remaining))
        except (TimeoutError, asyncio.TimeoutError):
            continue
    return await future


async def main() -> int:
    parser = argparse.ArgumentParser(description="Live-test media retry reupload through updateMediaMessage.")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--retry-timeout", type=float, default=90)
    parser.add_argument("--from-jid", help="only accept a media message from this remote or participant JID")
    parser.add_argument("--message-id", help="only accept this inbound message id")
    parser.add_argument("--download", action="store_true", help="download/decrypt the updated media after retry")
    parser.add_argument("--debug", action="store_true", help="print a traceback when the probe fails")
    args = parser.parse_args()

    creds_path = Path(args.creds_path)
    if not creds_path.exists():
        print(f"MISSING_CREDS {args.creds_path}", flush=True)
        return 2

    client = make_socket(creds_path)
    client.ev.on("connection.update", lambda payload: print(f"EVENT connection.update {payload}", flush=True))
    client.ev.on("messages.media-update", lambda payload: print(f"EVENT messages.media-update count={len(payload)}", flush=True))
    client.ev.on("messages.decrypt_error", lambda payload: print(f"EVENT messages.decrypt_error {payload['error']!r}", flush=True))
    client.ev.on("node.receipt", lambda node: print(f"EVENT node.receipt attrs={node.attrs}", flush=True))
    client.ev.on("node.ack", lambda node: print(f"EVENT node.ack attrs={node.attrs}", flush=True))
    original_send_node = client.send_node

    async def logging_send_node(node):
        if node.tag == "receipt" and node.attrs.get("type") == "server-error":
            child_tags = [child.tag for child in node.content] if isinstance(node.content, list) else []
            print(f"SEND_MEDIA_RETRY_REQUEST attrs={node.attrs} children={child_tags}", flush=True)
        await original_send_node(node)

    client.send_node = logging_send_node  # type: ignore[method-assign]

    try:
        await client.connect_and_wait(success_timeout=60)
        print(f"WAITING_FOR_MEDIA seconds={args.timeout}", flush=True)
        message = await wait_for_media(client, timeout=args.timeout, from_jid=args.from_jid, message_id=args.message_id)
        before = media_content(message)
        before_direct = getattr(before, "directPath", "")
        before_url = getattr(before, "url", "")
        print(f"MEDIA_SELECTED {describe_media(message)}", flush=True)

        updated = await client.update_media_message(message, timeout=args.retry_timeout)
        after = media_content(updated)
        after_direct = getattr(after, "directPath", "")
        after_url = getattr(after, "url", "")
        print(
            f"MEDIA_RETRY_SUCCESS id={message.key.id} before_direct={before_direct!r} "
            f"after_direct={after_direct!r} before_url={before_url!r} after_url={after_url!r}",
            flush=True,
        )

        if args.download and after is not None:
            field = media_field(updated)
            media_type = media_type_from_field(field) if field else ""
            upload = SimpleNamespace(media_url=after_url, direct_path=after_direct, host="mmg.whatsapp.net")
            data = await client.download_media_message(upload, media_key=bytes(after.mediaKey), media_type=media_type)
            print(f"DOWNLOAD_AFTER_RETRY_OK type={media_type} bytes={len(data)}", flush=True)
    except asyncio.TimeoutError:
        print("MEDIA_RETRY_TIMEOUT", flush=True)
        return 2
    except Exception as exc:
        print(f"MEDIA_RETRY_ERROR {type(exc).__name__}: {exc}", flush=True)
        if args.debug:
            traceback.print_exc()
        return 1
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
