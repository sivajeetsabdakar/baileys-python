from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_release_status():
    spec = importlib.util.spec_from_file_location("release_status", ROOT / "scripts" / "release_status.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_release_status_tracks_phase9_and_deferred_items():
    release_status = load_release_status()

    status = release_status.build_status()

    assert status["phases"]["8"]["status"] == "Done"
    assert status["phases"]["9"]["status"].startswith("Done")
    assert status["status"] == "ready_with_deferred_live_proof"
    assert "Deferred Business And Community Proof" in status["deferred"]
    assert any(item["area"] == "Business" for item in status["partial_capabilities"])
    assert any(item["area"] == "Communities" for item in status["partial_capabilities"])
