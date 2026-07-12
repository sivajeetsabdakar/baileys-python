from __future__ import annotations

import asyncio

import baileys as bpt
import pytest
from baileys.auth_state import AuthState, JsonCredentialStore
from baileys.generated import WAProto_pb2 as proto
from baileys.pairing_code import generate_pairing_code
from baileys.socket import make_socket
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


def test_api_specific_errors_keep_standard_compatibility():
    timeout = bpt.QueryTimeoutError("query timed out", operation="query", timeout=5, tag_id="abc")

    assert isinstance(timeout, bpt.BaileysTimeoutError)
    assert isinstance(timeout, TimeoutError)
    assert str(timeout) == "query timed out"
    assert timeout.operation == "query"
    assert timeout.timeout == 5
    assert timeout.tag_id == "abc"

    assert isinstance(bpt.AuthStateError("bad auth"), bpt.BaileysValueError)
    assert isinstance(bpt.ContactResolutionError("bad contact"), ValueError)
    assert isinstance(bpt.GroupInviteError("bad invite"), ValueError)
    assert isinstance(bpt.MediaError("bad media"), ValueError)
    assert isinstance(bpt.PairingError("bad pairing"), ValueError)
    assert isinstance(bpt.SessionAssertionError("bad session"), ValueError)
    assert isinstance(bpt.SocketNotConnectedError("closed"), RuntimeError)
    assert isinstance(bpt.ProtocolError("bad protocol"), RuntimeError)


def test_account_capability_error_carries_capability_data():
    error = bpt.AccountCapabilityError("server rejected operation", capability="collections", data={"status": 500})

    assert isinstance(error, bpt.BaileysRuntimeError)
    assert str(error) == "server rejected operation"
    assert error.capability == "collections"
    assert error.data == {"status": 500}


def test_product_entry_points_raise_specific_errors(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials({"me": {"id": "me:1@s.whatsapp.net"}})
        client = make_socket(AuthState.from_store(store))

        with pytest.raises(bpt.SocketNotConnectedError):
            await client.send_node(BinaryNode("iq", {"id": "1"}))

        message = proto.Message()
        message.imageMessage.directPath = "/v/t/old"
        wa_message = bpt.WAMessage(bpt.MessageKey("chat@s.whatsapp.net", "m1", from_me=False), message)
        with pytest.raises(bpt.MediaError, match="mediaKey"):
            await client.update_media_message(wa_message)

    asyncio.run(scenario())


def test_pairing_code_validation_raises_pairing_error():
    with pytest.raises(bpt.PairingError):
        generate_pairing_code("123")
