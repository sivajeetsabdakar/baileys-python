# Contributing

Thanks for taking the time to contribute to Baileys Python. This project is an
alpha Python package for WhatsApp Web protocol surfaces inspired by
WhiskeySockets/Baileys, so careful testing and clear compatibility notes matter.

## Ways To Help

- Fix bugs in the public async API.
- Improve protocol parity with Node Baileys.
- Add offline vectors for binary nodes, protobuf messages, crypto, media,
  app-state, receipts, retries, and store behavior.
- Improve documentation, examples, and migration notes.
- Add or harden storage adapters.
- Reproduce account-gated WhatsApp behavior with clear logs and minimal test
  cases.

## Ground Rules

- Keep changes scoped to the problem being solved.
- Do not commit credentials, QR images, auth folders, local logs, media captures,
  database URLs, API tokens, or phone-number-specific test artifacts.
- Do not add deceptive automation, spam tooling, enforcement-evasion behavior,
  or features intended to bypass platform safety systems.
- Preserve the unofficial/non-affiliation wording in public docs.
- Prefer Pythonic async APIs while keeping common Baileys-compatible aliases
  where they help migration.
- Add typed errors for unsupported or account-gated behavior instead of hiding
  server rejections.

## Development Setup

Baileys Python currently targets Python 3.12.

```powershell
python -m pip install -e ".[dev]"
```

Optional docs dependencies:

```powershell
python -m pip install -e ".[docs]"
```

Optional Postgres dependencies:

```powershell
python -m pip install -e ".[postgres]"
```

## Local Checks

Run the full release gate before opening a pull request when possible:

```powershell
python scripts/release_gate.py
```

For smaller changes, run the focused checks that match the files touched:

```powershell
python -m compileall -q src scripts examples
python -m pytest -q
python scripts/generate_wabinary_tokens.py --check
python scripts/generate_proto.py --check
python scripts/generate_wam_constants.py --check
```

Docs changes should also pass:

```powershell
python -m mkdocs build --strict
```

Package metadata changes should pass:

```powershell
python -m build
python -m twine check dist/*
```

## Tests

Add offline tests for deterministic behavior. Good test targets include:

- binary node encode/decode behavior
- protobuf encode/decode compatibility
- Signal session and sender-key behavior
- media encryption/decryption
- retry receipt and replay behavior
- socket query correlation and timeout behavior
- event taxonomy and store idempotency
- SQLite and Postgres adapter behavior

Live tests are useful, but they are account-gated and should not be required for
ordinary pull requests. If a change depends on live WhatsApp behavior, document:

- the account capability required
- whether the test is read-only or mutating
- the exact script or example used
- the observed server response
- any deferred proof still needed

## Documentation

Update documentation when a public method, event, option, error, or behavior
changes. Common places to update:

- `README.md` for install and high-level entry points
- `docs/quickstart.md` for first-use flows
- `docs/examples.md` for practical API examples
- `docs/public-api.md` for public method and event surfaces
- `docs/feature-status.md` for alpha/deferred status
- `docs/compatibility-matrix.md` for parity status
- `CHANGELOG.md` and `docs/changelog.md` for release-facing changes

Public docs should avoid local machine paths, private environment details,
credentials, and pasted live account output.

## Pull Request Checklist

Before opening a pull request:

- Keep the diff focused.
- Add or update tests for behavior changes.
- Update docs for public API or behavior changes.
- Run the relevant local checks.
- Confirm generated artifacts are intentionally updated.
- Confirm no auth files, QR images, logs, secrets, or local media are staged.
- Include a concise summary and verification notes in the pull request.

## Compatibility Work

When porting or matching Node Baileys behavior:

- Include the Node reference version or source area used.
- Preserve copyright/license notices for copied or adapted material.
- Prefer structured parsers and builders over ad hoc string handling.
- Keep account-gated behavior observable through typed errors and events.
- Mark live-proof gaps as deferred instead of calling them complete.

## Release Policy

PyPI versions are immutable. Every upload needs a new version in
`pyproject.toml`.

Release-facing changes should update:

- `pyproject.toml`
- `CHANGELOG.md`
- `docs/changelog.md`
- `docs/index.md` when the current public version changes

Run:

```powershell
python scripts/release_gate.py
python -m twine check dist/*
```

Only publish with a PyPI token stored in the local shell or a configured trusted
publishing workflow. Never commit tokens.

## Security And Sensitive Reports

Do not open public issues containing secrets, saved auth state, Signal keys,
database URLs, API tokens, or private phone numbers. Redact sensitive values
before sharing logs.

For security-sensitive reports, open a minimal issue asking for a private
contact path, or use GitHub private vulnerability reporting if it is enabled for
the repository.

## License And Attribution

By contributing, you agree that your contributions are provided under this
repository's MIT License. See `LICENSE` and `NOTICE` for license text,
attribution, and affiliation notices.
