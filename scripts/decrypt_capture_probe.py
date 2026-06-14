from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from google.protobuf.json_format import MessageToDict


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.message_decrypt import decrypt_message_node, first_enc, message_field_names  # noqa: E402


def message_has_text(message) -> bool:
    return message.HasField("conversation") or message.HasField("extendedTextMessage")


def try_decrypt(node: dict, creds: dict, creds_path: Path | None):
    enc = first_enc(node)
    if not enc:
        return None
    enc_node, _ = enc
    if enc_node["attrs"].get("type") not in {"pkmsg", "msg", "skmsg"}:
        print(f"SKIP unsupported enc type {enc_node['attrs']}")
        return None

    try:
        result = decrypt_message_node(node, creds, persist_creds_path=creds_path)
    except Exception as exc:
        print(f"DECRYPT_FAIL id={node['attrs'].get('id')} err={type(exc).__name__}: {exc}")
        return None
    if result is None:
        return None
    print(f"DECRYPT_OK id={result.stanza_id} type={result.enc_type} addr={result.address} fields={message_field_names(result.message)}")
    print(json.dumps(MessageToDict(result.message, preserving_proto_field_name=True), indent=2)[:2000])
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "live_pair_creds.json"))
    parser.add_argument("--capture-path", default=str(ROOT / "captures" / "incoming_messages.jsonl"))
    parser.add_argument("--no-persist", action="store_true")
    parser.add_argument("--all", action="store_true", help="attempt every captured encrypted message instead of stopping")
    parser.add_argument("--require-text", action="store_true", help="exit nonzero unless a chat text payload decrypts")
    args = parser.parse_args()

    creds_path = Path(args.creds_path)
    creds = json.loads(creds_path.read_text(encoding="utf-8"))
    nodes = [json.loads(line) for line in Path(args.capture_path).read_text(encoding="utf-8").splitlines() if line]
    any_success = False
    any_text = False
    for node in nodes:
        result = try_decrypt(node, creds, None if args.no_persist else creds_path)
        any_success = result is not None or any_success
        any_text = (result is not None and message_has_text(result.message)) or any_text
        if result is not None and not args.all:
            break
    if not any_success:
        raise SystemExit("no captured pkmsg decrypted")
    if args.require_text and not any_text:
        raise SystemExit("no captured text chat message decrypted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
