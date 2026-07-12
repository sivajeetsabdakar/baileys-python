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
| 4 | Outbound messages and media breadth | Done |
| 5 | Chats, profile, privacy, groups | Done |
| 6 | History and app-state completeness | Done |
| 7 | Business, newsletters, communities, edge surfaces | Done with deferred live-proof Todos |
| 8 | Core beta release hardening | In progress |
| 9 | Full parity hardening | Not started |

## Release Strategy

Ship a core beta before full parity once auth, sockets, events, common
send/receive, media, groups, profile/privacy, docs, examples, and live smoke
tests are stable.

## Design References

- `docs/architecture-design.md` defines the target package layers, event
  taxonomy, and error model.
- `docs/storage-design.md` defines the durable auth, signal-key, app-state,
  LID/PN mapping, replay, and event-store plan.
- `docs/inbound-processing-design.md` defines the remaining message decrypt,
  content normalization, retry, device-change, and store integration plan.
- `docs/live-verification-design.md` defines the live suite, account-gated
  capability tracking, and probe result format.
- `docs/release-hardening-design.md` defines Phase 8 and Phase 9 release gates,
  packaging checks, observability, and hardening backlog.
- `docs/release-checklist.md` gives the maintainer checklist for core-beta
  release candidates.

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
- Added atomic JSON writes for built-in credential and directory signal-key
  stores, plus `AuthState.transaction()` for all-or-nothing credential updates.
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

## Phase 4 Delivered

- Added product outbound APIs on `WhatsAppClient`: `send_message`,
  `relay_message`, `download_media_message`, and `send_media_message`.
- Added Baileys-style aliases `sendMessage`, `relayMessage`,
  `downloadMediaMessage`, and `sendMediaMessage`.
- Promoted the proven text send path into the product client, including direct
  sends, group/USync fanout, Signal session assertion, credential persistence
  after successful relay, and recent outbound replay for retry receipts.
- Added message content builders for text, extended text, mentions, quote keys,
  reactions, edit, delete, location, contact, contact-list, poll, pin, and
  unpin messages.
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
- Location, contact, poll, pin, and unpin sends are live-proven with ACK
  through `scripts/message_content_probe.py --include-extra`.
- Image, video, audio, document, and sticker send/download/decrypt are
  live-proven with ACK using generated samples and file-backed fixtures.

## Phase 5 Delivered

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
- Block/unblock is live-proven against a disposable peer. The product client
  resolves PN contacts to LID blocklist entries through USync, sends `pn_jid`
  for block writes, and restores the contact after the cycle.
- Group subject and description set/revert are live-proven against the
  dedicated test group. Description updates fetch metadata first and send the
  previous description id to avoid server conflicts.
- Group metadata preserves PN mappings for LID participants so probes and
  callers can match either address form.
- Profile name, profile status, and profile picture updates are live-proven.
- Chat archive, mute, pin, and star mutations are live-proven on a refreshed
  saved session with app-state keys.
- Fresh QR pairing, app-state snapshot request, external app-state blob
  download/decrypt, snapshot metadata decode, app-state key-share ingestion,
  and full app-state replay are live-proven through
  `scripts/app_state_key_probe.py`.
- Group participant remove is live-proven against the dedicated test group.
  Raw participant add remains account-gated in the current live account with
  `account_reachout_restricted`; `group_participants_update_or_invite` now
  falls back to a structured group invite message, and structured invite send is
  live-proven with ACK. Temporary group create does not return a response before
  timeout or leave a created group in the participating list. Product APIs now
  raise explicit IQ errors for server-side rejections instead of returning empty
  success results.

## Phase 6 Delivered

- Added `WhatsAppClient.fetch_app_state_snapshots()` /
  `fetchAppStateSnapshots` for app-state collection snapshot requests.
- App-state snapshot extraction now downloads and decrypts external
  `md-app-state` blobs, decodes snapshot version/record/key metadata, and
  persists blocked collection -> missing key id state in saved credentials.
