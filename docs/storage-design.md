# Storage Design

The package currently ships with JSON credential storage, directory-backed
signal keys, SQLite-backed credential/signal/replay/event stores, and an
in-memory event store. The target design is to keep these simple defaults
while adding durable adapters behind stable interfaces.

## Current Built-In Guarantees

- `JsonCredentialStore` writes credentials atomically.
- `DirectorySignalKeyStore` writes key files atomically.
- `MemorySignalKeyStore` isolates mutable values with deep copies.
- `SQLiteCredentialStore` persists credentials in a local SQLite database.
- `SQLiteSignalKeyStore` persists signal-key namespaces in the same SQLite
  database shape.
- `AuthState.transaction()` persists credential mutations only when the block
  completes successfully.
- `InMemoryStore` is bindable to socket events and idempotent for duplicate
  message ids.
- `SQLiteEventStore` is bindable to socket events and persists messages, chats,
  contacts, message updates, receipts, reactions, LID/PN mappings, and
  app-state state in a local SQLite database.
- `ReplayStore` defines recent outbound replay persistence, with
  `InMemoryReplayStore` as the default implementation and `SQLiteReplayStore`
  as the local durable adapter.
- `binary_node_to_json` and `binary_node_from_json` preserve BinaryNode attrs,
  byte content, string content, and child nodes for durable replay adapters.

## Interfaces

### Credential Store

Required methods:

- `load_credentials() -> dict`
- `save_credentials(credentials: dict) -> None`

Target extension:

- optional `transaction(callback)` or context-manager support.
- optional optimistic version checks for concurrent writers.
- optional backup/export helper for account migration.

### Signal Key Store

Required methods:

- `get(namespace, key)`
- `set(namespace, key, value)`
- `delete(namespace, key)`

Target extension:

- `get_many(namespace, keys)`
- `set_many(namespace, values)`
- `delete_many(namespace, keys)`
- transaction support shared with credential updates.

### Event Store

Target methods:

- `bind(events)`
- `unbind(events)`
- `load_messages(jid, count=None)`
- `load_message(jid, message_id, participant=None)`
- `upsert_message(message)`
- `apply_message_update(update)`
- `apply_receipt_update(update)`
- `upsert_chat(chat)`
- `upsert_contact(contact)`
- `upsert_lid_pn_mapping(lid_jid, pn_jid, source)`
- `get_lid_for_pn(pn_jid)`
- `get_pn_for_lid(lid_jid)`
- `save_app_state(collection, state)`
- `load_app_state(collection)`
- `save_recent_outbound(message_id, node, expires_at)`
- `load_recent_outbound(message_id)`

The socket calls these through `ReplayStore` after a message node is sent and
again when a retry receipt needs a replay. Expired or missing entries are
treated as unavailable messages, not socket errors.

## SQLite Adapter

SQLite is the first durable adapter because it is local, easy to test, and
good enough for single-process bots. The current adapter covers credentials,
signal keys, recent outbound replay, event-backed message/chat/contact state,
LID/PN mappings, and app-state state.

### Tables

`credentials`

- `name text primary key`
- `value text not null`

`signal_keys`

- `namespace text not null`
- `key text not null`
- `value text not null`
- primary key: `(namespace, key)`

`recent_outbound`

- `message_id text primary key`
- `node_json text not null`
- `expires_at real not null`

`messages`

- `remote_jid text not null`
- `message_id text not null`
- `participant text not null default ''`
- `from_me integer not null default 0`
- `timestamp integer`
- `push_name text`
- `broadcast integer not null default 0`
- `message_blob blob`
- `updated_at integer not null`
- primary key: `(remote_jid, message_id, participant)`

`message_updates`

- `remote_jid text not null`
- `message_id text not null`
- `participant text not null default ''`
- `update_json text not null`
- `updated_at integer not null`
- primary key: `(remote_jid, message_id, participant)`

`message_receipts`

- `remote_jid text not null`
- `message_id text not null`
- `participant text not null default ''`
- `user_jid text not null`
- `receipt_json text not null`
- `updated_at integer not null`
- primary key: `(remote_jid, message_id, participant, user_jid)`

`chats`

- `id text primary key`
- `conversation_timestamp integer`
- `unread_count integer not null default 0`
- `name text`
- `updated_at integer not null`

`contacts`

- `id text primary key`
- `name text`
- `notify text`
- `updated_at integer not null`

`lid_pn_mappings`

- `lid_jid text primary key`
- `pn_jid text not null`
- `source text not null`
- `updated_at integer not null`

`app_state`

- `collection text primary key`
- `state_json text not null`
- `updated_at integer not null`

Additional planned tables:

`media_cache`

- `file_sha256 text primary key`
- `media_type text not null`
- `upload_json text not null`
- `expires_at integer`
- `updated_at integer not null`

### Transaction Rules

- Auth credential and signal-key updates that belong to the same socket action
  must commit in one transaction.
- Failed socket operations must not persist partially updated sessions,
  prekeys, signed prekeys, or LID/PN mappings.
- Recent outbound replay writes should happen after the message node is sent.
- Retry replay reads must tolerate expired or missing entries.
- App-state patch application must persist LT hash state only after MAC
  validation succeeds.

## Postgres Adapter

Postgres should use the same logical schema as SQLite and add:

- advisory or row locks for auth-state writers.
- JSONB indexes for selected query surfaces if needed.
- connection-pool integration supplied by the application.
- explicit migration files.

## Redis Adapter

Redis should be treated as an optional cache/replay store, not the only durable
source of truth unless the application accepts that tradeoff.

Good Redis uses:

- recent outbound replay cache.
- media upload cache.
- short-lived query or token caches.
- pub/sub for multi-process event fanout.

Risky Redis uses:

- long-term credentials without persistence.
- app-state LT hash as the only copy.
- message history as the only copy.

## Serialization

- WAProto messages should be stored as protobuf bytes when possible.
- Binary nodes can be stored as JSON using `binary_node_to_json` and restored
  with `binary_node_from_json`.
- Credentials and Signal records stay JSON-compatible to preserve current auth
  files.
- Unknown fields must be preserved.

## Implementation Order

1. Define public storage protocols for credentials, signal keys, app-state
   state, LID/PN mappings, recent outbound replay, and event store operations.
   Recent outbound replay is covered by `ReplayStore`; the other storage
   protocols remain future work.
2. Refactor socket code to depend on protocols where concrete file stores are
   still assumed.
3. Add SQLite credential and signal-key store. This is done for the public
   prototype.
4. Add SQLite event store. This is done for messages, chats, contacts,
   updates, receipts, reactions, LID/PN mappings, and app-state state.
5. Add replay cache integration for retry receipts. This is done for the
   public interface, in-memory default, and SQLite adapter.
6. Add broader LID/PN mapping store integration for USync and group metadata.
7. Add migration and backup helpers.
8. Add Postgres adapter after SQLite semantics are stable.

## Acceptance

- File-backed stores keep current tests green.
- SQLite-backed auth can pair, reconnect, send, receive, and logout.
- Failed prekey/session operations do not corrupt persisted credentials.
- Reconnect replay does not duplicate messages.
- LID/PN mapping survives process restart.
- App-state sync survives process restart.
- Recent outbound retry replay survives short process restarts within its TTL.
