# Inbound Processing Design

The inbound pipeline already handles binary node dispatch, message decrypt,
ACKs, receipts, retry requests, notifications, offline nodes, and app-state
sync. The remaining work is to normalize more message content, persist more
message-derived state, and make retry/replay behavior durable.

## Pipeline

1. Receive a WebSocket frame.
2. Decode WABinary into a `BinaryNode`.
3. Classify the node.
4. Send automatic ACK when required.
5. Dispatch to a typed handler.
6. Decrypt message payloads when supported.
7. Normalize message content.
8. Emit stable public events.
9. Apply store updates.
10. Persist required auth, mapping, replay, or app-state changes.

Each step should be independently testable with offline node vectors.

## Message Decrypt

Current support:

- direct message decrypt.
- group sender-key decrypt.
- sender-key distribution ingestion.
- decrypt-error events.

Remaining support:

- more protocol-message subtypes.
- status/broadcast-specific key handling.
- view-once wrappers.
- ephemeral wrappers.
- edited message wrappers.
- keep-in-chat and pinned-message wrappers.
- unsupported encrypted payload events with enough metadata for debugging.

## Content Normalization

Inbound messages should expose two forms:

- raw generated WAProto message for exact parity.
- normalized helper fields for common application use.

Target normalized fields:

- `message_type`
- `text`
- `caption`
- `quoted`
- `mentions`
- `media`
- `reaction`
- `edit`
- `delete`
- `location`
- `contacts`
- `poll`
- `pin`
- `protocol`
- `ephemeral`
- `view_once`

The raw message should always remain available.

## Event Emission

`messages.upsert` should remain the primary inbound event. Additional events
can be emitted when content implies a specialized update:

- reaction messages update `messages.reaction`.
- edit protocol messages update `messages.update`.
- delete/revoke protocol messages update `messages.update`.
- receipt nodes update `messages.update` or `message-receipt.update`.
- media retry receipts update `messages.retry`.
- media retry responses update `messages.media-update`.
- call nodes update `call`.
- group change notifications update `groups.update` and
  `group-participants.update`.

Unknown content should not block `messages.upsert`.

## Store Integration

The store should consume events rather than receive hidden socket calls.

Required updates:

- add message body normalization for search and display.
- store edited message replacement metadata.
- store delete/revoke markers.
- store media metadata and download state.
- store poll creation and response updates.
- store pin/unpin state.
- store contact updates from history and app-state patches.
- store LID/PN mappings from history, USync, group metadata, and contact
  patches.
- persist recent outbound nodes for retry replay.

The in-memory store should remain simple. Durable stores should implement the
same event-backed behavior.

## Retry Receipts

Current support:

- retry receipt parsing.
- retry count limiting.
- session-bundle injection.
- recent outbound replay from memory.

Target support:

- durable recent outbound replay.
- retry state persisted by message id and participant.
- replay TTL cleanup.
- retry failure event with reason and original request.
- session assertion after identity/device updates.
- retry behavior for group participant fanout.

## Device And Identity Changes

Device and identity notifications should update state without breaking active
receive loops.

Required behavior:

- parse device-list changes into stable events.
- invalidate stale sessions when the identity changes.
- trigger session assertion for future sends.
- preserve unknown notification payloads.
- never delete sessions until replacement state is safe to use.

## Offline Nodes

Offline nodes should be observable and safe:

- emit `offline` with node attrs and child summaries.
- route contained messages, receipts, and notifications through the same
  handlers where possible.
- dedupe replayed message ids.
- do not double-increment unread counts.

## Acceptance

- Offline vectors cover each normalized message content type.
- Decrypt failures emit `messages.decrypt_error` and do not stop the socket.
- Duplicate messages are idempotent in the store.
- Retry receipts can replay a stored outbound node after restart with a durable
  store.
- Device/identity notifications update observable state without crashes.
- Live 1:1, group, media, reaction, edit/delete, receipt, and retry smoke tests
  stay green where the account can trigger them.