- App-state snapshot mutation decode now validates content/index MACs,
  decrypts `SyncActionData`, applies LT hash/index-map updates, exposes typed
  decoded mutations, and preserves missing-key errors so blocked collections
  can be retried after key-share delivery.
- App-state sync application now extracts snapshots and inline/external patch
  nodes from sync responses, downloads external mutation blobs, validates patch
  and snapshot MACs, persists per-collection LT hash state, and emits decoded
  mutation events from `WhatsAppClient.sync_app_state()` /
  `syncAppState`.
- History sync processing now inflates inline bootstrap payloads, downloads
  and decrypts `md-msg-hist` payloads, parses `HistorySync` chats, contacts,
  messages, LID/PN mappings, push names, and binds `messaging-history.set`
  into the in-memory store.
- History blob download now maps history notification `fileLength` onto
  `ExternalBlobReference.fileSizeBytes`, matching the generated WAProto field
  names used by current live history notifications.
- Live saved-session proof received and processed a
  `HISTORY_SYNC_NOTIFICATION` push-name sync with 14 contacts and no history
  processing errors.
- Fresh QR live proof received `APP_STATE_SYNC_KEY_SHARE` for key `AAAAAP9V`,
  persisted the key, decoded and applied all five core app-state collections,
  and emitted 311 decoded mutations across `critical_block`,
  `critical_unblock_low`, `regular`, `regular_high`, and `regular_low`.
- Saved reconnect with the refreshed session re-applies all five app-state
  collections with zero blocked collections, zero decrypt errors, and zero
  history processing errors.
- Re-verification through `scripts/app_state_key_probe.py --sync-app-state`
  applied all five app-state collections on a saved session without blocked
  collections, decrypt errors, or history processing errors.

## Phase 7 Delivered

- Added WAM binary telemetry encoding primitives with Pythonic
  `encode_wam` and Baileys-style `encodeWAM` aliases. The encoder supports the
  Node WAM packet header, globals, event ids, property ids, compact integer
  values, strings, floats, and validation errors.
- Added generated WAM constants from the local Node Baileys reference with
  `scripts/generate_wam_constants.py --check`. The package artifact currently
  contains 313 event specs and 48 global ids.
- Added `send_wam_buffer` / `sendWAMBuffer` and `send_wam` / `sendWAM` for the
  Node-compatible `w:stats` upload stanza.
- Added MEX query helpers and response parsing for `w:mex` GraphQL stanzas,
  including typed `MexError` failures for server-side GraphQL errors.
- Added business/profile commerce APIs on `WhatsAppClient`: business profile
  fetch/update, catalog reads, collection reads, order details, product create,
  product update, product delete, cover-photo update, and cover-photo remove,
  with Baileys-compatible aliases.
- Added product/catalog node builders and parsers for catalog results, product
  mutations, product delete responses, product review status, uploaded product
  image URLs, origin-country compliance, and retailer IDs.
- Added catalog product image upload preparation through the product create and
  update paths using the raw product-catalog image upload endpoint.
- Added newsletter/MEX APIs for create, update, metadata, follow, unfollow,
  mute, unmute, subscribers, admin count, ownership/demote/delete operations,
  picture update/remove, reactions, message fetch, and live-update subscription, with
  Baileys-compatible aliases.
- Added newsletter notification processing for reaction, view, participant, and
  settings events from direct newsletter notifications and legacy MEX
  newsletter notifications.
- Added community APIs for metadata, create, linked group create/link/unlink,
  linked group fetch, leave, subject/description updates, participants update,
  membership-request list/update, invite fetch/revoke/accept/v4/info,
  ephemeral mode, settings, member-add mode, and join-approval mode, with parsers and
  Baileys-compatible aliases.
- Added Node-compatible group aliases for invite-info lookup, ephemeral toggle,
  member-add mode, and join-approval mode.
