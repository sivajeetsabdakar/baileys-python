from __future__ import annotations

import base64
import time

from baileys.auth_state import MemorySignalKeyStore
from baileys.generated import WAProto_pb2 as proto
from baileys.privacy_tokens import build_tc_token_from_jid, store_tc_tokens_from_iq_result
from baileys.reporting import get_message_reporting_token, should_include_reporting_token
from baileys.wabinary import BinaryNode


def test_reporting_token_filters_message_and_builds_node():
    message = proto.Message()
    message.conversation = "hello"
    message.messageContextInfo.messageSecret = b"s" * 32
    payload = message.SerializeToString()

    node = get_message_reporting_token(
        payload,
        message,
        {"id": "msg-1", "remoteJid": "123@s.whatsapp.net", "fromMe": True},
    )

    assert should_include_reporting_token(message) is True
    assert node is not None
    assert node.tag == "reporting"
    assert node.content[0].tag == "reporting_token"
    assert node.content[0].attrs["v"] == "2"
    assert len(node.content[0].content) == 16

    reaction = proto.Message()
    reaction.reactionMessage.text = "+"
    assert should_include_reporting_token(reaction) is False


def test_privacy_token_store_and_build_round_trip():
    store = MemorySignalKeyStore()
    timestamp = str(int(time.time()))
    result = BinaryNode(
        "iq",
        {},
        [
            BinaryNode(
                "tokens",
                {},
                [BinaryNode("token", {"type": "trusted_contact", "t": timestamp}, b"secret-token")],
            )
        ],
    )

    stored = store_tc_tokens_from_iq_result(store, result, "123@s.whatsapp.net")
    assert stored == ["123@s.whatsapp.net"]
    entry = store.get("tctoken", "123@s.whatsapp.net")
    assert base64.b64decode(entry["token"]) == b"secret-token"

    content = build_tc_token_from_jid(store, "123@s.whatsapp.net")
    assert content is not None
    assert content[0].tag == "tctoken"
    assert content[0].attrs == {"t": timestamp}
    assert content[0].content == b"secret-token"

    index = store.get("tctoken", "__index")
    assert base64.b64decode(index["token"]).decode("utf-8") == '["123@s.whatsapp.net"]'
