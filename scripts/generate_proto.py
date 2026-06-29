from __future__ import annotations

import argparse
from pathlib import Path
import re
import tempfile


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


def write_local_proto(generated_dir: Path) -> Path:
    if not SOURCE_PROTO.exists():
        raise SystemExit(f"Missing source proto: {SOURCE_PROTO}")

    generated_dir.mkdir(parents=True, exist_ok=True)
    (generated_dir / "__init__.py").write_text("", encoding="utf-8")
    local_proto = generated_dir / "WAProto.proto"
    proto_text = SOURCE_PROTO.read_text(encoding="utf-8")
    # Baileys uses protobufjs, which accepts proto3 enums whose first value is
    # not zero. Google's Python protoc rejects those as open-enum violations.
    # Keep proto3 semantics, but add a local zero placeholder only in the copied
    # generated proto used by this package.
    local_proto.write_text(make_proto_google_compatible(proto_text), encoding="utf-8")
    return local_proto


def compile_proto(generated_dir: Path, local_proto: Path) -> None:
    try:
        from grpc_tools import protoc
    except ImportError as exc:
        raise SystemExit("grpcio-tools is required: python -m pip install -e .[proto]") from exc

    result = protoc.main(
        [
            "grpc_tools.protoc",
            f"-I{generated_dir}",
            f"--python_out={generated_dir}",
            str(local_proto),
        ]
    )
    if result != 0:
        raise SystemExit(result)


def check_generated_artifacts() -> int:
    with tempfile.TemporaryDirectory(prefix="baileys-proto-check-") as tmp:
        check_dir = Path(tmp)
        local_proto = write_local_proto(check_dir)
        compile_proto(check_dir, local_proto)

        expected = {
            "WAProto.proto": local_proto.read_bytes(),
            "WAProto_pb2.py": (check_dir / "WAProto_pb2.py").read_bytes(),
        }
        for name, expected_bytes in expected.items():
            current_path = GENERATED_DIR / name
            if not current_path.exists():
                print(f"missing generated artifact: {current_path}")
                return 1
            if current_path.read_bytes() != expected_bytes:
                print(f"generated artifact is out of date: {current_path}")
                return 1

    print(f"checked {GENERATED_DIR / 'WAProto_pb2.py'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Python WAProto artifacts from Node Baileys.")
    parser.add_argument("--check", action="store_true", help="fail if generated proto artifacts are out of date")
    args = parser.parse_args()

    if args.check:
        return check_generated_artifacts()

    local_proto = write_local_proto(GENERATED_DIR)
    compile_proto(GENERATED_DIR, local_proto)
    print(f"generated {GENERATED_DIR / 'WAProto_pb2.py'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
