# Release Hardening Design

Phase 8 should turn the current package into a dependable core beta. Phase 9
should close the remaining full-parity gaps and keep the project maintainable
as WhatsApp changes.

## Core Beta Scope

Core beta should include:

- QR pairing.
- pairing-code linking.
- saved reconnect.
- logout.
- reconnect and keepalive handling.
- query correlation.
- event emitter.
- inbound 1:1 and group text.
- receipts and ACKs.
- common outbound messages.
- common media send/download.
- profile, privacy, presence, and groups.
- history and app-state sync.
- in-memory store.
- built-in file-backed auth stores.
- public API and migration docs.

Core beta does not need every account-gated Phase 7 mutation, but it must
report unsupported or gated cases clearly.

## Release Gates

Every release candidate should pass:

- compile check for `src`, `scripts`, and `examples`.
- full pytest suite.
- WABinary generated artifact check.
- WAProto generated artifact check.
- WAM generated artifact check.
- docs hygiene scan.
- package build.
- clean install smoke test.
- import smoke test.
- selected examples.
- read-only live suite where credentials are available.
- write live suite only with explicit target confirmation.

## CI Layout

Recommended jobs:

- `lint-docs`: docs hygiene and generated artifact checks.
- `test`: pytest on supported Python version.
- `package`: build wheel and sdist.
- `examples`: run no-network examples and import checks.
- `live-readonly`: optional, credential-gated.
- `live-write`: manual only.

The default CI path should never require WhatsApp credentials.

## Versioning

Suggested pre-release path:

- `0.1.0a0`: current internal alpha state.
- `0.1.0a1`: storage design and live-suite wrapper started.
- `0.1.0b0`: core beta with release gates passing.
- `0.1.x`: compatibility fixes and additional live proof.
- `0.2.0`: durable storage adapters and broader Phase 7 proof.

Do not mark a parity area as complete only because the method exists. Use the
compatibility matrix status rules.

## Packaging

Package must include:

- generated WAProto Python module.
- generated WABinary token JSON.
- generated WAM constants JSON.
- typed public modules.
- no auth files.
- no local live-output artifacts.
- no probe-generated media files.

Source distributions should be buildable without regenerating proto files.

## Observability

The client should support configurable logging without printing secrets:

- connection state.
- query ids and tags.
- node classes, not raw encrypted payloads.
- retry counts.
- disconnect reasons.
- server IQ error status/reason.
- live-suite summary.

Secrets to avoid logging:

- auth credentials.
- Signal session records.
- prekeys and signed-prekeys.
- app-state keys.
- media keys.
- QR pairing secret components.
- full phone numbers in public docs.

## Deprecation Policy

- Keep camelCase aliases for Node Baileys migration.
- Prefer adding Pythonic names instead of removing aliases.
- If a wire shape changes, keep old parser behavior where possible and add a
  compatibility vector.
- Public dataclass fields should not be removed in patch releases.

## Hardening Backlog

Phase 8:

- code hardening complete; keep release evidence current while preparing beta
  candidates.

Phase 9:

- SQLite event store.
- Postgres adapter.
- broader Phase 7 enabled-account live proof.
- media retry success proof when eligible media is available.
- full peer-data operation live coverage.
- expanded WAM live ACK proof.
- nightly live read-only suite.
- 24-hour reconnect soak.
- compatibility matrix audit against the current Node reference.

## Acceptance

Core beta can be released when:

- release gates pass.
- read-only live suite passes or records account-gated checks cleanly.
- write live suite passes against dedicated targets.
- docs explain install, auth, send/receive, media, groups, store, and migration.
- compatibility matrix has no stale or overclaimed statuses.
- package install works in a fresh environment.
