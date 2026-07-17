# Feature Status

Baileys Python is published as an alpha package. It is suitable for controlled
development, test accounts, and applications that can handle account-gated
WhatsApp behavior explicitly.

## Works Now

- Public package install with `pip install baileys-python`.
- Generated WAProto and WABinary token package data.
- Crypto, Noise, Signal session wrappers, media keys, and app-state keys.
- QR pairing, saved auth reconnect, logout, disconnect mapping, keepalive, and
  query correlation.
- Event emitter with stable socket, message, receipt, chat, contact, group,
  notification, call, dirty, and offline events.
- In-memory store plus SQLite and Postgres store adapters.
- Text sends, group text sends, retry replay cache, receipts, and read state.
- Media upload, send, download, and decrypt for common media types.
- Chat, presence, profile, privacy, blocklist, and group method surfaces.
- App-state snapshot and patch helpers.
- Business, newsletter, community, WAM, privacy-token, reporting, and MEX
  surfaces where account capability allows them.

## Alpha Areas

- WhatsApp server behavior can vary by account, device platform, and rollout.
- Pairing-code live completion depends on account eligibility.
- Some advanced account surfaces are account-gated and may return structured server
  rejections even when the wire shape is implemented.
- Long-run reconnect soak and live nightly evidence are still being expanded.
- Full public API parity with every Node Baileys method is tracked but not
  declared complete.

## Deferred Or Todo

- Longer release soak evidence.
- Account-gated live proof for remaining business, community, newsletter, and
  order flows.
- More durable multi-process session ownership patterns for large deployments.
- Broader live media retry reupload proof when WhatsApp returns encrypted media
  update responses.
- Continued parity auditing as the Node reference changes.

See [Compatibility Matrix](compatibility-matrix.md) and
[Deferred Todos](deferred-todos.md) for detailed status.

## Safety Guidance

- Use a dedicated test account before using a personal or business account.
- Respect recipient consent, opt-out requests, and local messaging rules.
- Do not use the package to spam, evade platform controls, or misrepresent the
  sender.
- Treat saved auth credentials and Signal keys as sensitive secrets.
- Expect WhatsApp to reject, rate-limit, or change behavior for some account
  states.
