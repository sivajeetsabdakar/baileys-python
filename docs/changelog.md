# Changelog

## 0.1.0a0

First public alpha release.

### Added

- Public PyPI package under `baileys-python`.
- Import package under `baileys`.
- MIT license and attribution notice.
- Python 3.12 package metadata and typed package marker.
- Core async socket API through `WhatsAppClient`, `make_socket`, and
  `makeWASocket`.
- QR pairing, saved reconnect, event emitter, query manager, ACKs, receipts,
  retry replay, and disconnect reason handling.
- Generated WAProto and WABinary package data.
- Message content builders and outbound send APIs.
- Media upload, send, download, and decrypt helpers.
- In-memory, SQLite, and Postgres store surfaces.
- Chat, profile, privacy, presence, group, app-state, history, business,
  newsletter, community, MEX, WAM, reporting, and privacy-token surfaces.
- Release gate covering compile checks, tests, generated artifact checks, docs
  hygiene, status consistency, package build, clean install, and import smoke.

### Known Limitations

- Alpha release. Public API details may still change.
- Some account-gated WhatsApp features can return server rejections.
- Pairing-code live completion depends on account eligibility.
- Long-run soak and live nightly evidence remain deferred release-hardening
  work.
- Full parity with every Node Baileys public surface is tracked in the
  compatibility matrix, not declared complete.
