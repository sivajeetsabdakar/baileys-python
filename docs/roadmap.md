# Full Baileys-Python Roadmap

## Goal

Build `Baileys-python` into a full Python equivalent of local Node Baileys
`7.0.0-rc13`, using `../baileys-python-test` only as the proven reference lab.

The API should be Pythonic async first, with compatibility aliases for common
Baileys names such as `sendMessage`, `relayMessage`, `groupMetadata`,
`useMultiFileAuthState`, and `downloadMediaMessage`.

## Timeline

| Phase | Target | Status |
| --- | --- | --- |
| 0 | Product repo bootstrap | Done |
| 1 | Protocol foundation | Done |
| 2 | Auth and socket lifecycle | Done |
| 3 | Event/store and inbound pipeline | Done |
| 4 | Outbound messages and media breadth | Partial |
| 5 | Chats, profile, privacy, groups | Partial |
| 6 | History and app-state completeness | Not started |
| 7 | Business, newsletters, communities, edge surfaces | Not started |
| 8 | Core beta release hardening | Not started |
| 9 | Full parity hardening | Not started |

## Release Strategy

Ship a core beta before full parity once auth, sockets, events, common
send/receive, media, groups, profile/privacy, docs, examples, and live smoke
tests are stable.

## Phase 0 Delivered

- `src/baileys/` package seeded from the proven spike.
- `pyproject.toml`, package data, README, examples, tests, and live probe
  scripts added.
- Compatibility matrix created against Node Baileys `7.0.0-rc13`.
- Baseline verification: editable install, example execution, compile check,
  and offline tests.

## Phase 1 Delivered

- Added central protocol defaults for versioning, WebSocket origin, Noise intro,
  JID servers, key-bundle constants, prekey thresholds, and media mapping names.
- Added shared JID utilities with encode/decode, normalization,
  phone-number-to-JID, Baileys-compatible aliases, hosted/LID domain typing,
  device transfer, same-user comparison, and classifier helpers.
- Added typed auth credential wrappers that round-trip existing JSON auth dicts
  and preserve unknown future fields.
- Added auth-state storage interfaces, JSON credentials, directory signal-key
  storage, and the `useMultiFileAuthState` compatibility alias.
- Added check modes for WAProto and WABinary generated artifacts.
- Added offline vectors for WABinary tokenized nodes, packed nibble/hex,
  AD/FB/interop JIDs, compressed frames, crypto, media/app-state key
  derivation, pairing-code key wrapping, Noise intro, Signal sessions, and
  group sender keys.
- Added public socket facade with `WhatsAppClient`, `make_socket`,
  `makeWASocket`, async event emitter, and query correlation primitives.
- Added saved-auth lifecycle helpers, receive-loop dispatch, server-ping
  auto-reply, pairing-code request builders, and QR payload helpers.
- Added QR-first registration socket path that emits QR payloads,
  acknowledges `pair-device`, and finalizes `pair-success` into saved
  credentials.
- Added `scripts/product_qr_pairing_probe.py` to exercise QR pairing and
  saved reconnect through the product `WhatsAppClient` API.
- Rewired registration, client, Noise, prekey, retry, session assertion, and
  USync helpers to use shared foundation modules while keeping old imports
  compatible.

## Phase 2 Delivered

- Live-proved the product QR pairing flow through
  `scripts/product_qr_pairing_probe.py --open --scan-timeout 180 --reconnect-check`.
- Confirmed `WhatsAppClient.connect_for_qr_pairing()` receives QR refs, emits a
  QR payload, finalizes `pair-success`, persists
  `auth/product_qr_creds.json`, and reconnects through saved auth.
- Live reconnect success returned server attrs including `lid`,
  `companion_enc_static`, and success timestamp fields.
- Added product socket methods for prekey digest, prekey upload, and signed
  prekey rotation with Baileys-style aliases `digestKeyBundle`,
  `uploadPreKeys`, and `rotateSignedPreKey`.
- Added login-time prekey maintenance using server prekey count, low-count
  upload, bounded retry/backoff, and non-fatal `prekeys.update` failure events.
- Added Baileys-compatible logout and disconnect reason handling for
  `stream:error`, `failure`, and intentional logout close events.
- Added configurable automatic reconnect policy with bounded backoff,
  retryable disconnect filtering, receive-loop continuation, keepalive failure
  scheduling, and observable reconnect events.
- Hardened pairing-code request and pair-success finalization through the same
  `WhatsAppClient` and `AuthState` paths used by QR pairing.
