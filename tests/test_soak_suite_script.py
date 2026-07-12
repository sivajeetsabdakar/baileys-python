from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def load_soak_suite():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("soak_suite", SCRIPTS / "soak_suite.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_soak_suite_builds_product_soak_command():
    soak_suite = load_soak_suite()
    args = argparse.Namespace(
        creds_path="auth/product_qr_creds.json",
        duration=60,
        receive_timeout=30,
        keepalive_interval=25,
    )

    command = soak_suite.build_command(args)

    assert command[1].endswith("product_soak_probe.py")
    assert "--duration" in command
    assert "60" in command


def test_soak_suite_classifies_statuses():
    soak_suite = load_soak_suite()

    assert soak_suite.classify_soak(0, "SOAK_OK counters={}", "") == "passed"
    assert soak_suite.classify_soak(2, "MISSING_CREDS auth/missing.json", "") == "skipped"
    assert soak_suite.classify_soak(1, "MESSAGE_TIMEOUT", "") == "limited"
    assert soak_suite.classify_soak(1, "boom", "") == "failed"
