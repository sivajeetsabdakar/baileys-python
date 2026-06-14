# Baileys Compatibility Matrix

Target reference: local Node Baileys `7.0.0-rc13`.

Legend:

- `Done`: implemented in `Baileys-python` and covered by tests or proven spike
- `Seeded`: copied from proven spike, needs production API hardening
- `Partial`: some capability exists, parity incomplete
- `Todo`: not implemented in product package yet

| Area | Capability | Status | Notes |
| --- | --- | --- | --- |
| Core | WAProto generated Python classes | Seeded | Generated artifact copied from spike. |
| Core | Tokenized WABinary encode/decode | Seeded | Includes dictionary tokens, packed nibbles/hex, AD/FB/interop JIDs. |
| Core | JID utilities | Partial | Basic encode/decode exists; full Baileys JID helpers still needed. |
| Core | Defaults/version constants | Partial | Protocol constants exist across modules; central defaults module needed. |
| Core | WAM telemetry encoder | Todo | Not ported. |
| Core | WAUSync protocol builders | Partial | Device discovery exists; full protocol set needed. |
| Auth | Credential generation | Seeded | Registration payload and key material implemented. |
| Auth | QR pairing | Seeded | Proven in spike; needs product API integration. |
| Auth | Pairing-code flow | Seeded | Companion hello live-proven, finish bundle offline-tested. |
| Auth | Saved auth login/reconnect | Seeded | `WhatsAppWebClient` supports saved-auth login. |
| Auth | Multi-file auth state | Todo | Product storage interface needed. |
| Auth | Signal key store and transactions | Partial | JSON hydration/export exists; production store API needed. |
| Auth | Prekey upload/digest/rotation | Seeded | Node builders and live proof exist in spike. |
| Auth | Routing info | Seeded | WebSocket `ED` and Noise intro supported. |
| Auth | LID/PN mapping | Partial | USync and history mapping need production store integration. |
| Socket | Noise handshake | Seeded | Live server hello/login proven. |
| Socket | Query/response correlation | Todo | Scripts have ad hoc waits; product query manager needed. |
| Socket | Event emitter | Todo | Required for Baileys-style events. |
| Socket | Keepalive/reconnect | Partial | Saved-auth reconnect proven; auto reconnect manager needed. |
| Socket | Logout/disconnect reasons | Todo | Not implemented. |
| Inbound | Binary node dispatcher | Todo | Classifier exists; full dispatcher needed. |
| Inbound | Message decrypt | Seeded | 1:1 pkmsg/msg and group skmsg paths exist. |
| Inbound | Retry receipts | Seeded | Offline node/session behavior tested. |
| Inbound | Notifications/calls/offline nodes | Partial | Classification exists; processors needed. |
| Outbound | `sendMessage` text | Partial | Direct and USync fanout text proven in spike. |
| Outbound | `relayMessage` | Todo | Needs production API and group/newsletter paths. |
| Outbound | Receipts/read messages | Todo | Node builders needed. |
| Outbound | Privacy tokens/peer data operations | Todo | Not ported. |
| Messages | Text/extended text | Partial | Basic text exists. |
| Messages | Quote/mention/forward/location/contact/reaction/pin/poll/edit/delete | Todo | Content generation needed. |
| Media | Image upload/send/download | Seeded | Live-proven image path. |
| Media | Video/audio/document/sticker/stream/url inputs/thumbnails/reupload | Todo | Not ported. |
| Chats | Presence/status/profile/privacy/blocklist/chat modify | Todo | Not ported. |
| History | History sync/app-state/LTHash/MAC validation | Partial | Key derivation exists; full sync pipeline needed. |
| Store | In-memory store and buffered events | Todo | Not ported. |
| Groups | Metadata/create/participants/invites/settings | Todo | Only group probing exists. |
| Communities | Community APIs | Todo | Not ported. |
| Business | Profile/catalog/products/orders | Todo | Not ported. |
| Newsletters | MEX/newsletter APIs/events | Todo | Not ported. |
| Tooling | Package install/tests/examples | Done | Product bootstrap provides baseline install and tests. |
| Tooling | Live test harness | Partial | Spike probes copied into product `scripts/`; pytest-style live suite still needed. |
| Docs | Migration guide/API docs | Todo | README and matrix only. |