- Covered query timeout cleanup, deterministic disconnect mapping, intentional
  logout, auth clearing, reconnect exhaustion, keepalive failure handling, and
  credential persistence behavior with offline tests.
- Added `scripts/product_pairing_code_probe.py` and live-proved pairing-code
  completion through server `pair-success`, product credential persistence, and
  saved reconnect.

## Phase 3 Delivered

- Added initial inbound `messages.upsert` payloads for decrypted message nodes.
- Added `MessageKey`, `WAMessage`, and `MessageUpsert` public types with a
  `to_web_message_info()` bridge to generated WAProto.
- Socket dispatch now emits `messages.upsert` for supported encrypted message
  nodes and `messages.decrypt_error` for decrypt failures.
- Added `scripts/product_inbound_probe.py` to live-test inbound
  `messages.upsert` using saved product QR credentials.
- Live-proved inbound text decrypt and event emission with
  `scripts/product_inbound_probe.py --require-text`; WhatsApp delivered the
  sender as a LID JID and emitted multiple text `messages.upsert` payloads.
- Added Baileys-compatible ACK stanza construction and automatic socket ACKs
  for inbound message, receipt, notification, and call nodes.
- Added basic inbound receipt processing that emits `message-receipt.update`.
- Added retry receipt parsing, retry count limiting, session-bundle injection,
  `messages.retry` / `messages.retry_error` events, and an overridable resend
  hook for later `relayMessage` parity.
- Added receipt status mapping so direct receipts emit `messages.update` and
  group/status receipts emit per-user `message-receipt.update` timestamps.
- Added basic outbound `send_receipt` and `read_messages` helpers plus
  Baileys-style aliases.
- Added a bindable `InMemoryStore` and default `client.store` that tracks
  messages, chats, and contacts from `messages.upsert`, with
  `makeInMemoryStore` compatibility alias.
- Added typed notification, dirty/app-state, offline, and call dispatch events
  so important inbound stanzas have stable event surfaces in addition to raw
  node events.
- Kept unknown or unsupported notification/offline nodes observable without
  crashing the receive path.
- Expanded the in-memory store to consume `messages.update`,
  `message-receipt.update`, and reaction payloads derived from
  `messages.upsert`.
- Live 1:1 inbound text remains proven through the product inbound probe.
- Live group inbound text is proven through the same product inbound probe using
  `--require-group`; the run received a sender-key distribution message and a
  decrypted group text message.

## Phase 4 In Progress

- Added product outbound APIs on `WhatsAppClient`: `send_message`,
  `relay_message`, `download_media_message`, and `send_media_message`.
- Added Baileys-style aliases `sendMessage`, `relayMessage`,
  `downloadMediaMessage`, and `sendMediaMessage`.
- Promoted the proven text send path into the product client, including direct
  sends, group/USync fanout, Signal session assertion, credential persistence
  after successful relay, and recent outbound replay for retry receipts.
- Added message content builders for text, extended text, mentions, quote keys,
  reactions, edit, delete, location, contact, and contact-list messages.
- Added typed errors for unsupported message content instead of sending
  malformed payloads.
- Added media payload helpers for bytes and file paths plus generic
  image/video/audio/document/sticker protobuf message generation.
- Integrated media connection fetch/cache, media encrypt/upload, and product
  media send/download helpers.
- Reworked `scripts/send_text_probe.py` and `scripts/send_image_probe.py` to
  call the product `WhatsAppClient` APIs.
- Offline tests cover content builders, relay/cache retry replay, media message
  generation, send aliases, and product send orchestration.
- Live Phase 4 outbound coverage is proven for direct 1:1 text with ACK and
  image send/download/decrypt through `scripts/send_text_probe.py` and
  `scripts/send_image_probe.py`.
- Peer USync and session assertion are live-proven for a third-party contact
  with multiple companion devices; all returned sessions were injected and no
  unresolved device sessions remained.
- Added `scripts/message_content_probe.py` for live reaction, edit, delete, and
  reaction-removal validation through the product send API.
- Added `scripts/send_media_probe.py` for reusable product media probes across
  generated image/document/sticker payloads and real sample files.
- 1:1 send has direct session bootstrap coverage in product code and is
  live-proven for a third-party peer with USync device fanout.
- Group text send is live-proven with ACK against the dedicated test group.
- Reaction add/remove, edit, and delete are live-proven with ACK against the
  dedicated test peer.
