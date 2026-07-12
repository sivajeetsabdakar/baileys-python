# Live Verification Design

Offline vectors prove deterministic protocol behavior. Live verification proves
that the current WhatsApp account, server rollout, and device state accept the
wire shapes. Both are required for parity claims.

## Principles

- Live checks should be explicit and opt-in.
- Mutating checks should require a clear confirmation flag.
- Account-gated failures should be recorded as gated, not as package failures.
- Probes should print concise machine-readable evidence.
- Public docs should summarize capability state, not machine-specific output.
- A failed live capability should identify whether the failure is local,
  transport-level, server-rejected, account-gated, or condition-gated.

## Accounts

Minimum useful setup:

- one linked account for the product socket.
- one peer account for 1:1 sends, receives, media, reactions, and block tests.
- one test group containing the linked account and the peer.

Extended setup:

- a business-enabled account for catalog/product/order APIs.
- a newsletter-enabled account for newsletter/MEX mutations and events.
- a community-enabled account for community surfaces.
- an old media sample that can trigger media retry reupload.

## Probe Categories

### Read-Only

Read-only probes can run by default:

- saved reconnect.
- profile picture lookup.
- privacy fetch.
- blocklist fetch.
- group metadata.
- catalog fetch.
- newsletter metadata.
- community metadata.
- WAM stats upload when explicitly enabled.

### Reversible Writes

Reversible writes require `--apply`:

- presence changes.
- profile status set and restore.
- profile picture set and restore.
- group subject set and restore.
- group description set and restore.
- group announcement setting set and restore.
- mute/archive/pin/star patch set and restore.

### Potentially Disruptive Writes

These require a dedicated target and should never run against a personal
contact by accident:

- block/unblock.
- participant add/remove/promote/demote.
- group create/leave.
- newsletter create/delete.
- community create/delete.
- catalog product create/update/delete.

## Result Format

Each probe should print:

- `CHECK name=... status=pass`
- `CHECK name=... status=fail reason=...`
- `CHECK name=... status=gated reason=...`
- `CHECK name=... status=pending reason=...`

Where possible, include:

- message id.
- JID type, not private display names.
- server status code.
- server reason.
- ACK state.
- event count.

## Live Suite

Target command shape:

```powershell
python scripts/live_suite.py --creds-path auth/product_qr_creds.json --peer-jid 123@s.whatsapp.net --group-jid 123@g.us
```

Planned groups:

- `auth`: saved reconnect, logout dry-run checks, prekey maintenance read.
- `inbound`: text, group text, media receive, receipts, reactions.
- `outbound`: text, group text, content builders, media send/download.
- `phase5`: profile, privacy, presence, group operations.
- `phase6`: app-state snapshot, history sync, saved reconnect replay.
- `phase7`: business, newsletter, community, WAM, peer-data surfaces.
- `soak`: long-running reconnect and receive-loop stability.

The first version can wrap existing scripts and normalize their outputs. Later
versions can use pytest markers.

Use the soak wrapper for release evidence:

```powershell
python scripts/soak_suite.py --duration 3600
```

## Gated Capability Tracking

The live suite should emit a JSON summary:

```json
{
  "passed": [],
  "failed": [],
  "gated": [],
  "pending": []
}
```

The compatibility matrix should only move a row to `Done` when:

- offline tests cover the builder/parser/state path.
- live proof exists or the capability is inherently offline-only.
- account-gated failures are documented if live proof cannot run.

## Media Retry

Media retry is condition-gated:

- fresh media can prove receive, request construction, and ACK.
- encrypted `messages.media-update` needs WhatsApp to return a reupload.
- the best trigger is old or unavailable media that still exists on a primary
  device.

Until that condition is available, keep the status as partial and record the
ACK proof.

## Acceptance

- Existing live probes keep working.
- `live_suite.py` can run read-only checks without changing account state.
- `--apply` gates every write operation.
- JSON summary is stable enough for CI artifacts.
- Matrix updates are based on suite output, not memory of previous runs.
