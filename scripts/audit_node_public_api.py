from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_NODE_ROOT = ROOT.parent / "Baileys-master"
DEFAULT_MANIFEST = ROOT / "tests" / "fixtures" / "public_api_parity.json"

SOCKET_FACTORIES = {
    "src/Socket/business.ts": "makeBusinessSocket",
    "src/Socket/chats.ts": "makeChatsSocket",
    "src/Socket/communities.ts": "makeCommunitiesSocket",
    "src/Socket/groups.ts": "makeGroupsSocket",
    "src/Socket/messages-recv.ts": "makeMessagesRecvSocket",
    "src/Socket/messages-send.ts": "makeMessagesSocket",
    "src/Socket/socket.ts": "makeSocket",
    "src/Socket/mex.ts": "executeWMexQuery",
    "src/Socket/newsletter.ts": "makeNewsletterSocket",
}

INTERNAL_RETURN_KEYS = {
    "appPatch",
    "appStatePatchMutex",
    "authState",
    "content",
    "createParticipantNodes",
    "currentPreKeyId",
    "devicesMutex",
    "digestKeyBundle",
    "end",
    "ev",
    "exists",
    "fetchMessageHistory",
    "generateMessageTag",
    "jid",
    "logger",
    "logout",
    "messageMutex",
    "messageRetryManager",
    "notificationMutex",
    "onUnexpectedError",
    "or",
    "placeholderResendCache",
    "query",
    "receiptMutex",
    "registerSocketEndHandler",
    "requestPlaceholderResend",
    "rotateSignedPreKey",
    "sendMessageAck",
    "sendNode",
    "sendRawMessage",
    "sendRetryRequest",
    "sendUnifiedSession",
    "serverProps",
    "signalRepository",
    "status",
    "type",
    "updateServerTimeOffset",
    "uploadPreKeys",
    "uploadPreKeysToServerIfRequired",
    "upsertMessage",
    "user",
    "userDevicesCache",
    "waitForConnectionUpdate",
    "waitForMessage",
    "waitForSocketOpen",
    "wamBuffer",
    "ws",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Baileys-python public socket parity against a local Node Baileys checkout.")
    parser.add_argument("--node-root", type=Path, default=DEFAULT_NODE_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--include-internals", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    audit = build_audit(args.node_root, args.manifest, include_internals=args.include_internals)
    if args.json:
        print(json.dumps(audit, indent=2, sort_keys=True))
    else:
        print(f"Node reference: {audit['node_reference']}")
        print(f"Node socket keys: {len(audit['node_methods'])}")
        print(f"Tracked manifest methods: {len(audit['manifest_methods'])}")
        print(f"Missing in Python manifest: {', '.join(audit['missing_in_manifest']) or 'none'}")
        print(f"Manifest extras not found in socket factories: {', '.join(audit['manifest_extra']) or 'none'}")
        if audit["ignored_internal_keys"]:
            print(f"Ignored internal keys: {', '.join(audit['ignored_internal_keys'])}")
    return 1 if audit["missing_in_manifest"] else 0


def build_audit(node_root: Path, manifest_path: Path, *, include_internals: bool = False) -> dict[str, Any]:
    package = json.loads((node_root / "package.json").read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    node_methods_by_file = extract_node_socket_methods(node_root)
    node_methods = sorted({method for methods in node_methods_by_file.values() for method in methods})
    ignored = sorted(method for method in node_methods if method in INTERNAL_RETURN_KEYS and not include_internals)
    public_node_methods = node_methods if include_internals else [method for method in node_methods if method not in INTERNAL_RETURN_KEYS]
    manifest_methods = sorted(manifest["implemented_methods"])
    manifest_set = set(manifest_methods)
    node_set = set(public_node_methods)
    return {
        "node_reference": package.get("version"),
        "node_methods": public_node_methods,
        "node_methods_by_file": node_methods_by_file,
        "manifest_methods": manifest_methods,
        "missing_in_manifest": sorted(node_set - manifest_set),
        "manifest_extra": sorted(manifest_set - node_set),
        "ignored_internal_keys": ignored,
    }


def extract_node_socket_methods(node_root: Path) -> dict[str, list[str]]:
    methods: dict[str, list[str]] = {}
    for relative, factory in SOCKET_FACTORIES.items():
        source_path = node_root / relative
        if not source_path.exists():
            methods[relative] = []
            continue
        source = source_path.read_text(encoding="utf-8")
        returned = extract_public_return_object(source, factory)
        if returned:
            methods[relative] = top_level_object_keys(returned)
        elif factory == "executeWMexQuery":
            methods[relative] = [factory]
        else:
            methods[relative] = []
    return methods


def extract_public_return_object(source: str, factory_name: str) -> str:
    if factory_name == "executeWMexQuery":
        return ""
    for returned in extract_return_objects(source):
        if factory_name == "makeSocket" and "type: 'md'" in returned:
            return returned
        if factory_name != "makeSocket" and "...sock" in returned:
            return returned
    body = extract_factory_body(source, factory_name)
    return extract_top_level_return_object(body) if body else ""


def extract_return_objects(source: str) -> list[str]:
    objects: list[str] = []
    index = 0
    while index < len(source):
        found = source.find("return {", index)
        if found < 0:
            break
        brace_start = source.find("{", found)
        brace_end = find_matching_brace(source, brace_start)
        if brace_end > brace_start:
            objects.append(source[brace_start + 1 : brace_end])
            index = brace_end + 1
        else:
            index = found + 1
    return objects


def extract_factory_body(source: str, factory_name: str) -> str:
    marker = f"export const {factory_name}"
    start = source.find(marker)
    if start < 0:
        marker = f"const {factory_name}"
        start = source.find(marker)
    if start < 0:
        return ""
    arrow = source.find("=>", start)
    brace_start = source.find("{", arrow if arrow >= 0 else start)
    if brace_start < 0:
        return ""
    brace_end = find_matching_brace(source, brace_start)
    return source[brace_start + 1 : brace_end] if brace_end > brace_start else ""


def extract_top_level_return_object(body: str) -> str:
    index = body.rfind("return {")
    if index < 0:
        return ""
    brace_start = body.find("{", index)
    brace_end = find_matching_brace(body, brace_start)
    return body[brace_start + 1 : brace_end] if brace_end > brace_start else ""


def top_level_object_keys(source: str) -> list[str]:
    keys: list[str] = []
    for part in split_top_level(source):
        item = strip_leading_comments(part.strip())
        if not item or item.startswith("..."):
            continue
        if item.startswith("get "):
            item = item[4:].lstrip()
        name = ""
        for index, char in enumerate(item):
            if char.isalnum() or char in "_$":
                name += char
                continue
            if index > 0 and char in ":=, \r\n\t":
                break
            name = ""
            break
        if name and name not in {"return", "const", "let"}:
            keys.append(name)
    return sorted(set(keys))


def strip_leading_comments(item: str) -> str:
    while item.startswith("//"):
        _, _, item = item.partition("\n")
        item = item.strip()
    return item


def split_top_level(source: str) -> list[str]:
    items: list[str] = []
    start = 0
    index = 0
    depth = 0
    while index < len(source):
        char = source[index]
        if char in "'\"`":
            index = skip_string(source, index)
            continue
        if char in "{[(":
            depth += 1
        elif char in "}])":
            depth -= 1
        elif char == "," and depth == 0:
            items.append(source[start:index])
            start = index + 1
        index += 1
    items.append(source[start:])
    return items


def find_matching_brace(source: str, brace_start: int) -> int:
    depth = 0
    index = brace_start
    while index < len(source):
        char = source[index]
        if char in "'\"`":
            index = skip_string(source, index)
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def skip_string(source: str, quote_index: int) -> int:
    quote = source[quote_index]
    index = quote_index + 1
    while index < len(source):
        char = source[index]
        if char == "\\":
            index += 2
            continue
        if char == quote:
            return index + 1
        index += 1
    return index


if __name__ == "__main__":
    sys.exit(main())
