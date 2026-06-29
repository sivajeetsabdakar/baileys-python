from __future__ import annotations

import asyncio

from baileys.events import EventEmitter
from baileys.generated import WAProto_pb2 as proto
from baileys.messages import MessageKey, MessageUpsert, WAMessage
from baileys.store import InMemoryStore, makeInMemoryStore


def _text_message(text: str) -> proto.Message:
    message = proto.Message()
    message.conversation = text
    return message


def test_in_memory_store_applies_messages_upsert_and_dedupes():
    store = InMemoryStore()
    message = WAMessage(
        key=MessageKey("user@s.whatsapp.net", "m1"),
        message=_text_message("hello"),
        message_timestamp=123,
        push_name="Alice",
    )

    first = store.apply_messages_upsert(MessageUpsert([message], type="notify"))
    second = store.apply_messages_upsert(MessageUpsert([message], type="notify"))

    assert makeInMemoryStore is InMemoryStore
    assert store.load_messages("user@s.whatsapp.net") == [message]
    assert store.chats["user@s.whatsapp.net"].conversation_timestamp == 123
    assert store.chats["user@s.whatsapp.net"].unread_count == 1
    assert store.contacts["user@s.whatsapp.net"].notify == "Alice"
    assert first.chats[0].id == "user@s.whatsapp.net"
    assert second.chats[0].id == "user@s.whatsapp.net"


def test_in_memory_store_bind_emits_chat_and_contact_upserts():
    async def scenario():
        events = EventEmitter()
        store = InMemoryStore()
        store.bind(events)
        chats = []
        contacts = []
        events.on("chats.upsert", lambda payload: chats.extend(payload))
        events.on("contacts.upsert", lambda payload: contacts.extend(payload))

        await events.emit(
            "messages.upsert",
            MessageUpsert(
                [
                    WAMessage(
                        key=MessageKey("group@g.us", "m1", participant="sender@s.whatsapp.net"),
                        message=_text_message("hello group"),
                        message_timestamp=456,
                        push_name="Sender",
                    )
                ]
            ),
        )

        assert store.load_messages("group@g.us")[0].message.conversation == "hello group"
        assert chats[0].id == "group@g.us"
        assert contacts[0].id == "sender@s.whatsapp.net"
        assert contacts[0].name == "Sender"

    asyncio.run(scenario())


def test_in_memory_store_applies_message_updates_and_receipts():
    store = InMemoryStore()
    message = WAMessage(
        key=MessageKey("user@s.whatsapp.net", "m1"),
        message=_text_message("hello"),
        message_timestamp=123,
    )
    store.apply_messages_upsert(MessageUpsert([message], type="notify"))

    store.apply_messages_update(
        [
            {
                "key": {"remote_jid": "user@s.whatsapp.net", "id": "m1", "from_me": False},
                "update": {"status": proto.WebMessageInfo.Status.READ, "message_timestamp": 456},
            }
        ]
    )
    store.apply_message_receipt_update(
        [
            {
                "key": {"remote_jid": "group@g.us", "id": "g1", "participant": "sender@s.whatsapp.net"},
                "receipt": {"user_jid": "reader@s.whatsapp.net", "read_timestamp": 789},
            }
        ]
    )

    assert store.chats["user@s.whatsapp.net"].unread_count == 0
    assert store.message_updates[("user@s.whatsapp.net", "m1", None)]["status"] == proto.WebMessageInfo.Status.READ
    assert store.message_receipts[("group@g.us", "g1", "sender@s.whatsapp.net")]["reader@s.whatsapp.net"] == {
        "read_timestamp": 789
    }


def test_in_memory_store_derives_reaction_events():
    async def scenario():
        events = EventEmitter()
        store = InMemoryStore()
        store.bind(events)
        reactions = []
        events.on("messages.reaction", lambda payload: reactions.extend(payload))

        message = proto.Message()
        message.reactionMessage.key.remoteJid = "chat@s.whatsapp.net"
        message.reactionMessage.key.id = "target"
        message.reactionMessage.text = "like"
        message.reactionMessage.senderTimestampMs = 1234

        await events.emit(
            "messages.upsert",
            MessageUpsert(
                [
                    WAMessage(
                        key=MessageKey("chat@s.whatsapp.net", "reaction-1", participant="sender@s.whatsapp.net"),
                        message=message,
                    )
                ]
            ),
        )

        assert reactions == [
            {
                "key": {
                    "remote_jid": "chat@s.whatsapp.net",
                    "id": "target",
                    "from_me": False,
                    "participant": None,
                },
                "reaction": {
                    "text": "like",
                    "sender_timestamp_ms": 1234,
                    "from_jid": "sender@s.whatsapp.net",
                },
            }
        ]
        assert store.reactions[("chat@s.whatsapp.net", "target", None)] == reactions

    asyncio.run(scenario())
