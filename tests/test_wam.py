from __future__ import annotations

import pytest

from baileys.wam import WAMBinaryInfo, WAMEncodeError, WAMEvent, WAMEventSpec, encode_wam


def test_encode_wam_header_globals_and_event_fields():
    payload = encode_wam(
        WAMBinaryInfo(
            protocol_version=5,
            sequence=7,
            events=[
                WAMEvent(
                    "DemoEvent",
                    props={"small": 1, "signed": -5, "label": "ok"},
                    globals={"platform": "web"},
                )
            ],
        ),
        {"DemoEvent": WAMEventSpec(id=4358, weight=2, props={"small": 1, "signed": 2, "label": 300})},
        {"platform": 9},
    )

    assert payload.startswith(b"WAM\x05\x01\x00\x07\x00")
    assert b"\x80\x09\x03web" in payload
    assert b"\x39\x06\x11\xfe" in payload
    assert b"\x21\x01" in payload
    assert b"\x31\x02\xfb" in payload
    assert b"\x8e,\x01\x02ok" in payload


def test_encode_wam_handles_null_global_and_extended_event():
    payload = encode_wam(
        WAMBinaryInfo(events=[WAMEvent("EmptyEvent", props={}, globals={"unset": None})]),
        {"EmptyEvent": WAMEventSpec(id=10, weight=1, props={})},
        {"unset": 20},
    )

    assert payload == b"WAM\x05\x01\x00\x00\x00\x00\x14\x35\x0a\xff"


def test_encode_wam_rejects_unknown_schema_entries():
    with pytest.raises(WAMEncodeError, match="unknown WAM event"):
        encode_wam(WAMBinaryInfo(events=[WAMEvent("Missing")]), {})

    with pytest.raises(WAMEncodeError, match="unknown WAM property"):
        encode_wam(WAMBinaryInfo(events=[WAMEvent("Demo", props={"bad": 1})]), {"Demo": WAMEventSpec(id=1)})
