from __future__ import annotations

import logging

import baileys as bpt
from baileys.logging_utils import configure_logging, get_logger, node_log_summary, redact_mapping, redact_value
from baileys.wabinary import BinaryNode


def test_redact_value_masks_sensitive_attrs_jids_and_long_blobs():
    assert redact_value("media_key", "abc") == "<redacted>"
    assert redact_value("to", "919272419368@s.whatsapp.net") == "<number>@s.whatsapp.net"
    assert redact_value("payload", "A" * 80) == "<redacted>"


def test_node_log_summary_redacts_attrs_and_omits_payload_bytes():
    node = BinaryNode(
        "message",
        {"id": "abc", "to": "919272419368@s.whatsapp.net", "phash": "secret"},
        [BinaryNode("enc", {}, b"encrypted bytes")],
    )

    summary = node_log_summary(node)

    assert summary["tag"] == "message"
    assert summary["attrs"] == {"id": "abc", "to": "<number>@s.whatsapp.net", "phash": "<redacted>"}
    assert summary["children"] == ["enc"]


def test_configure_logging_keeps_library_logger_opt_in():
    logger = get_logger("test")
    assert logger.name == "baileys.test"
    root = configure_logging(logging.DEBUG)

    assert root.name == "baileys"
    assert root.level == logging.DEBUG
    assert root.handlers


def test_logging_helpers_are_public_exports():
    assert bpt.configure_logging is configure_logging
    assert bpt.configureLogging is configure_logging
    assert bpt.get_logger is get_logger
    assert bpt.node_log_summary is node_log_summary
    assert bpt.redact_mapping is redact_mapping
