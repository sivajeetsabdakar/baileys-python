from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_live_suite():
    spec = importlib.util.spec_from_file_location("live_suite", ROOT / "scripts" / "live_suite.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_live_suite_redacts_paths_numbers_and_blobs():
    live_suite = load_live_suite()
    text = (
        f"SCAN_QR {ROOT}\\product_qr.png\n"
        "QR_PAYLOAD https://wa.me/settings/linked_devices#secret\n"
        "jid=919272419368@s.whatsapp.net token=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789==\n"
    )

    redacted = live_suite.redact_text(text)

    assert str(ROOT) not in redacted
    assert "QR_PAYLOAD <redacted>" in redacted
    assert "919272419368" not in redacted
    assert "<blob>" in redacted
    outside_python = Path.home() / "python.exe"
    assert live_suite.redacted_command([str(outside_python)]) == ["python.exe"]


def test_live_suite_classifies_limited_and_missing_creds():
    live_suite = load_live_suite()

    assert live_suite.classify_step(0, "BUSINESS_PROFILE_OK {}", "") == "passed"
    assert live_suite.classify_step(0, "WAM_ACCOUNT_OR_SERVER_LIMIT TimeoutError", "") == "limited"
    assert live_suite.classify_step(2, "MISSING_CREDS auth/missing.json", "") == "skipped"
    assert live_suite.classify_step(1, "GROUP_METADATA_TIMEOUT jid=group", "") == "limited"
    assert live_suite.classify_step(1, "boom", "") == "failed"


def test_live_suite_write_steps_are_skipped_without_destination():
    live_suite = load_live_suite()
    args = argparse.Namespace(
        creds_path="auth/product_qr_creds.json",
        probe_timeout=45.0,
        watch_timeout=30,
        group_jid=None,
        profile_jid=None,
        on_whatsapp_jid=[],
        business_jid=None,
        peer_jid=None,
        community_jid=None,
        newsletter_kind="jid",
        newsletter_key=None,
        order_id=None,
        order_token=None,
        to=None,
        text="text",
        caption="caption",
        include_remaining=False,
        include_write=True,
        skip_collections=False,
        apply_newsletter_create=False,
        apply_cover_photo=False,
        send_peer_data=False,
        send_wam=False,
    )

    steps = live_suite.build_steps(args)
    write_steps = {step.name: step for step in steps if step.name.startswith("send-")}

    assert write_steps["send-text"].required == ("--to is required for write probes",)
    assert write_steps["send-image"].required == ("--to is required for write probes",)
    assert "45" in steps[0].command
    assert "45.0" not in steps[0].command


def test_live_suite_writes_redacted_nightly_plan(tmp_path):
    live_suite = load_live_suite()
    args = argparse.Namespace(
        creds_path=str(ROOT / "auth" / "product_qr_creds.json"),
        probe_timeout=45.0,
        watch_timeout=30,
        group_jid="120363123456789012@g.us",
        profile_jid=None,
        on_whatsapp_jid=[],
        business_jid=None,
        peer_jid=None,
        community_jid=None,
        newsletter_kind="jid",
        newsletter_key=None,
        order_id=None,
        order_token=None,
        to=None,
        text="text",
        caption="caption",
        include_remaining=True,
        include_write=False,
        skip_collections=True,
        apply_newsletter_create=False,
        apply_cover_photo=False,
        send_peer_data=False,
        send_wam=False,
    )
    output = tmp_path / "nightly.json"

    plan = live_suite.write_nightly_plan(output, live_suite.build_steps(args))
    data = json.loads(output.read_text(encoding="utf-8"))

    assert plan["kind"] == "nightly-live-readonly"
    assert data["kind"] == "nightly-live-readonly"
    assert {step["name"] for step in data["steps"]} == {"phase5-readonly", "phase7-readonly", "phase7-remaining"}
    assert str(ROOT) not in output.read_text(encoding="utf-8")
    assert "120363123456789012" not in output.read_text(encoding="utf-8")
