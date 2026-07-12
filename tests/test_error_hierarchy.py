from __future__ import annotations

import baileys as bpt
from baileys.socket_nodes import IQError
from baileys.wabinary import BinaryNode


def test_public_errors_share_base_class_and_keep_standard_compatibility():
    iq_error = IQError("403", "forbidden", BinaryNode("iq", {"type": "error"}))
    unsupported = bpt.UnsupportedMessageContent("bad content")
    wam_error = bpt.WAMEncodeError("bad wam")
    mex_error = bpt.MexError("bad mex")
    missing_key = bpt.MissingAppStateKey("missing key")

    assert isinstance(iq_error, bpt.BaileysError)
    assert isinstance(iq_error, RuntimeError)
    assert isinstance(unsupported, bpt.BaileysError)
    assert isinstance(unsupported, ValueError)
    assert isinstance(wam_error, bpt.BaileysValueError)
    assert isinstance(mex_error, bpt.BaileysRuntimeError)
    assert isinstance(missing_key, bpt.BaileysRuntimeError)


def test_account_capability_error_carries_capability_data():
    error = bpt.AccountCapabilityError("server rejected operation", capability="collections", data={"status": 500})

    assert isinstance(error, bpt.BaileysRuntimeError)
    assert str(error) == "server rejected operation"
    assert error.capability == "collections"
    assert error.data == {"status": 500}
