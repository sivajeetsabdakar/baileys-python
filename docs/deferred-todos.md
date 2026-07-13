# Deferred TODOs

These items are intentionally deferred because they need a specific account
capability, a live server response that did not occur during current probes, or
a longer release-hardening run. They should stay visible until proven or
retired with a clear reason.

## Release Hardening

- Run a real Postgres database integration proof for credential, signal-key,
  replay, event-store, LID/PN, and app-state persistence.
- Add versioned Postgres migrations and explicit multi-writer transaction
  tests before recommending Postgres for multi-process production bots.
- Run the 24-hour reconnect soak before marking the core beta ready.
- Add a nightly live read-only suite once dedicated account scheduling is in
  place.

## Live Proof

- Re-run broader account-gated USync protocol proof on an account that returns
  the relevant protocol payloads.
- Prove media retry through a server/device response that includes the final
  encrypted media update. Current code and offline crypto tests pass; current
  live probe gets the retry ACK but not the final update.
- Prove WAM stats upload on an account/server path that returns a useful ACK.
- Prove newsletter inbound event delivery with a newsletter-enabled account and
  a real inbound event.
- Prove community metadata/mutation flow with a community JID or a safe enabled
  community account flow.
- Re-run raw participant add on an account without the current
  `account_reachout_restricted` limit, while keeping the structured invite
  fallback.

## Account-Gated Business Items

- Keep collections live proof as TODO until a responding business account is
  available.
- Keep order-details live proof as TODO until there is a real order id and
  token.

## Maintenance

- Re-run `scripts/audit_node_public_api.py` when the local Node Baileys
  checkout changes.
- Keep `docs/compatibility-matrix.md` aligned with the latest live evidence;
  do not move account-gated rows to Done without a repeatable proof.
