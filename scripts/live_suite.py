from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CREDS = ROOT / "auth" / "product_qr_creds.json"
DEFAULT_OUTPUT = ROOT / ".tmp" / "live_suite_summary.json"

LONG_BLOB_RE = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=]{48,}(?![A-Za-z0-9+/=])")
PHONE_JID_RE = re.compile(r"\b\d{8,}(?=[:@])")
PHONE_RE = re.compile(r"\b\d{8,}\b")


@dataclass(frozen=True)
class SuiteStep:
    name: str
    command: list[str]
    required: tuple[str, ...] = ()


def relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return path.name if path.is_absolute() else str(path)


def redact_text(text: str) -> str:
    text = text.replace(str(ROOT), ".")
    text = re.sub(r"QR_PAYLOAD .+", "QR_PAYLOAD <redacted>", text)
    text = PHONE_JID_RE.sub("<number>", text)
    text = PHONE_RE.sub("<number>", text)
    return LONG_BLOB_RE.sub("<blob>", text)


def redacted_command(command: Iterable[str]) -> list[str]:
    output: list[str] = []
    for item in command:
        try:
            path = Path(item)
            if path.is_absolute():
                try:
                    output.append(relative_path(path.resolve()))
                except ValueError:
                    output.append(path.name)
                continue
        except OSError:
            pass
        output.append(redact_text(item))
    return output


def classify_step(returncode: int, stdout: str, stderr: str) -> str:
    combined = f"{stdout}\n{stderr}"
    if returncode == 0 and "ACCOUNT_OR_SERVER_LIMIT" in combined:
        return "limited"
    if returncode == 0:
        return "passed"
    if "MISSING_CREDS" in combined:
        return "skipped"
    if "ACCOUNT_OR_SERVER_LIMIT" in combined or "TIMEOUT" in combined:
        return "limited"
    return "failed"


