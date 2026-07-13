from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCS_PATHS = [ROOT / "README.md", ROOT / "docs"]
DOCS_BLOCKLIST = re.compile(r"[A-Z]:\\|/Users/|/home/|\bconda\b|\bAI\b|\bagent\b")


def run_step(name: str, command: list[str], *, cwd: Path = ROOT) -> None:
    print(f"==> {name}", flush=True)
    print(" ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def iter_doc_files() -> list[Path]:
    files: list[Path] = []
    for path in DOCS_PATHS:
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(sorted(item for item in path.rglob("*") if item.is_file()))
    return files


def docs_hygiene() -> None:
    print("==> docs hygiene", flush=True)
    failures: list[str] = []
    for path in iter_doc_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for index, line in enumerate(text.splitlines(), start=1):
            if DOCS_BLOCKLIST.search(line):
                failures.append(f"{path.relative_to(ROOT)}:{index}: {line.strip()}")
    if failures:
        raise SystemExit("docs hygiene failed:\n" + "\n".join(failures))


def import_smoke(python: str) -> None:
    code = (
        "import baileys; "
        "from baileys import WhatsAppClient, make_socket, makeWASocket, encode_wam; "
        "print(baileys.__name__, WhatsAppClient.__name__, callable(make_socket), callable(makeWASocket), callable(encode_wam))"
    )
    run_step("import smoke", [python, "-c", code])


def build_package() -> Path:
    shutil.rmtree(ROOT / "build", ignore_errors=True)
    shutil.rmtree(ROOT / "dist", ignore_errors=True)
    run_step("package build", [sys.executable, "-m", "build"])
    wheels = sorted((ROOT / "dist").glob("*.whl"))
    if not wheels:
        raise SystemExit("package build did not produce a wheel")
    return wheels[-1]


def clean_install_smoke(wheel: Path) -> None:
    print("==> clean install smoke", flush=True)
    with tempfile.TemporaryDirectory(prefix="baileys-python-release-") as temp:
        venv_dir = Path(temp) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], check=True)
        subprocess.run([str(python), "-m", "pip", "install", str(wheel)], check=True)
        import_smoke(str(python))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run core beta release gates.")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-clean-install", action="store_true")
    args = parser.parse_args()

    run_step("compile", [sys.executable, "-m", "compileall", "-q", "src", "scripts", "examples"])
    run_step("pytest", [sys.executable, "-m", "pytest", "-q"])
    run_step("WABinary generated check", [sys.executable, "scripts/generate_wabinary_tokens.py", "--check"])
    run_step("WAProto generated check", [sys.executable, "scripts/generate_proto.py", "--check"])
    run_step("WAM generated check", [sys.executable, "scripts/generate_wam_constants.py", "--check"])
    docs_hygiene()
    run_step("release status check", [sys.executable, "scripts/release_status.py", "--check"])
    import_smoke(sys.executable)
    run_step("example pairing-code request", [sys.executable, "examples/pairing_code_request.py"])

    wheel: Path | None = None
    if not args.skip_build:
        wheel = build_package()
    if wheel is not None and not args.skip_clean_install:
        clean_install_smoke(wheel)

    print("RELEASE_GATE_OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
