from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "roadmap.md"
DEFERRED_TODOS = ROOT / "docs" / "deferred-todos.md"
COMPATIBILITY_MATRIX = ROOT / "docs" / "compatibility-matrix.md"

PHASE_ROW_RE = re.compile(r"^\|\s*(\d+)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$")
MATRIX_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$")


def parse_phases(text: str) -> dict[str, dict[str, str]]:
    phases: dict[str, dict[str, str]] = {}
    for line in text.splitlines():
        match = PHASE_ROW_RE.match(line.strip())
        if not match:
            continue
        phase, target, status = match.groups()
        phases[phase] = {"target": target.strip(), "status": status.strip()}
    return phases


def parse_deferred(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    pending: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = pending
            current = line[3:].strip()
            pending = []
            continue
        if current is None:
            continue
        if line.startswith("- "):
            pending.append(line[2:].strip())
        elif pending and line.startswith("  "):
            pending[-1] += " " + line.strip()
    if current is not None:
        sections[current] = pending
    return sections


def parse_partial_capabilities(text: str) -> list[dict[str, str]]:
    partials: list[dict[str, str]] = []
    for line in text.splitlines():
        match = MATRIX_ROW_RE.match(line.strip())
        if not match:
            continue
        area, capability, status, notes = [item.strip() for item in match.groups()]
        if area in {"Area", "---"}:
            continue
        if status in {"Partial", "Todo", "Seeded"}:
            partials.append({"area": area, "capability": capability, "status": status, "notes": notes})
    return partials


def build_status() -> dict[str, object]:
    roadmap_text = ROADMAP.read_text(encoding="utf-8")
    deferred_text = DEFERRED_TODOS.read_text(encoding="utf-8")
    matrix_text = COMPATIBILITY_MATRIX.read_text(encoding="utf-8")
    phases = parse_phases(roadmap_text)
    deferred = parse_deferred(deferred_text)
    partials = parse_partial_capabilities(matrix_text)
    phase9_status = phases.get("9", {}).get("status", "")
    phase8_status = phases.get("8", {}).get("status", "")
    expected_deferred_sections = {
        "Long-Run Release Evidence",
        "Live Proof",
        "Deferred Business And Community Proof",
        "Maintenance",
    }
    checks = {
        "phase8_done": phase8_status == "Done",
        "phase9_closed": phase9_status.startswith("Done"),
        "phase9_not_in_progress": "Phase 9 In Progress" not in roadmap_text,
        "no_remaining_phase9_wording": "Remaining Phase 9 targets" not in roadmap_text,
        "deferred_sections_present": expected_deferred_sections.issubset(set(deferred)),
        "deferred_items_present": sum(len(items) for items in deferred.values()) > 0,
    }
    return {
        "status": "ready_with_deferred_live_proof" if all(checks.values()) else "incomplete",
        "checks": checks,
        "phases": phases,
        "deferred": deferred,
        "partial_capabilities": partials,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize release and Phase 9 completion status.")
    parser.add_argument("--check", action="store_true", help="fail if the status is incomplete")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args()

    status = build_status()
    if args.json:
        print(json.dumps(status, indent=2, sort_keys=True))
    else:
        print(f"RELEASE_STATUS {status['status']}")
        phase9 = status["phases"].get("9", {})
        print(f"PHASE_9 {phase9.get('status', 'missing')}")
        for section, items in status["deferred"].items():
            print(f"DEFERRED {section}: {len(items)}")
    if args.check and status["status"] != "ready_with_deferred_live_proof":
        failed = [name for name, passed in status["checks"].items() if not passed]
        raise SystemExit("release status incomplete: " + ", ".join(failed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
