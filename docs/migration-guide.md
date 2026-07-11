# Migration Guide From Node Baileys

This guide maps common Node Baileys usage to the Python package. The wire
protocol concepts are intentionally familiar, while the preferred API style is
Pythonic async.

## Imports

Node:

```ts
import makeWASocket, { useMultiFileAuthState } from '@whiskeysockets/baileys'
```

Python:

```python
from baileys import make_socket, use_multi_file_auth_state
```

Compatibility aliases are also available:

```python
from baileys import makeWASocket, useMultiFileAuthState
```

## Socket Creation

Node:

```ts
const { state, saveCreds } = await useMultiFileAuthState('auth')
const sock = makeWASocket({ auth: state })
sock.ev.on('creds.update', saveCreds)
```

Python:

```python
from baileys import make_socket, use_multi_file_auth_state

auth_state, save_creds = use_multi_file_auth_state("auth")
client = make_socket(auth_state)
client.ev.on("creds.update", lambda _: save_creds())
```

For a saved JSON credential file, `make_socket("auth/product_qr_creds.json")`
is the shortest path.

## Events

Node and Python use the same event naming style for the main public events:

```python
client.ev.on("connection.update", print)
client.ev.on("messages.upsert", print)
client.ev.on("creds.update", lambda _: save_creds())
```

Python handlers may be normal functions or async functions. Socket methods that
perform network work are awaited.

## Sending Text

Node:

```ts
await sock.sendMessage(jid, { text: 'hello' })
```

Python:

```python
await client.send_message(jid, {"text": "hello"})
await client.sendMessage(jid, {"text": "hello"})
```

The Python method returns a `SendMessageResult` with the message id, remote JID,
fanout recipients, signal types, ACK status, and sent node.

## Message Content

Node-style content dictionaries are accepted for common content:

```python
await client.send_message(jid, {"text": "hello", "mentions": [other_jid]})
await client.send_message(jid, {"react": {"key": key, "text": "+1"}})
await client.send_message(jid, {"edit": {"key": key, "text": "updated"}})
await client.send_message(jid, {"delete": key})
await client.send_message(jid, {"location": {"degreesLatitude": 18.52, "degreesLongitude": 73.85}})
```

For lower-level callers, generated `WAProto` message instances can be passed
directly to `send_message` or `relay_message`.

## Media

Node:

```ts
await sock.sendMessage(jid, { image: { url: './image.jpg' }, caption: 'hello' })
```

Python:

```python
await client.send_media_message(jid, "testmedia/sample.jpg", media_type="image", caption="hello")
```

Downloads use:

```python
data = await client.download_media_message(upload, media_key=media_key, media_type="image")
```

The Baileys alias `downloadMediaMessage` is available.

## Groups

Node:

```ts
const metadata = await sock.groupMetadata(groupJid)
await sock.groupParticipantsUpdate(groupJid, [jid], 'remove')
```

Python:

```python
metadata = await client.group_metadata(group_jid)
metadata = await client.groupMetadata(group_jid)
updates = await client.group_participants_update(group_jid, [jid], "remove")
```

When direct participant add is blocked by account policy, use
`group_participants_update_or_invite` to fall back to a structured invite.

## Profile, Privacy, And Presence

Pythonic names are preferred:

```python
await client.send_presence_update("available")
settings = await client.fetch_privacy_settings()
picture = await client.profile_picture_url(jid)
await client.update_profile_status("Available")
```

Common Node-style aliases such as `sendPresenceUpdate`,
`fetchPrivacySettings`, `profilePictureUrl`, and `updateProfileStatus` are
available.

## Store

Node Baileys commonly binds an in-memory store to `sock.ev`. Python exposes the
same idea:

```python
from baileys import make_in_memory_store

store = make_in_memory_store()
store.bind(client.ev)
```

The store tracks chats, contacts, messages, message updates, receipts, and
reactions from socket events.

## Errors

Network and server-side failures are surfaced as Python exceptions. WhatsApp IQ
errors keep the server-provided status, text, and reason where available, so
account-gated behavior can be handled explicitly.

```python
try:
    await client.newsletter_metadata("jid", newsletter_jid)
except Exception as exc:
    print(exc)
```

## Naming Rules

Use snake_case for new Python code:

- `send_message`
- `relay_message`
- `group_metadata`
- `fetch_privacy_settings`
- `download_media_message`

Use camelCase aliases when porting existing Node examples:

- `sendMessage`
- `relayMessage`
- `groupMetadata`
- `fetchPrivacySettings`
- `downloadMediaMessage`

Both styles call the same implementation.
