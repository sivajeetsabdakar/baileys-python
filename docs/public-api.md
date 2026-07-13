# Public API Guide

This package exposes a Pythonic async API first and keeps common Node Baileys
method names as compatibility aliases. The public entrypoints are available from
`baileys`.

## Socket And Auth

Use `make_socket` when you already have saved credentials:

```python
import asyncio
from baileys import make_socket


async def main():
    client = make_socket("auth/product_qr_creds.json")
    client.ev.on("connection.update", print)

    try:
        await client.connect_and_wait()
        await client.send_message("1234567890@s.whatsapp.net", {"text": "hello"})
    finally:
        await client.close()


asyncio.run(main())
```

The lower-level auth surfaces are:

- `AuthState`
- `JsonCredentialStore`
- `DirectorySignalKeyStore`
- `SQLiteCredentialStore`
- `SQLiteSignalKeyStore`
- `use_multi_file_auth_state`
- `useMultiFileAuthState`
- `use_sqlite_auth_state`
- `useSqliteAuthState`

QR pairing, pairing-code linking, saved reconnect, logout, prekey maintenance,
and disconnect reason mapping are exposed on `WhatsAppClient`.

`JsonCredentialStore` and `DirectorySignalKeyStore` write files atomically.
`SQLiteCredentialStore` and `SQLiteSignalKeyStore` provide a local durable
adapter for single-process bots. Use `AuthState.transaction()` when several
credential fields should be updated and persisted together:

```python
with auth_state.transaction() as creds:
    creds["routing_info"] = "..."
    creds["next_pre_key_id"] = 100
```

## Events

Every socket has an async event emitter at `client.ev`.

Common event names:

- `connection.update`
- `creds.update`
- `messages.upsert`
- `messages.update`
- `message-receipt.update`
- `messages.retry`
- `messages.retry_error`
- `messages.media-update`
- `chats.upsert`
- `chats.update`
- `contacts.upsert`
- `contacts.update`
- `groups.update`
- `group-participants.update`
- `presence.update`
- `call`
- `notification`
- `dirty`
- `offline`

Unknown inbound nodes remain observable through raw node events instead of
crashing the socket.

## Logging

The library uses the `baileys` logger namespace and stays quiet until logging is
configured by the application:

```python
from baileys import configure_logging, make_socket

configure_logging("INFO")
client = make_socket("auth/product_qr_creds.json")
```

Structured log records include connection state, query ids, node tags, child
tags, retry stages, and close reasons. Node payload bytes, keys, tokens,
signatures, and long opaque values are redacted before they are attached to log
records.

## Errors

Package-raised public exceptions inherit from `BaileysError`. Existing
standard exception compatibility is preserved, so validation errors such as
`UnsupportedMessageContent`, `WAMEncodeError`, `MediaError`, `PairingError`,
and `SessionAssertionError` remain `ValueError` instances. Runtime failures
such as `IQError`, `MexError`, `MissingAppStateKey`, `ProtocolError`, and
`SocketNotConnectedError` remain `RuntimeError` instances. Timeout failures
such as `QueryTimeoutError` remain `TimeoutError` instances and expose
operation metadata.

Useful catch surfaces:

- `BaileysError`
- `BaileysValueError`
- `BaileysRuntimeError`
- `BaileysTimeoutError`
- `AccountCapabilityError`
- `AuthStateError`
- `ContactResolutionError`
- `DisconnectError`
- `GroupInviteError`
- `IQError`
- `MediaError`
- `MexError`
- `PairingError`
- `ProtocolError`
- `QueryTimeoutError`
- `SessionAssertionError`
- `SocketNotConnectedError`

## Replay Store

Retry receipts can replay recently sent outbound message nodes through the
socket replay store. The default `InMemoryReplayStore` preserves current
behavior; applications can pass another `ReplayStore` implementation to
`make_socket` when recent outbound replay should survive process restarts.

Useful helpers:

- `ReplayStore`
- `InMemoryReplayStore`
- `SQLiteReplayStore`
- `binary_node_to_json`
- `binary_node_from_json`
- `client.save_recent_outbound`
- `client.load_recent_outbound`
- `client.prune_recent_outbound`

## Sending Messages

Pythonic methods and Baileys aliases both work:

```python
await client.send_message(jid, {"text": "hello"})
await client.sendMessage(jid, {"text": "hello"})
```

Supported content builders include:

- text and extended text
- quoted messages
- mentions
- forwarded markers
- reactions
- edits and deletes
- location
- contact and contact list
- pin and unpin
- polls
- structured group invites

`relay_message` / `relayMessage` accepts a prepared `BinaryNode`, an outbound
message payload, or a generated proto message for lower-level flows.

## Media

Use `send_media_message` for file or bytes input:

```python
result = await client.send_media_message(
    jid,
    "testmedia/sample.jpg",
    media_type="image",
    caption="image from Python",
)
```

Use `download_media_message` / `downloadMediaMessage` to fetch and optionally
decrypt media. `update_media_message` / `updateMediaMessage` sends the media
retry request for a message whose media needs reupload.

Live proof currently covers image, video, audio, document, and sticker
send/download/decrypt. Media retry request and ACK are live-proven; the final
encrypted media-update response depends on WhatsApp returning a reupload for an
unavailable media item.

## Chats, Profile, Privacy, And Groups

Common chat and account methods:

- `chat_modify` / `chatModify`
- `archive_chat`, `mute_chat`, `pin_chat`, `delete_chat`
- `star_message`
- `send_presence_update` / `sendPresenceUpdate`
- `on_whatsapp` / `onWhatsApp`
- `profile_picture_url` / `profilePictureUrl`
- `update_profile_name` / `updateProfileName`
- `update_profile_status` / `updateProfileStatus`
- `update_profile_picture`, `remove_profile_picture`
- `fetch_privacy_settings` / `fetchPrivacySettings`
- `update_privacy_setting`
- `fetch_blocklist`
- `update_block_status` / `updateBlockStatus`

Common group methods:

- `group_metadata` / `groupMetadata`
- `group_create` / `groupCreate`
- `group_leave` / `groupLeave`
- `group_update_subject`
- `group_update_description`
- `group_participants_update` / `groupParticipantsUpdate`
- `group_participants_update_or_invite`
- `group_invite_code` / `groupInviteCode`
- `group_revoke_invite` / `groupRevokeInvite`
- `group_accept_invite` / `groupAcceptInvite`
- `group_get_invite_info` / `groupGetInviteInfo`
- `group_setting_update`
- `group_toggle_ephemeral`
- `group_member_add_mode`
- `group_join_approval_mode`

## History And App-State

The app-state surface includes snapshot fetch, sync-key request, patch
application, LT hash updates, MAC validation, encrypted patch writes, and an
event store that can bind to socket events.

Use `make_in_memory_store` / `makeInMemoryStore` for the default event-backed
store. Use `SQLiteEventStore` or `make_sqlite_event_store` when message,
chat, contact, receipt, reaction, LID/PN mapping, and app-state state should
survive process restarts.

## Business, Newsletters, Communities, And Edge APIs

Phase 7 surfaces are exposed where the account supports them:

- business profile, catalog, collections, product, order, and cover-photo APIs
- newsletter create/update/metadata/follow/mute/subscriber/admin/message APIs
- MEX query helpers
- community metadata/create/link/invite/participant/settings APIs
- WAM telemetry encoding and upload helpers
- low-level USync, privacy-token, peer-data, labels, bot-list, and call helpers

Some Phase 7 methods are account-gated by WhatsApp. In those cases the client
raises a structured server error instead of hiding the rejection.
