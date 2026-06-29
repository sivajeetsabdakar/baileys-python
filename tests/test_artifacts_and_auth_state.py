from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from baileys import AuthState, JsonCredentialStore, MemorySignalKeyStore, useMultiFileAuthState


ROOT = Path(__file__).resolve().parents[1]


def _run_script_check(script: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, script, "--check"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def test_wabinary_token_artifact_is_current():
    result = _run_script_check("scripts/generate_wabinary_tokens.py")
    assert "checked" in result.stdout


def test_waproto_artifact_is_current():
    if importlib.util.find_spec("grpc_tools") is None:
        pytest.skip("grpcio-tools is only required for proto generation checks")
    result = _run_script_check("scripts/generate_proto.py")
    assert "checked" in result.stdout


def test_json_credential_store_and_auth_state_round_trip(tmp_path):
    raw = {
        "identity_public": "id-pub",
        "identity_private": "id-priv",
        "registration_id": 123,
        "signed_pre_key_id": 4,
        "signed_pre_key_public": "spk-pub",
        "signed_pre_key_private": "spk-priv",
        "signed_pre_key_signature": "spk-sig",
        "me": {"id": "123:4@s.whatsapp.net"},
    }
    store = JsonCredentialStore(tmp_path / "creds.json")
    store.save_credentials(raw)

    state = AuthState.from_store(store, signal_store=MemorySignalKeyStore())
    assert state.credentials["registration_id"] == 123
    assert state.typed_credentials.me is not None
    assert state.typed_credentials.me.id == "123:4@s.whatsapp.net"

    state.credentials["routing_info"] = "abc"
    state.save_credentials()
    assert store.load_credentials()["routing_info"] == "abc"


def test_multi_file_auth_state_signal_key_store(tmp_path):
    multi = useMultiFileAuthState(tmp_path / "auth")
    multi.credential_store.save_credentials(
        {
            "identity_public": "id-pub",
            "identity_private": "id-priv",
            "registration_id": 123,
            "signed_pre_key_id": 4,
            "signed_pre_key_public": "spk-pub",
            "signed_pre_key_private": "spk-priv",
            "signed_pre_key_signature": "spk-sig",
        }
    )

    state = multi.load()
    assert state.signal_store is not None
    state.signal_store.set("session", "alice:1", {"record": "abc"})
    assert state.signal_store.get("session", "alice:1") == {"record": "abc"}
    assert state.signal_store.delete("session", "alice:1")
    assert state.signal_store.get("session", "alice:1") is None


def test_phase_1_foundation_docs_are_marked_complete_and_portable():
    roadmap = (ROOT / "docs" / "roadmap.md").read_text(encoding="utf-8")
    matrix = (ROOT / "docs" / "compatibility-matrix.md").read_text(encoding="utf-8")
    docs = roadmap + "\n" + matrix + "\n" + (ROOT / "README.md").read_text(encoding="utf-8")

    assert "| 1 | Protocol foundation | Done |" in roadmap
    assert "| Core | WAProto generated Python classes | Done |" in matrix
    assert "| Core | Tokenized WABinary encode/decode | Done |" in matrix
    assert "| Core | JID utilities | Done |" in matrix
    assert "| Core | Crypto/key primitives | Done |" in matrix
    assert "python.exe" not in docs
    assert "conda" not in docs.lower()
    assert "C:\\" not in docs
    assert "D:\\" not in docs
