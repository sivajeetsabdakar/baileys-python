# Baileys Compatibility Matrix

Target reference: local Node Baileys `7.0.0-rc13`.

Legend:

- `Done`: implemented in `Baileys-python` and covered by tests or proven spike
- `Seeded`: copied from proven spike, needs production API hardening
- `Partial`: some capability exists, parity incomplete
- `Todo`: not implemented in product package yet

| Area | Capability | Status | Notes |
| --- | --- | --- | --- |
| Core | WAProto generated Python classes | Done | Generated artifact is package data and checked by `scripts/generate_proto.py --check` when proto tooling is installed. |
| Core | Tokenized WABinary encode/decode | Done | Includes dictionary tokens, packed nibbles/hex, AD/FB/interop JIDs, and compressed frame vectors. |
| Core | JID utilities | Done | Shared parser/encoder/classifiers cover PN, LID, hosted, group, broadcast, newsletter, bot/meta, integrator, same-user, transfer-device, and Baileys-compatible aliases. |
| Core | Defaults/version constants | Done | Central defaults feed registration, socket, Noise, prekey, media, and key derivation layers. |
| Core | Crypto/key primitives | Done | AES/HKDF/HMAC/hash/X25519, pairing-code key derivation, media keys, app-state keys, Noise helpers, Signal sessions, and group sender keys have offline vectors. |
| Core | WAM telemetry encoder | Todo | Not ported. |
| Core | WAUSync protocol builders | Partial | Device discovery exists; full protocol set needed. |
| Auth | Credential models | Done | Typed wrappers round-trip existing auth dicts and preserve unknown future fields. |
| Auth | Credential generation | Done | Registration payload, key material, QR pairing, and pair-success credential persistence are wired through product auth state and covered by tests/live QR proof. |
| Auth | QR pairing | Done | Product `WhatsAppClient.connect_for_qr_pairing()` live-proven: QR refs, scan, `pair-success`, device signature, and saved creds. |
| Auth | Pairing-code flow | Partial | Request and success-finalization paths are wired and offline-tested; live completion depends on account capability and remains pending. |
| Auth | Saved auth login/reconnect | Done | Product QR probe live-proved saved reconnect through `WhatsAppClient.connect_and_wait()` after QR pairing. |
| Auth | Multi-file auth state | Partial | Storage interfaces, JSON credential store, directory signal-key store, and `useMultiFileAuthState` alias added; production transactions still needed in later auth hardening. |
| Auth | Signal key store and transactions | Partial | JSON hydration/export exists; production store API needed. |
| Auth | Prekey upload/digest/rotation | Done | Product socket methods `digest_key_bundle`, `count_pre_keys`, `maintain_pre_keys`, `upload_pre_keys`, and `rotate_signed_pre_key` are wired and tested; login lifecycle runs non-fatal low-count maintenance with bounded upload backoff. |
| Auth | Routing info | Seeded | WebSocket `ED` and Noise intro supported. |
| Auth | LID/PN mapping | Partial | USync and history mapping need production store integration. |
| Socket | Noise handshake | Seeded | Live server hello/login proven. |
| Socket | Query/response correlation | Done | Query manager resolves by node id, cancels timed-out waiters, and can drive receive while awaiting responses. |
| Socket | Event emitter | Done | Async event emitter supports `on`, `once`, `off`, `emit`, and `wait_for`; Phase 3 event taxonomy now covers message, receipt, notification, dirty, offline, call, reconnect, and auth surfaces. |
| Socket | Public socket API | Done | `WhatsAppClient`, `make_socket`, and `makeWASocket` facade includes QR pairing, saved reconnect, event emitter, query manager, receive loop, reconnect, logout, ACKs, receipts, and prekey maintenance. |
| Socket | Keepalive/reconnect | Done | Saved-auth reconnect is live-proven; receive loop handles server pings and automatic retry/backoff for retryable disconnects, keepalive failures, and exhausted reconnect attempts. |
| Socket | Logout/disconnect reasons | Done | `logout()` sends `remove-companion-device`, clears saved auth by default, and emits `loggedOut`; `stream:error`, `failure`, transport errors, and intentional logout map to deterministic `DisconnectReason` values. |
| Inbound | Binary node dispatcher | Done | Classifier plus socket dispatch covers message, receipt, notification, call, dirty, offline, failure, stream-error, server ping, IQ, ACK, and unknown-node observability. |
| Inbound | Message decrypt | Partial | 1:1 pkmsg/msg live-proven through product `messages.upsert`; group skmsg is offline-proven. Broader message/content processors still needed. |
| Inbound | Retry receipts | Partial | Retry receipt parsing, retry count limiting, session-bundle injection, `messages.retry` / `messages.retry_error` events, and resend hook are wired; full `relayMessage` replay/cache parity still needed. |
| Inbound | Receipts/acks | Done | Baileys-compatible ACK builder added, socket auto-ACKs message/receipt/notification/call nodes, direct receipts emit `messages.update` status changes, group/status receipts emit `message-receipt.update`, and retry receipts route separately. |
| Inbound | Notifications/calls/offline nodes | Done | Typed notification, dirty/app-state, offline, and call dispatch emits stable events while preserving raw node observability for unknown cases. |
| Outbound | `sendMessage` text | Partial | Direct and USync fanout text proven in spike. |
| Outbound | `relayMessage` | Todo | Needs production API and group/newsletter paths. |
| Outbound | Receipts/read messages | Partial | Basic `send_receipt`/`read_messages` builders send receipt nodes; privacy-setting-aware read type and full aggregation semantics still needed. |
| Outbound | Privacy tokens/peer data operations | Todo | Not ported. |
| Messages | Text/extended text | Partial | Basic text exists. |
| Messages | Quote/mention/forward/location/contact/reaction/pin/poll/edit/delete | Todo | Content generation needed. |
| Media | Image upload/send/download | Seeded | Live-proven image path. |
| Media | Video/audio/document/sticker/stream/url inputs/thumbnails/reupload | Todo | Not ported. |
| Chats | Presence/status/profile/privacy/blocklist/chat modify | Todo | Not ported. |
| History | History sync/app-state/LTHash/MAC validation | Partial | Key derivation exists; full sync pipeline needed. |
| Store | In-memory store and buffered events | Done | Bindable `InMemoryStore` tracks messages, chats, contacts, message updates, per-user receipts, and reactions from inbound events; durable stores are a later extension. |
| Groups | Metadata/create/participants/invites/settings | Todo | Only group probing exists. |
| Communities | Community APIs | Todo | Not ported. |
| Business | Profile/catalog/products/orders | Todo | Not ported. |
| Newsletters | MEX/newsletter APIs/events | Todo | Not ported. |
| Tooling | Package install/tests/examples | Done | Product bootstrap provides baseline install, tests, and generated-artifact check modes. |
| Tooling | Live test harness | Partial | Spike probes copied into product `scripts/`; product QR/reconnect probe added; pytest-style live suite still needed. |
| Docs | Migration guide/API docs | Todo | README and matrix only. |