- Added Node-compatible privacy setter aliases for messages, calls, last seen,
  online, profile picture, status, read receipts, and group-add controls.
- Added call helpers for call reject and call-link creation.
- Added label app-state patch helpers for label edit, chat label association,
  and message label association through `chat_modify`, plus common
  Baileys-style aliases.
- Added contact and quick-reply app-state patch helpers with common
  Baileys-style aliases.
- Added reporting-token helpers for protobuf field filtering, message-secret
  key derivation, and `reporting/reporting_token` node generation.
- Added privacy-token helpers for trusted-contact token storage, expiry
  checks, issuance JID resolution, and `tctoken` node construction.
- Added public wrappers for low-level session assertion, generic USync queries,
  bot-list discovery, trusted-contact privacy-token issuance, group member
  labels, peer-data operation messages, message capping aliasing, and app-state
  resync aliasing.
- Added additional Node-compatible socket methods for status fetch,
  disappearing-duration fetch, presence subscription, batch receipts, dirty-bit
  cleanup, default disappearing mode, link-preview privacy, and starred
  message patches.
- Added public wrappers for media connection refresh, current media host,
  media upload, and USync device discovery.
- Expanded generic USync result parsing for contact, status, disappearing
  mode, username, bot profile, side-list, and unknown protocol child values.
- Added typed WAUSync parser helpers for contact, status, disappearing mode,
  username, and bot profile results, plus a shared generic query builder.
- Added `scripts/phase7_live_probe.py` for read-only live checks of catalog,
  MEX reachout/message-capping, newsletter metadata, community metadata, and
  optional WAM stats upload.
- Offline tests cover WAM encoding, MEX response parsing, newsletter query
  shapes, newsletter live-event parsing and dispatch, business/catalog/product
  nodes, catalog product image preparation, community nodes/parsers, label
  app-state patches, reporting tokens, privacy tokens, status/disappearing
  USync parsers, typed WAUSync protocol parsers, generic USync wrapper shapes, bot-list parsing, privacy-token
  issuance, peer-data/member-label protocol messages, presence subscription,
  contact and quick-reply app-state patches, batch receipt aggregation,
  media/USync wrappers, media retry request/response crypto,
  `updateMediaMessage`, public exports, client aliases, and the public API
  parity manifest.
- Live Phase 7 proof currently confirms WhatsApp Business QR pairing, saved
  reconnect, business profile fetch, catalog read, temporary product
  create/delete using an existing catalog image, reversible product update, and
  temporary product create/delete using a freshly generated raw-upload image.
  Fresh catalog image uploads use the Node-compatible direct-path media URL and
  recover by unique catalog name if the server applies the create but does not
  return the mutation IQ before timeout. Cover-photo update/remove, newsletter
  create/metadata/delete, bot-list fetch, trusted-contact privacy-token
  issuance, and a self peer-data operation with ACK are also live-proven.
  Message-capping MEX currently returns a server GraphQL bad request for this
  account/request shape. Collections, community create, and WAM stats upload are
  wired but time out waiting for server IQ responses on this account; the
  community create attempt did not leave a participating community behind.
- Deferred Phase 7 live-proof Todos are collections, order details, community
  metadata/mutation proof, WAM upload ACK, newsletter event proof, and broader
  account-gated WAUSync/media-retry edge surfaces. These are tracked as
  account/data-gated live proof rather than blocking core beta hardening.

## Phase 8 In Progress

- Added `scripts/release_gate.py` as the local core-beta release gate runner.
  It runs compile, pytest, generated WABinary/WAProto/WAM checks, public-docs
  hygiene, import smoke, package build, and clean wheel install smoke.
- Added `scripts/live_suite.py` to run selected read-only and explicit write
  probes with redacted JSON summaries.
- Added configurable `baileys` logger helpers and socket lifecycle/query/node
  log hooks with redacted node summaries.
