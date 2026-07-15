# Quickstart

## Install

```powershell
python -m pip install baileys-python
```

Baileys Python currently supports Python 3.12.

## Create A Saved-Auth Session

The easiest runtime flow is:

1. Pair once with a QR code using a local probe or your application.
2. Save the credentials.
3. Reuse the saved credentials in your bot or service.

For local development, the product QR probe writes credentials under a relative
`auth/` path:

```powershell
python scripts/product_qr_pairing_probe.py --open --scan-timeout 180 --reconnect-check
```

Scan the QR from WhatsApp Linked devices. Use a dedicated test account first.

## Connect With Saved Auth

```python
import asyncio
from baileys import configure_logging, make_socket


async def main() -> None:
    configure_logging("INFO")
    client = make_socket("auth/product_qr_creds.json")
    client.ev.on("connection.update", print)

    try:
        await client.connect_and_wait(start_receive_loop=True)
        print("connected")
    finally:
        await client.close()


asyncio.run(main())
```

## Send A Text Message

WhatsApp JIDs use the full WhatsApp domain:

```python
import asyncio
from baileys import make_socket


async def main() -> None:
    client = make_socket("auth/product_qr_creds.json")

    try:
        await client.connect_and_wait(start_receive_loop=True)
        result = await client.send_message(
            "15551234567@s.whatsapp.net",
            {"text": "hello from Python"},
        )
        print(result.message_id, result.status)
    finally:
        await client.close()


asyncio.run(main())
```

The Baileys-style alias is also available:

```python
await client.sendMessage("15551234567@s.whatsapp.net", {"text": "hello"})
```

## Receive Messages

```python
import asyncio
from baileys import MessageUpsert, make_socket


def first_text(upsert: MessageUpsert) -> tuple[str, str] | None:
    if not upsert.messages:
        return None

    item = upsert.messages[0]
    if item.message is None or item.key.from_me:
        return None

    text = None
    if item.message.conversation:
        text = item.message.conversation
    elif item.message.HasField("extendedTextMessage"):
        text = item.message.extendedTextMessage.text

    if not text or not item.key.remote_jid:
        return None

    return item.key.remote_jid, text


async def main() -> None:
    client = make_socket("auth/product_qr_creds.json")

    async def on_message(upsert: MessageUpsert) -> None:
        parsed = first_text(upsert)
        if parsed is None:
            return

        remote_jid, text = parsed
        print(remote_jid, text)

        if text.strip().lower() == "!ping":
            await client.send_message(remote_jid, {"text": "pong"})

    client.ev.on("messages.upsert", on_message)

    try:
        await client.connect_and_wait(start_receive_loop=True)
        await asyncio.sleep(300)
    finally:
        await client.close()


asyncio.run(main())
```

## Pairing Notes

- QR linking is account-gated by WhatsApp and can be temporarily rejected.
- Pairing-code support is implemented, but live completion depends on the
  account being eligible for that flow.
- Saved reconnect is the preferred path for long-running services.
- Keep credentials private. Treat saved auth state like a password.
