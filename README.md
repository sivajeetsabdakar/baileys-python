# Baileys Python

`Baileys-python` is an async Python package for WhatsApp Web protocol surfaces,
inspired by Node Baileys.

This project is an unofficial Python implementation inspired by
WhiskeySockets/Baileys. It is not affiliated with, endorsed by, sponsored by, or
maintained by WhiskeySockets/Baileys, WhatsApp, Meta, or any of their
subsidiaries or affiliates. WhatsApp and related names, marks, emblems, and
images are trademarks of their respective owners.

This is an alpha release. Start with a dedicated test account and review the
feature status before using it in a production service.

## Install

```powershell
python -m pip install baileys-python
```

## Documentation

- Documentation site: <https://sivajeetsabdakar.github.io/baileys-python/>
- Quickstart: `docs/quickstart.md`
- API examples: `docs/examples.md`
- Feature status: `docs/feature-status.md`
- Contributing: `CONTRIBUTING.md`
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
