from __future__ import annotations

import pytest

from baileys.messages import MessageKey, WAMessage
from baileys.receipts import (
    ReceiptInfo,
    aggregate_message_keys,
    build_ack_node,
    build_receipt_node,
    parse_receipt_info,
    parse_retry_request,
    receipt_message_ids,
    receipt_node_for_message,
    receipt_status_from_type,
)
from baileys.generated import WAProto_pb2 as proto
from baileys.wabinary import BinaryNode


def test_build_ack_node_matches_baileys_message_shape():
    node = BinaryNode(
        "message",
        {
            "id": "msg-001",
            "from": "group@g.us",
            "participant": "sender@s.whatsapp.net",
            "type": "text",
        },
    )

    ack = build_ack_node(node, me_id="me@s.whatsapp.net")

    assert ack.tag == "ack"
    assert ack.attrs == {
        "id": "msg-001",
        "to": "group@g.us",
        "class": "message",
        "participant": "sender@s.whatsapp.net",
        "type": "text",
        "from": "me@s.whatsapp.net",
    }


def test_build_ack_node_forwards_error_recipient_and_skips_from_for_receipts():
    node = BinaryNode(
        "receipt",
        {
            "id": "rcpt-001",
            "from": "group@g.us",
            "participant": "sender@s.whatsapp.net",
            "recipient": "me@s.whatsapp.net",
            "type": "read",
        },
    )

    ack = build_ack_node(node, error_code=500, me_id="me@s.whatsapp.net")

    assert ack.attrs == {
        "id": "rcpt-001",
        "to": "group@g.us",
        "class": "receipt",
        "error": "500",
        "participant": "sender@s.whatsapp.net",
        "recipient": "me@s.whatsapp.net",
        "type": "read",
    }


def test_build_ack_node_omits_zero_error():
    ack = build_ack_node(BinaryNode("message", {"id": "m1", "from": "user@s.whatsapp.net"}), error_code=0)

    assert "error" not in ack.attrs


def test_build_receipt_node_supports_multiple_message_ids():
    receipt = build_receipt_node(
        "user@s.whatsapp.net",
        ["a", "b", "c"],
        participant="sender@s.whatsapp.net",
        receipt_type="read",
        timestamp=123,
    )

    assert receipt.tag == "receipt"
    assert receipt.attrs == {
        "id": "a",
        "to": "user@s.whatsapp.net",
        "participant": "sender@s.whatsapp.net",
        "type": "read",
        "t": "123",
    }
    assert receipt.content[0].tag == "list"
    assert [item.attrs["id"] for item in receipt.content[0].content] == ["b", "c"]


def test_build_receipt_node_requires_ids():
    with pytest.raises(ValueError, match="at least one"):
        build_receipt_node("user@s.whatsapp.net", [], receipt_type="read")


def test_receipt_node_for_message_uses_message_key():
    message = WAMessage(
        key=MessageKey(
            remote_jid="group@g.us",
            id="msg-1",
            participant="sender@s.whatsapp.net",
        ),
        message=None,
    )

    receipt = receipt_node_for_message(message, receipt_type="read", timestamp=999)

    assert receipt.attrs == {
        "id": "msg-1",
        "to": "group@g.us",
        "participant": "sender@s.whatsapp.net",
        "type": "read",
        "t": "999",
    }


def test_aggregate_message_keys_skips_from_me_and_groups_by_chat_participant():
    groups = aggregate_message_keys(
        [
            MessageKey("user@s.whatsapp.net", "a"),
            MessageKey("user@s.whatsapp.net", "b"),
            MessageKey("user@s.whatsapp.net", "mine", from_me=True),
            MessageKey("group@g.us", "c", participant="sender@s.whatsapp.net"),
        ]
    )

    assert groups == [
        ("user@s.whatsapp.net", None, ["a", "b"]),
        ("group@g.us", "sender@s.whatsapp.net", ["c"]),
    ]


def test_receipt_message_ids_reads_list_children():
    node = BinaryNode(
        "receipt",
        {"id": "a", "from": "user@s.whatsapp.net"},
        [BinaryNode("list", {}, [BinaryNode("item", {"id": "b"}), BinaryNode("item", {"id": "c"})])],
    )

    assert receipt_message_ids(node) == ["a", "b", "c"]


def test_parse_retry_request_builds_baileys_style_key():
    node = BinaryNode(
        "receipt",
        {"id": "m1", "from": "user@s.whatsapp.net", "type": "retry"},
        [BinaryNode("retry", {"id": "m1", "count": "2", "error": "4"})],
    )

    request = parse_retry_request(node, {"me": {"id": "me@s.whatsapp.net"}})

    assert request is not None
    assert request.ids == ["m1"]
    assert request.retry_count == 2
    assert request.error_code == 4
    assert request.key.remote_jid == "user@s.whatsapp.net"
    assert request.key.id == "m1"
    assert request.key.from_me is True
    assert request.key.participant == "user@s.whatsapp.net"


def test_receipt_status_from_type_matches_baileys_status_mapping():
    assert receipt_status_from_type(None) == proto.WebMessageInfo.Status.DELIVERY_ACK
    assert receipt_status_from_type("sender") == proto.WebMessageInfo.Status.SERVER_ACK
    assert receipt_status_from_type("read") == proto.WebMessageInfo.Status.READ
    assert receipt_status_from_type("read-self") == proto.WebMessageInfo.Status.READ
    assert receipt_status_from_type("played") == proto.WebMessageInfo.Status.PLAYED
    assert receipt_status_from_type("unknown") is None


def test_parse_receipt_info_builds_direct_message_update_shape():
    node = BinaryNode("receipt", {"id": "m1", "from": "user@s.whatsapp.net", "type": "read", "t": "123"})

    info = parse_receipt_info(node, {"me": {"id": "me@s.whatsapp.net"}})

    assert isinstance(info, ReceiptInfo)
    assert info.ids == ["m1"]
    assert info.status == proto.WebMessageInfo.Status.READ
    assert info.timestamp == 123
    assert info.key.remote_jid == "user@s.whatsapp.net"
    assert info.key.from_me is True
    assert info.is_group_or_status is False


def test_parse_receipt_info_builds_group_user_receipt_shape():
    node = BinaryNode(
        "receipt",
        {
            "id": "m1",
            "from": "group@g.us",
            "participant": "sender@c.us",
            "type": "read",
            "t": "456",
        },
    )

    info = parse_receipt_info(node, {"me": {"id": "me@s.whatsapp.net"}})

    assert info is not None
    assert info.key.remote_jid == "group@g.us"
    assert info.key.participant == "sender@c.us"
    assert info.user_jid == "sender@s.whatsapp.net"
    assert info.receipt_timestamp_key == "read_timestamp"
    assert info.is_group_or_status is True
