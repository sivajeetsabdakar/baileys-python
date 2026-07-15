# Baileys Python

Baileys Python is an async Python package for WhatsApp Web protocol surfaces,
inspired by WhiskeySockets/Baileys.

```powershell
python -m pip install baileys-python
```

```python
from baileys import WhatsAppClient, make_socket
```

The package currently targets Python 3.12 and exposes a Pythonic async API with
common Baileys-style aliases for migration work.

## Important Notice

This project is unofficial. It is not affiliated with, endorsed by, sponsored
by, or maintained by WhiskeySockets/Baileys, WhatsApp, Meta, or any of their
subsidiaries or affiliates. WhatsApp and related names, marks, emblems, and
images are trademarks of their respective owners.

Start with a dedicated test account. Account capabilities, pairing behavior,
business features, newsletters, communities, media retry, and some server-side
APIs can vary by WhatsApp account, platform, and rollout state.

## Start Here

- [Quickstart](quickstart.md): install, connect with saved auth, send text, and
  listen for messages.
- [API Examples](examples.md): auth state, sending, media, groups, profile,
  privacy, SQLite, and Postgres.
- [Feature Status](feature-status.md): what works, what is alpha, and what is
  deferred.
- [Public API](public-api.md): full current API surface.
- [Migration Guide](migration-guide.md): mapping from common Node Baileys usage.

## Current Package

```text
pip install baileys-python
```

Current public alpha:

```text
0.1.0a0
```

The package is useful for controlled development and test-account integrations.
It is not yet a full replacement for every Node Baileys surface in production.