- Image, video, audio, document, and sticker send/download/decrypt are
  live-proven with ACK using generated samples and file-backed fixtures.

## Phase 5 In Progress

- Added chat and presence APIs: `chat_modify`, `archive_chat`, `mute_chat`,
  `pin_chat`, `delete_chat`, `star_message`, and `send_presence_update`.
- Added profile/privacy/blocklist APIs: `on_whatsapp`,
  `profile_picture_url`, `update_profile_name`, `update_profile_status`,
  `update_profile_picture`, `remove_profile_picture`,
  `fetch_privacy_settings`, `update_privacy_setting`, `fetch_blocklist`, and
  `update_block_status`.
- Added group APIs: `group_metadata`, `group_create`, `group_leave`,
  `group_update_subject`, `group_update_description`,
  `group_participants_update`, `group_invite_code`, `group_revoke_invite`,
  `group_accept_invite`, and `group_setting_update`.
- Added Baileys-compatible aliases for the common chat, presence, profile,
  privacy, blocklist, and group methods.
- Added group metadata and participant result parsers plus stable
  `groups.update`, `group-participants.update`, and `chats.update` emissions
  from successful product API calls.
- Offline tests cover query node builders, parsers, aliases, presence nodes,
  typed validation, and store/event integration for the new API surfaces.
- Live Phase 5 read-only checks are proven through `scripts/phase5_live_probe.py`
  for privacy settings, profile picture lookup, blocklist, `on_whatsapp`, group
  metadata, and group invite code lookup.
- Presence writes are proven through `scripts/phase5_write_probe.py` for
  available, unavailable, composing, paused, and recording states.
- Added `scripts/phase5_mutation_probe.py` for explicit live mutation checks
  across group settings, invite revoke, participant promote/demote, chat
  patches, profile updates, and profile picture updates.
- Added Baileys-style encrypted app-state patch encoding for chat/profile-name
  mutations, including app-state key-share ingestion, LT hash update,
  SyncActionData encryption, content/snapshot/patch MACs, and persisted
  per-collection sync versions.
- Group announcement mode change/revert, invite revoke, participant promote,
  and participant demote are live-proven against the dedicated test group.
- Profile status and profile picture update are live-proven.
- Profile name and chat patch mutations are offline-covered through the
  encrypted app-state patch builder. The current saved live session still lacks
  `myAppStateKeyId`; a fresh app-state key share or first-history sync with
  the new handler active is needed before live patch writes can pass.

## Live Harness

- `scripts/product_qr_pairing_probe.py` covers QR pairing and saved reconnect.
- `scripts/product_pairing_code_probe.py` covers phone-number pairing-code
  linking and saved credential persistence.
- `scripts/product_inbound_probe.py` covers live 1:1 and group inbound message
  proof.
- `scripts/product_soak_probe.py` keeps a saved-auth product socket online for
  timed reconnect/receive-loop checks.
- `scripts/send_text_probe.py` covers product outbound text send probes.
- `scripts/send_image_probe.py` covers product outbound image send probes.
- `scripts/message_content_probe.py` covers reaction add/remove, edit, and
  delete probes.
- `scripts/send_media_probe.py` covers reusable product media send/download
  probes for generated or file-backed media samples.
- `scripts/phase5_live_probe.py` covers read-only profile/privacy/blocklist/group
  metadata probes.
- `scripts/phase5_write_probe.py` covers explicit Phase 5 write flows (presence,
  profile name/status, and group participant updates) with a required `--apply`
  confirmation flag.
- `scripts/phase5_mutation_probe.py` covers broader explicit Phase 5 mutation
  flows and reports per-operation success or server/client errors.

## Current Verification

- Offline compile check passes for `src`, `scripts`, and `examples`.
- Offline test suite passes with 112 tests.
- WABinary token and WAProto generated artifact checks pass.
- Product QR pairing and saved reconnect pass against the dedicated test
  account.
- The latest live run proves QR pairing, saved reconnect, third-party USync
  device/session assertion, direct text send with ACK, group text send with
  ACK, reaction/edit/delete operations with ACK, image/document/sticker
  send/download, video/audio send/download from file fixtures, Phase 5
  read-only profile/privacy/blocklist/on-whatsapp/group checks, all supported
  presence write states, group setting/invite/participant mutations, profile
  status update, and profile picture update.
- Live chat patch/profile-name writes currently stop at missing app-state key
  material in the saved session, not at patch encoding.
- Public docs are kept to relative repository paths and avoid local machine
  setup details.
