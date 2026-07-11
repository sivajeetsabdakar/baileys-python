# Baileys Python

`Baileys-python` is the product package for a native Python implementation of
the WhatsApp Web protocol surface provided by Node Baileys.

This repository is being built from the proven feasibility work in
`../baileys-python-test`. The spike remains the lab/reference; this package is
the production implementation target.

## Current State

The product package has live-proven auth, inbound, outbound, media, app-state,
and Phase 5 API foundations:

- installable Python package under `src/baileys`
- generated WAProto and WABinary token package data
- proven crypto, Noise, Signal, WABinary, media, pairing-code, retry, USync, and
  saved-auth client modules copied from the spike
- offline parity tests and minimal public API tests
- examples for saved-auth login and pairing-code request
- compatibility matrix in `docs/compatibility-matrix.md`
- public API guide in `docs/public-api.md`
- migration guide for Node Baileys users in `docs/migration-guide.md`
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

This is not full Baileys parity yet. It is the first product baseline for the
full roadmap.

## Install For Development

```powershell
python -m pip install -e ".[dev]"
```

## Run Tests

```powershell
python -m pytest -q
```

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
for Node Baileys migration notes. See `docs/architecture-design.md` for the
remaining implementation design.
