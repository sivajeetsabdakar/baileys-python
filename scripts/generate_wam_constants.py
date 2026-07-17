from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT.parent / "Baileys-master" / "src" / "WAM" / "constants.ts"
DEFAULT_OUTPUT = ROOT / "src" / "baileys" / "generated" / "wam_constants.json"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate compact WAM event/global id tables from Node Baileys constants.")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    source = Path(args.source)
    output = Path(args.output)
    data = parse_constants(source.read_text(encoding="utf-8"))
    rendered = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not output.exists():
            print(f"missing {output}", file=sys.stderr)
            return 1
        existing = output.read_text(encoding="utf-8")
        if existing != rendered:
            print(f"{output} is out of date", file=sys.stderr)
            return 1
        print(f"checked {output}")
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(f"wrote {output} events={len(data['events'])} globals={len(data['globals'])}")
    return 0


def parse_constants(text: str) -> dict[str, object]:
    events_block = _array_block(text, "WEB_EVENTS")
    globals_block = _array_block(text, "WEB_GLOBALS")
    return {"events": _parse_events(events_block), "globals": _parse_globals(globals_block)}


def _array_block(text: str, name: str) -> str:
    marker = f"export const {name}"
    start = text.index(marker)
    equals = text.index("=", start)
    array_start = text.index("[", equals)
    depth = 0
    for index in range(array_start, len(text)):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[array_start + 1 : index]
    raise ValueError(f"could not find array for {name}")


def _top_level_objects(block: str) -> list[str]:
    objects: list[str] = []
    start: int | None = None
    depth = 0
    quote: str | None = None
    escape = False
    for index, char in enumerate(block):
        if quote:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
            continue
        if char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and start is not None:
                objects.append(block[start : index + 1])
                start = None
    return objects


def _parse_events(block: str) -> dict[str, object]:
    events: dict[str, object] = {}
    for item in _top_level_objects(block):
        name = _match_string(item, "name")
        event_id = _match_int(item, "id")
        weight = _match_int(item, "weight", default=1)
        props = _props_block(item)
        prop_ids = {match.group(1): int(match.group(2)) for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*\[\s*(\d+)\s*,", props)}
        events[name] = {"id": event_id, "weight": weight, "props": prop_ids}
    return events


def _parse_globals(block: str) -> dict[str, int]:
    globals_: dict[str, int] = {}
    for item in _top_level_objects(block):
        globals_[_match_string(item, "name")] = _match_int(item, "id")
    return globals_


def _props_block(item: str) -> str:
    match = re.search(r"\bprops\s*:\s*{", item)
    if not match:
        return ""
    start = match.end() - 1
    depth = 0
    for index in range(start, len(item)):
        if item[index] == "{":
            depth += 1
        elif item[index] == "}":
            depth -= 1
            if depth == 0:
                return item[start + 1 : index]
    raise ValueError("unterminated props block")


def _match_string(item: str, key: str) -> str:
    match = re.search(rf"\b{key}\s*:\s*'([^']+)'", item)
    if not match:
        raise ValueError(f"missing string key {key}: {item[:120]}")
    return match.group(1)


def _match_int(item: str, key: str, *, default: int | None = None) -> int:
    match = re.search(rf"\b{key}\s*:\s*(\d+)", item)
    if not match:
        if default is not None:
            return default
        raise ValueError(f"missing int key {key}: {item[:120]}")
    return int(match.group(1))


if __name__ == "__main__":
    raise SystemExit(main())
