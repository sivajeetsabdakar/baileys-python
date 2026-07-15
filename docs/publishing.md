# Publishing

Use this flow to publish a public package build.

## Preflight

Confirm the distribution name is still available before the first upload:

```powershell
python -m pip index versions baileys-python
```

Run the full local release gate:

```powershell
python scripts/release_gate.py
```

Review the package metadata:

```powershell
python -m twine check dist/*
```

## TestPyPI

Set a TestPyPI token in the shell where the upload will run:

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "<testpypi-token>"
python -m twine upload --repository testpypi dist/*
```

Install the TestPyPI build in a clean environment:

```powershell
python -m pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ baileys-python
python -c "from baileys import WhatsAppClient; print(WhatsAppClient.__name__)"
```

## PyPI

Use a scoped PyPI project token when possible:

```powershell
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "<pypi-token>"
python -m twine upload dist/*
```

After upload, confirm the public install path:

```powershell
python -m pip install baileys-python
python -c "import baileys; print(baileys.__name__)"
```

## Release Notes

- Keep generated auth files, QR images, logs, and live probe media out of the
  release commit.
- Update `docs/compatibility-matrix.md` and `docs/deferred-todos.md` before a
  tagged release.
- Update `CHANGELOG.md` and `docs/changelog.md` before publishing a new
  package version.
- Publish alpha builds while account-gated compatibility items remain marked as
  Todo.

## Documentation Site

The documentation site is built with MkDocs Material and deployed by GitHub
Pages from the `Docs` workflow.

Build locally:

```powershell
python -m pip install -e ".[docs]"
python -m mkdocs build --strict
```

The expected public URL is:

```text
https://sivajeetsabdakar.github.io/baileys-python/
```