def run_suite_step(step: SuiteStep, timeout: float) -> dict[str, object]:
    started = time.monotonic()
    if step.required:
        return {
            "name": step.name,
            "status": "skipped",
            "duration_seconds": 0.0,
            "command": redacted_command(step.command),
            "reason": ", ".join(step.required),
            "stdout": "",
            "stderr": "",
        }
    try:
        completed = subprocess.run(
            step.command,
            cwd=ROOT,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
        duration = round(time.monotonic() - started, 3)
        stdout = redact_text(completed.stdout)
        stderr = redact_text(completed.stderr)
        return {
            "name": step.name,
            "status": classify_step(completed.returncode, stdout, stderr),
            "returncode": completed.returncode,
            "duration_seconds": duration,
            "command": redacted_command(step.command),
            "stdout": stdout,
            "stderr": stderr,
        }
    except subprocess.TimeoutExpired as exc:
        duration = round(time.monotonic() - started, 3)
        stdout = redact_text(exc.stdout or "")
        stderr = redact_text(exc.stderr or "")
        return {
            "name": step.name,
            "status": "limited",
            "returncode": None,
            "duration_seconds": duration,
            "command": redacted_command(step.command),
            "stdout": stdout,
            "stderr": stderr,
            "reason": f"timed out after {timeout:g}s",
        }


def script_command(script: str, *args: str) -> list[str]:
    return [sys.executable, str(ROOT / "scripts" / script), *args]


def append_if(command: list[str], flag: str, value: str | None) -> None:
    if value:
        command.extend([flag, value])


def format_cli_number(value: float | int) -> str:
    return f"{value:g}"


def build_steps(args: argparse.Namespace) -> list[SuiteStep]:
    creds = str(Path(args.creds_path))
    timeout = format_cli_number(args.probe_timeout)
    steps: list[SuiteStep] = []

    phase5 = script_command("phase5_live_probe.py", "--creds-path", creds, "--timeout", timeout)
    append_if(phase5, "--group-jid", args.group_jid)
    append_if(phase5, "--profile-jid", args.profile_jid)
    for jid in args.on_whatsapp_jid:
        phase5.extend(["--on-whatsapp-jid", jid])
    steps.append(SuiteStep("phase5-readonly", phase5))

    phase7 = script_command("phase7_live_probe.py", "--creds-path", creds, "--timeout", timeout, "--allow-limits")
    append_if(phase7, "--business-jid", args.business_jid)
    append_if(phase7, "--community-jid", args.community_jid)
    append_if(phase7, "--newsletter-kind", args.newsletter_kind)
    append_if(phase7, "--newsletter-key", args.newsletter_key)
    if args.send_wam:
        phase7.append("--send-wam")
    steps.append(SuiteStep("phase7-readonly", phase7))

    if args.include_remaining:
        remaining = script_command("phase7_remaining_probe.py", "--creds-path", creds, "--timeout", timeout, "--allow-limits")
        append_if(remaining, "--business-jid", args.business_jid)
        append_if(remaining, "--peer-jid", args.peer_jid)
        append_if(remaining, "--community-jid", args.community_jid)
        append_if(remaining, "--newsletter-kind", args.newsletter_kind)
        append_if(remaining, "--newsletter-key", args.newsletter_key)
        append_if(remaining, "--order-id", args.order_id)
        append_if(remaining, "--order-token", args.order_token)
        if args.skip_collections:
            remaining.append("--skip-collections")
        if args.apply_newsletter_create:
            remaining.append("--apply-newsletter-create")
        if args.apply_cover_photo:
            remaining.append("--apply-cover-photo")
        if args.send_peer_data:
            remaining.append("--send-peer-data")
        if args.send_wam:
            remaining.append("--send-wam")
        steps.append(SuiteStep("phase7-remaining", remaining))

    if args.include_write:
        missing_to = () if args.to else ("--to is required for write probes",)
        text = script_command("send_text_probe.py", "--creds-path", creds, "--timeout", timeout, "--watch", str(args.watch_timeout))
        if args.to:
            text.extend(["--to", args.to, "--text", args.text])
        steps.append(SuiteStep("send-text", text, missing_to))

        image = script_command("send_image_probe.py", "--creds-path", creds, "--timeout", timeout, "--watch", str(args.watch_timeout))
        if args.to:
            image.extend(["--to", args.to, "--caption", args.caption, "--download"])
        steps.append(SuiteStep("send-image", image, missing_to))

    return steps


def write_summary(output_path: Path, summary: dict[str, object]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run selected live probes and write a JSON summary.")
    parser.add_argument("--creds-path", default=str(DEFAULT_CREDS))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--probe-timeout", type=float, default=45)
    parser.add_argument("--step-timeout", type=float, default=120)
    parser.add_argument("--watch-timeout", type=int, default=30)
    parser.add_argument("--group-jid")
    parser.add_argument("--profile-jid")
    parser.add_argument("--on-whatsapp-jid", action="append", default=[])
    parser.add_argument("--business-jid")
    parser.add_argument("--peer-jid")
    parser.add_argument("--community-jid")
    parser.add_argument("--newsletter-kind", default="jid")
    parser.add_argument("--newsletter-key")
    parser.add_argument("--order-id")
    parser.add_argument("--order-token")
    parser.add_argument("--to", help="destination JID for write probes")
    parser.add_argument("--text", default="Baileys Python live-suite text probe")
    parser.add_argument("--caption", default="Baileys Python live-suite image probe")
    parser.add_argument("--include-remaining", action="store_true")
    parser.add_argument("--include-write", action="store_true")
    parser.add_argument("--skip-collections", action="store_true")
    parser.add_argument("--apply-newsletter-create", action="store_true")
    parser.add_argument("--apply-cover-photo", action="store_true")
    parser.add_argument("--send-peer-data", action="store_true")
    parser.add_argument("--send-wam", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    steps = build_steps(args)
    if args.dry_run:
        for step in steps:
            print(" ".join(redacted_command(step.command)), flush=True)
        return 0

    started_at = datetime.now(timezone.utc).isoformat()
    results = [run_suite_step(step, args.step_timeout) for step in steps]
    summary = {
        "started_at": started_at,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "passed" if all(item["status"] in {"passed", "limited", "skipped"} for item in results) else "failed",
        "steps": results,
    }
    write_summary(args.output, summary)
    print(f"LIVE_SUITE_SUMMARY {relative_path(args.output)}", flush=True)
    print(f"LIVE_SUITE_STATUS {summary['status']}", flush=True)
    return 0 if summary["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
