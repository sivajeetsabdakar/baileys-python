<div align="center">

<pre>
██████╗  █████╗ ██╗██╗     ███████╗██╗   ██╗███████╗      ██████╗ ██╗   ██╗
██╔══██╗██╔══██╗██║██║     ██╔════╝╚██╗ ██╔╝██╔════╝      ██╔══██╗╚██╗ ██╔╝
██████╔╝███████║██║██║     █████╗   ╚████╔╝ ███████╗█████╗██████╔╝ ╚████╔╝
██╔══██╗██╔══██║██║██║     ██╔══╝    ╚██╔╝  ╚════██║╚════╝██╔═══╝   ╚██╔╝
██████╔╝██║  ██║██║███████╗███████╗   ██║   ███████║      ██║        ██║
╚═════╝ ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝   ╚═╝   ╚══════╝      ╚═╝        ╚═╝
</pre>

# Baileys Python

Async Python package for WhatsApp Web protocol surfaces, inspired by Node
Baileys.

[![PyPI](https://img.shields.io/pypi/v/baileys-python?color=2ea44f)](https://pypi.org/project/baileys-python/)
[![Python](https://img.shields.io/pypi/pyversions/baileys-python)](https://pypi.org/project/baileys-python/)
[![License](https://img.shields.io/github/license/sivajeetsabdakar/baileys-python)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-github.io-0f766e)](https://sivajeetsabdakar.github.io/baileys-python/)
[![Build](https://img.shields.io/github/actions/workflow/status/sivajeetsabdakar/baileys-python/docs.yml?label=docs)](https://github.com/sivajeetsabdakar/baileys-python/actions)

[Install](#install) ·
[Quickstart](https://sivajeetsabdakar.github.io/baileys-python/quickstart/) ·
[API Examples](https://sivajeetsabdakar.github.io/baileys-python/examples/) ·
[Feature Status](https://sivajeetsabdakar.github.io/baileys-python/feature-status/) ·
[Contributing](CONTRIBUTING.md)

</div>

> Alpha release: start with a dedicated test account and review the feature
> status before using this package in a production service.

<p align="center">
  <img
    src="https://raw.githubusercontent.com/sivajeetsabdakar/baileys-python/main/docs/assets/readme-overview.svg"
    alt="Baileys Python architecture overview"
    width="100%"
  />
</p>

## Install

```powershell
python -m pip install baileys-python
```

```python
from baileys import WhatsAppClient, make_socket
```

## What Works Today

| Area | Capabilities |
| --- | --- |
| Auth and sockets | QR pairing, saved auth reconnect, keepalive, logout, disconnect reasons, async event emitter |
| Messaging | send/receive text, common message builders, replies, mentions, reactions, edits, deletes, retry replay |
| Media | image, video, audio, document, and sticker send/download/decrypt helpers |
| Events and store | message, receipt, chat, contact, group, presence, call, notification, dirty, and offline events |
| Account APIs | chat, profile, privacy, presence, blocklist, and group method surfaces |
| Persistence | in-memory, SQLite, and Postgres auth/event/replay store surfaces |
| Protocol foundation | generated WAProto, WABinary tokens, Noise, Signal wrappers, crypto, media/app-state keys |
| Migration | Pythonic async methods plus common Baileys-compatible aliases |

Some WhatsApp features are account-gated or rollout-dependent. Unsupported or
rejected server behavior is surfaced through typed errors instead of being
silently hidden.

## Flow

```text
Python app
   |
   v
WhatsAppClient / make_socket
   |
   +-- AuthState and Signal keys
   +-- EventEmitter and optional store
   +-- WABinary, WAProto, Noise, Signal, media crypto
   |
   v
WhatsApp Web socket
```

## Minimal Saved-Auth Login

```python
import asyncio
from pathlib import Path
from baileys import WhatsAppWebClient


async def main() -> None:
    async with WhatsAppWebClient(Path("auth/live_pair_creds.json")) as client:
        success = await client.wait_for_success(timeout=60)
        print(success.attrs)


asyncio.run(main())
```

## Send A Message

```python
import asyncio
from baileys import make_socket


async def main() -> None:
    client = make_socket("auth/product_qr_creds.json")

    try:
        await client.connect_and_wait(start_receive_loop=True)
        result = await client.send_message(
            "15551234567@s.whatsapp.net",
            {"text": "hello from Python"},
        )
        print(result.message_id, result.status)
    finally:
        await client.close()


asyncio.run(main())
```

## Documentation

| Link | Description |
| --- | --- |
| [Docs site](https://sivajeetsabdakar.github.io/baileys-python/) | Hosted documentation |
| [Quickstart](https://sivajeetsabdakar.github.io/baileys-python/quickstart/) | Install, connect, send, and receive |
| [API examples](https://sivajeetsabdakar.github.io/baileys-python/examples/) | Auth, messages, media, groups, stores |
| [Public API](https://sivajeetsabdakar.github.io/baileys-python/public-api/) | Current exported API surface |
| [Feature status](https://sivajeetsabdakar.github.io/baileys-python/feature-status/) | Working, alpha, and deferred areas |
| [Migration guide](https://sivajeetsabdakar.github.io/baileys-python/migration-guide/) | Notes for Node Baileys users |
| [Contributing](CONTRIBUTING.md) | Local setup, checks, PR guidance |
| [Changelog](CHANGELOG.md) | Release notes |

## Development

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q
```

Build the documentation site locally:

```powershell
python -m pip install -e ".[docs]"
python -m mkdocs serve
```

Run the full release gate:

```powershell
python scripts/release_gate.py
```

## Safety And Affiliation

This project is unofficial. It is not affiliated with, endorsed by, sponsored
by, or maintained by WhiskeySockets/Baileys, WhatsApp, Meta, or any of their
subsidiaries or affiliates. WhatsApp and related names, marks, emblems, and
images are trademarks of their respective owners.

Use the package responsibly:

- use a dedicated test account first
- keep saved auth state and Signal keys private
- respect recipient consent and opt-out requests
- do not use it for spam or platform enforcement evasion

## License

This package is released under the MIT License. See [LICENSE](LICENSE) and
[NOTICE](NOTICE) for license text, attribution, and affiliation notices.
