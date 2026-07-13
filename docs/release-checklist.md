# Release Checklist

Use this checklist before cutting a core-beta build.

## Local Gates

```powershell
python scripts/release_gate.py
```

The release gate covers compile checks, pytest, generated artifact checks,
public-docs hygiene, import smoke, package build, clean wheel install, and the
no-network example smoke test.

Check the local Node parity audit when the Node checkout or public manifest
changes:

```powershell
python scripts/audit_node_public_api.py --node-root ../Baileys-master/Baileys-master
```

## Live Evidence

Run the read-only live summary when saved credentials are available:

```powershell
python scripts/live_suite.py --include-remaining --skip-collections
```

Run write checks only after confirming the target account or group:

```powershell
python scripts/live_suite.py --include-write --to 120363000000000000@g.us
```

Keep the JSON summary as local release evidence. Update
`docs/compatibility-matrix.md` only with stable capability status, not pasted
machine-specific output.

Run a short soak before a candidate build:

```powershell
python scripts/soak_suite.py --duration 3600
```

Run the longer soak before marking the core beta ready:

```powershell
python scripts/soak_suite.py --duration 86400
```

## Manual Review

- Confirm `docs/compatibility-matrix.md` has no stale Done entries.
- Confirm account-gated Todos remain explicit.
- Confirm examples use relative paths.
- Confirm no auth files, generated QR images, local logs, or probe media are
  staged.
- Confirm public docs avoid local setup details.
- Confirm the current branch is clean before tagging or publishing.

## Core-Beta Notes

Core beta can ship with account-gated Phase 7 proof marked as Todo when the
wire implementation is present, offline tests pass, and live probes report the
server limitation clearly.
