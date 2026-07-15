# API Examples

These examples use the public `baileys` package entrypoints.

## Auth State

```python
from baileys import make_socket

client = make_socket("auth/product_qr_creds.json")
```

For local multi-file auth:

```python
from baileys import use_multi_file_auth_state

auth_state = use_multi_file_auth_state("auth/session")
```

## WhatsAppClient

```python
import asyncio
from baileys import make_socket


async def main() -> None:
    client = make_socket("auth/product_qr_creds.json")
    client.ev.on("connection.update", print)

    try:
        await client.connect_and_wait(start_receive_loop=True)
    finally:
        await client.close()


asyncio.run(main())
```

## Send Message

```python
result = await client.send_message(
    "15551234567@s.whatsapp.net",
    {"text": "hello"},
)

print(result.message_id, result.status)
```

Common supported content builders include text, quotes, mentions, reactions,
edits, deletes, location, contacts, pins, polls, and group invites.

## Send Media

```python
result = await client.send_media_message(
    "15551234567@s.whatsapp.net",
    "testmedia/sample.jpg",
    media_type="image",
    caption="image from Python",
)

print(result.message_id, result.media_url)
```

Supported media types include image, video, audio, document, and sticker.

## Download Media

```python
payload = await client.download_media_message(message)

with open("downloaded.bin", "wb") as file:
    file.write(payload.data)
```

The media message must include enough media metadata for the library to fetch
and decrypt the file.

## Presence

```python
await client.send_presence_update("available")
await client.send_presence_update("composing", "15551234567@s.whatsapp.net")
await client.send_presence_update("paused", "15551234567@s.whatsapp.net")
```

## Profile And Privacy

```python
settings = await client.fetch_privacy_settings()
print(settings)

picture_url = await client.profile_picture_url("15551234567@s.whatsapp.net")
print(picture_url)

matches = await client.on_whatsapp("15551234567@s.whatsapp.net")
print(matches)
```

Profile mutation helpers are available, but use them carefully because they
change the linked account state.

## Groups

```python
metadata = await client.group_metadata("120363000000000000@g.us")
print(metadata.subject)

invite_code = await client.group_invite_code("120363000000000000@g.us")
print(invite_code)
```

Participant updates require the linked account to have the right group role:

```python
await client.group_participants_update(
    "120363000000000000@g.us",
    ["15551234567@s.whatsapp.net"],
    "add",
)
```

## SQLite Stores

SQLite stores are useful for one process on one machine:

```python
from baileys import use_sqlite_auth_state, make_sqlite_event_store, make_socket

auth_state = use_sqlite_auth_state("auth/session.sqlite")
event_store = make_sqlite_event_store("auth/events.sqlite")

client = make_socket(auth_state, event_store=event_store)
```

## Postgres Stores

Install the optional Postgres dependency:

```powershell
python -m pip install "baileys-python[postgres]"
```

Apply migrations and create auth state:

```python
from baileys import apply_postgres_migrations, use_postgres_auth_state

apply_postgres_migrations("postgresql://user:password@host/database")
auth_state = use_postgres_auth_state("postgresql://user:password@host/database")
```

For multi-tenant applications, wrap the store interfaces with tenant scoping so
each linked account gets isolated credentials, Signal keys, and replay records.