- Refreshed examples for saved-auth login, no-network pairing-code node
  construction, and a small inbound echo bot. The release gate now runs the
  no-network example smoke test.
- Added `docs/release-checklist.md` for core-beta candidate review.
- Added shared public error bases, preserving existing `ValueError` and
  `RuntimeError` compatibility for current public exceptions.
- Added a public replay-store interface, default in-memory replay store, and
  BinaryNode JSON conversion helpers. Retry replay now uses the replay store
  instead of being hard-wired to the socket instance cache.
- Phase 8 now treats the deferred Phase 7 live-proof items as Todo evidence
  gaps, not core-beta blockers, as long as gated cases report cleanly and the
  compatibility matrix stays explicit.
- Next Phase 8 targets are deeper API-specific typed errors, optional SQLite
  auth/store prototype, and release soak planning.

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
- `scripts/app_state_key_probe.py` covers product app-state snapshot
  fetch/decrypt diagnostics, app-state sync application, blocked-key
  persistence, history event visibility, and app-state sync-key request probes.
- `scripts/phase7_live_probe.py` covers read-only Phase 7 business profile,
  catalog, MEX, newsletter metadata, community metadata, optional WAM stats
  upload checks, explicit temporary catalog create checks, and reversible
  existing-product update checks where the account has the required
  capabilities.
- `scripts/phase7_remaining_probe.py` covers remaining Phase 7 live checks for
  collections, order details, cover-photo update/remove, bot list,
  privacy-token issuance, peer-data operation sends, newsletter create/delete,
  community metadata, and WAM stats.
- `scripts/media_retry_probe.py` covers live media retry request, ACK, and
  optional post-retry download checks when WhatsApp returns a media update.
- `scripts/release_gate.py` runs the core beta release gates for compile,
  tests, generated artifacts, docs hygiene, package build, clean install, and
  import smoke.
- `scripts/live_suite.py` runs selected live probes and writes a redacted JSON
  summary for release evidence.

## Current Verification

- Offline compile check passes for `src`, `scripts`, and `examples`.
- Offline test suite passes with 160 tests.
- WABinary token, WAM constants, and WAProto generated artifact checks pass.
- Product QR pairing and saved reconnect pass against the dedicated test
  account.
- The latest live run proves QR pairing, saved reconnect, third-party USync
  device/session assertion, direct text send with ACK, group text send with
  ACK, reaction/edit/delete operations with ACK, image/document/sticker
  send/download, video/audio send/download from file fixtures, Phase 5
  read-only profile/privacy/blocklist/on-whatsapp/group checks, all supported
  presence write states, group setting/invite/participant mutations, profile
  status update, profile picture update, fresh app-state key-share delivery,
  and saved reconnect app-state replay.
- Live app-state key-share delivery and replay are proven on a freshly linked
  saved session. Profile-name/chat patch write probes can now be retried
  against that refreshed session.
- Latest Phase 6 re-verification applied all five saved app-state collections
  without blocked collections, decrypt errors, or history processing errors.
- Latest Phase 7 probe confirms WhatsApp Business QR pairing, saved reconnect,
  business profile fetch, catalog read, temporary product create/delete using an
  existing catalog image, temporary product create/delete using a freshly
  generated raw-upload image, reversible product update, cover-photo
  update/remove, newsletter create/metadata/delete, bot-list fetch, trusted-contact
  privacy-token issuance, self peer-data operation with ACK, and account
  reachout timelock MEX access. Collections, community create, and WAM stats
  timed out waiting for server responses on the current account; the community
  create attempt did not leave a participating community behind. Order-details
  proof needs a real order id/token, and community metadata proof needs a
  community JID or a safe enabled-account mutation flow.
- Latest media retry probe captures inbound peer image media and receives a
  server ACK for the retry receipt. The final encrypted media-update response
  still depends on WhatsApp returning a reupload for unavailable media.
- Public docs are kept to relative repository paths and avoid local machine
  setup details.
