from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
CONSTANTS_TS = REPO_ROOT / "Baileys-master" / "Baileys-master" / "src" / "WABinary" / "constants.ts"
OUTPUT = ROOT / "src" / "baileys" / "generated" / "wabinary_tokens.json"


def extract_array(source: str, name: str, next_marker: str) -> list:
    marker = f"export const {name} = "
    start = source.index(marker) + len(marker)
    end = source.index(next_marker, start)
    array_source = source[start:end].strip()
    if array_source.endswith("as const"):
        array_source = array_source[: -len("as const")].strip()
    return ast.literal_eval(array_source)


def build_token_payload() -> dict[str, list]:
    if not CONSTANTS_TS.exists():
        raise SystemExit(f"Missing constants source: {CONSTANTS_TS}")

    source = CONSTANTS_TS.read_text(encoding="utf-8")
    double_tokens = extract_array(source, "DOUBLE_BYTE_TOKENS", "\nexport const SINGLE_BYTE_TOKENS")
    single_tokens = extract_array(source, "SINGLE_BYTE_TOKENS", "\n\nexport const TOKEN_MAP")
    return {
        "single_byte_tokens": single_tokens,
        "double_byte_tokens": double_tokens,
    }


def render_token_payload(payload: dict[str, list]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate WABinary dictionary tokens from Node Baileys.")
    parser.add_argument("--check", action="store_true", help="fail if generated tokens are out of date")
    args = parser.parse_args()

    payload = build_token_payload()
    rendered = render_token_payload(payload)
    if args.check:
        if not OUTPUT.exists():
            print(f"missing generated token file: {OUTPUT}")
            return 1
        if OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"generated token file is out of date: {OUTPUT}")
            return 1
        print(f"checked {OUTPUT}")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")

    print(f"generated {OUTPUT}")
    print(f"single={len(payload['single_byte_tokens'])} double_dicts={len(payload['double_byte_tokens'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
