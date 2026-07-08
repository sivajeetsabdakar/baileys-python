# Baileys Python

`Baileys-python` is the product package for a native Python implementation of
the WhatsApp Web protocol surface provided by Node Baileys.

This repository is being built from the proven feasibility work in
`../baileys-python-test`. The spike remains the lab/reference; this package is
the production implementation target.

## Current State

The product package has live-proven auth/inbound foundations and offline-tested
outbound/chat/group API foundations:

- installable Python package under `src/baileys`
- generated WAProto and WABinary token package data
- proven crypto, Noise, Signal, WABinary, media, pairing-code, retry, USync, and
  saved-auth client modules copied from the spike
- offline parity tests and minimal public API tests
- examples for saved-auth login and pairing-code request
- compatibility matrix in `docs/compatibility-matrix.md`
- live/proof scripts under `scripts/`
- product QR pairing plus saved reconnect through
  `scripts/product_qr_pairing_probe.py`
- product outbound text/media API probes through `scripts/send_text_probe.py`
  and `scripts/send_image_probe.py`
- reusable product content/media probes through
  `scripts/message_content_probe.py` and `scripts/send_media_probe.py`
- product chat, presence, profile, privacy, blocklist, and group method
  surfaces with Baileys-compatible aliases
- encrypted app-state patch encoding plus app-state snapshot fetch/decrypt
  diagnostics, pending live peer key-share response on the saved test session
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
`docs/compatibility-matrix.md` for the public Baileys parity checklist.
