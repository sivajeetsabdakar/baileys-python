from __future__ import annotations

from pathlib import Path
import re

from grpc_tools import protoc


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
SOURCE_PROTO = REPO_ROOT / "Baileys-master" / "Baileys-master" / "WAProto" / "WAProto.proto"
GENERATED_DIR = ROOT / "src" / "baileys" / "generated"


ENUM_RE = re.compile(r"^(\s*)enum\s+([A-Za-z_][A-Za-z0-9_]*)\s*\{")
ENUM_VALUE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(-?\d+)\s*;")


def make_proto_google_compatible(proto_text: str) -> str:
    lines = proto_text.splitlines()
    output: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        output.append(line)

        match = ENUM_RE.match(line)
        if match:
            enum_indent, enum_name = match.groups()
            j = i + 1
            while j < len(lines):
                candidate = lines[j].strip()
                if not candidate or candidate.startswith("//") or candidate.startswith("option "):
                    j += 1
                    continue

                value_match = ENUM_VALUE_RE.match(lines[j])
                if value_match and int(value_match.group(2)) != 0:
                    output.append(f"{enum_indent}    UNKNOWN_{enum_name} = 0;")
                break

        i += 1

    return "\n".join(output) + "\n"


def main() -> int:
    if not SOURCE_PROTO.exists():
        raise SystemExit(f"Missing source proto: {SOURCE_PROTO}")

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    (GENERATED_DIR / "__init__.py").write_text("", encoding="utf-8")

    local_proto = GENERATED_DIR / "WAProto.proto"
    proto_text = SOURCE_PROTO.read_text(encoding="utf-8")
    # Baileys uses protobufjs, which accepts proto3 enums whose first value is
    # not zero. Google's Python protoc rejects those as open-enum violations.
    # Keep proto3 semantics, but add a local zero placeholder only in the copied
    # generated proto used by this spike.
    local_proto.write_text(make_proto_google_compatible(proto_text), encoding="utf-8")

    result = protoc.main(
        [
            "grpc_tools.protoc",
            f"-I{GENERATED_DIR}",
            f"--python_out={GENERATED_DIR}",
            str(local_proto),
        ]
    )
    if result != 0:
        raise SystemExit(result)

    print(f"generated {GENERATED_DIR / 'WAProto_pb2.py'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
