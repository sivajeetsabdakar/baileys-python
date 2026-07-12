from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from live_suite import redact_text, redacted_command, relative_path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CREDS = ROOT / "auth" / "product_qr_creds.json"
DEFAULT_OUTPUT = ROOT / ".tmp" / "soak_summary.json"


def build_command(args: argparse.Namespace) -> list[str]:
    return [
        sys.executable,
        str(ROOT / "scripts" / "product_soak_probe.py"),
        "--creds-path",
        str(Path(args.creds_path)),
        "--duration",
        str(args.duration),
        "--receive-timeout",
        str(args.receive_timeout),
        "--keepalive-interval",
        str(args.keepalive_interval),
    ]


def classify_soak(returncode: int | None, stdout: str, stderr: str) -> str:
    combined = f"{stdout}\n{stderr}"
    if "MISSING_CREDS" in combined:
        return "skipped"
    if returncode == 0 and "SOAK_OK" in combined:
        return "passed"
    if "ACCOUNT_OR_SERVER_LIMIT" in combined or "TIMEOUT" in combined:
        return "limited"
    return "failed"


def write_summary(path: Path, summary: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the product socket soak probe and write a JSON summary.")
    parser.add_argument("--creds-path", default=str(DEFAULT_CREDS))
    parser.add_argument("--duration", type=float, default=3600)
    parser.add_argument("--receive-timeout", type=float, default=30)
    parser.add_argument("--keepalive-interval", type=float, default=25)
    parser.add_argument("--timeout-cushion", type=float, default=90)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    command = build_command(args)
    if args.dry_run:
        print(" ".join(redacted_command(command)), flush=True)
        return 0

    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=args.duration + args.timeout_cushion,
        )
        returncode = completed.returncode
        stdout = redact_text(completed.stdout)
        stderr = redact_text(completed.stderr)
        status = classify_soak(returncode, stdout, stderr)
        reason = None
    except subprocess.TimeoutExpired as exc:
        returncode = None
        stdout = redact_text(exc.stdout or "")
        stderr = redact_text(exc.stderr or "")
        status = "failed"
        reason = f"wrapper timed out after {args.duration + args.timeout_cushion:g}s"

    summary = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.monotonic() - started, 3),
        "status": status,
        "returncode": returncode,
        "command": redacted_command(command),
        "stdout": stdout,
        "stderr": stderr,
    }
    if reason is not None:
        summary["reason"] = reason
    write_summary(args.output, summary)
    print(f"SOAK_SUITE_SUMMARY {relative_path(args.output)}", flush=True)
    print(f"SOAK_SUITE_STATUS {status}", flush=True)
    return 0 if status in {"passed", "skipped", "limited"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
