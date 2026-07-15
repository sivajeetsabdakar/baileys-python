# Baileys Python

`Baileys-python` is the product package for a native Python implementation of
the WhatsApp Web protocol surface provided by Node Baileys.

This project is an unofficial Python implementation inspired by
WhiskeySockets/Baileys. It is not affiliated with, endorsed by, sponsored by, or
maintained by WhiskeySockets/Baileys, WhatsApp, Meta, or any of their
subsidiaries or affiliates. WhatsApp and related names, marks, emblems, and
images are trademarks of their respective owners.

This repository is being built from the proven feasibility work in
`../baileys-python-test`. The spike remains the lab/reference; this package is
the production implementation target.

## Current State

The product package has live-proven auth, inbound, outbound, media, app-state,
business/catalog, newsletter, and Phase 5 API foundations. Phase 8 core-beta
hardening gates are in place:

- installable Python package under `src/baileys`
- generated WAProto and WABinary token package data
- proven crypto, Noise, Signal, WABinary, media, pairing-code, retry, USync, and
  saved-auth client modules copied from the spike
- offline parity tests and minimal public API tests
- examples for saved-auth login, pairing-code request, and a small echo bot
- compatibility matrix in `docs/compatibility-matrix.md`
- public API guide in `docs/public-api.md`
- migration guide for Node Baileys users in `docs/migration-guide.md`
- release checklist in `docs/release-checklist.md`
- architecture and remaining implementation designs in `docs/architecture-design.md`
- live/proof scripts under `scripts/`
- product QR pairing plus saved reconnect through
  `scripts/product_qr_pairing_probe.py`
- product outbound text/media API probes through `scripts/send_text_probe.py`
  and `scripts/send_image_probe.py`
- reusable product content/media probes through
  `scripts/message_content_probe.py` and `scripts/send_media_probe.py`
- product chat, presence, profile, privacy, blocklist, and group method
  surfaces with Baileys-compatible aliases
- explicit IQ errors for account-side server rejections in public query APIs
- encrypted app-state patch encoding plus product app-state snapshot
  fetch/decrypt diagnostics, blocked-key tracking, live key-share ingestion,
  and app-state replay proof on a freshly linked test session
- `scripts/phase5_live_probe.py` for read-only Phase 5 live validation
- `scripts/phase5_mutation_probe.py` for explicit Phase 5 mutation validation
- `scripts/app_state_key_probe.py` for app-state key and snapshot diagnostics
- `scripts/phase7_live_probe.py` and `scripts/phase7_remaining_probe.py` for
  Phase 7 business, newsletter, community, WAM, privacy-token, bot-list, and
  peer-data proof tracking
- `scripts/live_suite.py` for JSON summaries of selected read-only and explicit
  write live probes
- `scripts/live_suite.py --write-nightly-plan` for scheduled read-only probe
  command planning
- `scripts/soak_suite.py` for timed reconnect/receive-loop soak summaries
- `scripts/release_gate.py` for compile, test, generated artifact, docs,
  package build, clean install, and import smoke checks
- `scripts/release_status.py` for roadmap, matrix, and deferred-proof
  consistency checks
- optional Postgres stores with versioned migration and live database
  integration proof

This is not full Baileys parity yet. Account-gated live proof items are tracked
as explicit Todos in the compatibility matrix while core beta hardening
continues.

## Install

```powershell
python -m pip install baileys-python
```

## Documentation

- Documentation site: <https://sivajeetsabdakar.github.io/baileys-python/>
- Quickstart: `docs/quickstart.md`
- API examples: `docs/examples.md`
- Feature status: `docs/feature-status.md`
- Changelog: `CHANGELOG.md`

## Install For Development

```powershell
python -m pip install -e ".[dev]"
```

Build the documentation site locally:

```powershell
python -m pip install -e ".[docs]"
python -m mkdocs serve
```

## Run Tests

```powershell
python -m pytest -q
```

## Run Release Gates

```powershell
python scripts/release_gate.py
```

## Run Live Suite Summary

```powershell
python scripts/live_suite.py --include-remaining --skip-collections
```

Write probes are opt-in:

```powershell
python scripts/live_suite.py --include-write --to 120363000000000000@g.us
```

## Run Soak Summary

```powershell
python scripts/soak_suite.py --duration 3600
```

## License

This package is released under the MIT License. See `LICENSE` and `NOTICE` for
license text, attribution, and affiliation notices.

## Minimal Saved-Auth Login

```python
import asyncio
from pathlib import Path
from baileys import WhatsAppWebClient

async def main():
    async with WhatsAppWebClient(Path("auth/live_pair_creds.json")) as client:
        success = await client.wait_for_success(timeout=60)
        print(success.attrs)

asyncio.run(main())
```

## Roadmap

See `docs/roadmap.md` for the implementation timeline and
`docs/compatibility-matrix.md` for the public Baileys parity checklist. See
`docs/public-api.md` for the current Python API and `docs/migration-guide.md`
for Node Baileys migration notes. See `CHANGELOG.md` for release notes,
`docs/publishing.md` for the PyPI release flow, and
`docs/architecture-design.md` for the remaining implementation design.
