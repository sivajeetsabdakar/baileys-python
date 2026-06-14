from __future__ import annotations

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


def main() -> int:
    if not CONSTANTS_TS.exists():
        raise SystemExit(f"Missing constants source: {CONSTANTS_TS}")

    source = CONSTANTS_TS.read_text(encoding="utf-8")
    double_tokens = extract_array(source, "DOUBLE_BYTE_TOKENS", "\nexport const SINGLE_BYTE_TOKENS")
    single_tokens = extract_array(source, "SINGLE_BYTE_TOKENS", "\n\nexport const TOKEN_MAP")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(
            {
                "single_byte_tokens": single_tokens,
                "double_byte_tokens": double_tokens,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"generated {OUTPUT}")
    print(f"single={len(single_tokens)} double_dicts={len(double_tokens)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
