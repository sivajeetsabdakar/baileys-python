from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("audit_node_public_api", ROOT / "scripts" / "audit_node_public_api.py")
audit_node_public_api = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audit_node_public_api)


def test_node_public_api_audit_extracts_factory_return_without_nested_helpers():
    source = """
export const makeGroupsSocket = (config: SocketConfig) => {
    const parse = () => {
        return { status: '200', id: 'nested' }
    }
    return {
        ...sock,
        groupMetadata,
        groupAcceptInviteV4: async (code: string) => code,
        groupFetchAllParticipating,
    }
}
export const extractGroupMetadata = (result: BinaryNode) => {
    return { id: 'group@g.us', status: 'nested' }
}
"""

    body = audit_node_public_api.extract_factory_body(source, "makeGroupsSocket")
    returned = audit_node_public_api.extract_top_level_return_object(body)

    assert audit_node_public_api.top_level_object_keys(returned) == [
        "groupAcceptInviteV4",
        "groupFetchAllParticipating",
        "groupMetadata",
    ]


def test_node_public_api_audit_reports_manifest_gaps(tmp_path):
    node_root = tmp_path / "node"
    socket_dir = node_root / "src" / "Socket"
    socket_dir.mkdir(parents=True)
    (node_root / "package.json").write_text(json.dumps({"version": "7.0.0-rc13"}), encoding="utf-8")
    for relative, factory in audit_node_public_api.SOCKET_FACTORIES.items():
        path = node_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if factory == "makeSocket":
            path.write_text(
                """
export const makeSocket = (config) => {
    const helper = () => {
        return { nestedOnly: true }
    }
    return {
        ev,
        onWhatsApp,
        requestPairingCode,
        newNodeMethod,
    }
}
""",
                encoding="utf-8",
            )
        elif factory == "executeWMexQuery":
            path.write_text("export const executeWMexQuery = async () => undefined\n", encoding="utf-8")
        else:
            path.write_text(f"export const {factory} = () => {{ return {{}} }}\n", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"implemented_methods": ["onWhatsApp"], "deferred_methods": {}}), encoding="utf-8")

    audit = audit_node_public_api.build_audit(node_root, manifest)

    assert "ev" not in audit["missing_in_manifest"]
    assert audit["missing_in_manifest"] == ["executeWMexQuery", "newNodeMethod", "requestPairingCode"]
    assert audit["ignored_internal_keys"] == ["ev"]
