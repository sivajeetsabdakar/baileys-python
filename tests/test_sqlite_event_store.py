from __future__ import annotations

import asyncio

import baileys as b
from baileys.auth_state import AuthState, JsonCredentialStore
from baileys.events import EventEmitter
from baileys.generated import WAProto_pb2 as proto
from baileys.history import HistoryChat, HistoryContact, HistorySyncResult, LidPnMapping
from baileys.messages import MessageKey, MessageUpsert, WAMessage
from baileys.sqlite_store import SQLiteEventStore, makeSqliteEventStore
from baileys.socket import make_socket
from baileys.wabinary import BinaryNode


def _text_message(text: str) -> proto.Message:
    message = proto.Message()
    message.conversation = text
    return message


def test_sqlite_event_store_persists_messages_chats_contacts_and_dedupes(tmp_path):
    db_path = tmp_path / "events.db"
    store = SQLiteEventStore(db_path)
    message = WAMessage(
        key=MessageKey("user@s.whatsapp.net", "m1"),
        message=_text_message("hello"),
        message_timestamp=123,
        push_name="Alice",
    )

    first = store.apply_messages_upsert(MessageUpsert([message], type="notify"))
    second = store.apply_messages_upsert(MessageUpsert([message], type="notify"))
    reopened = SQLiteEventStore(db_path)

    loaded = reopened.load_messages("user@s.whatsapp.net")
    assert makeSqliteEventStore is SQLiteEventStore
    assert b.makeSqliteEventStore is SQLiteEventStore
    assert loaded[0].message.conversation == "hello"
    assert reopened.load_chat("user@s.whatsapp.net").conversation_timestamp == 123
    assert reopened.load_chat("user@s.whatsapp.net").unread_count == 1
    assert reopened.load_contact("user@s.whatsapp.net").notify == "Alice"
    assert first.chats[0].id == "user@s.whatsapp.net"
    assert second.chats[0].id == "user@s.whatsapp.net"


def test_sqlite_event_store_bind_emits_updates(tmp_path):
    async def scenario():
        events = EventEmitter()
        store = SQLiteEventStore(tmp_path / "events.db")
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


def test_sqlite_event_store_persists_updates_receipts_reactions_lid_and_app_state(tmp_path):
    store = SQLiteEventStore(tmp_path / "events.db")
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

    reaction_message = proto.Message()
    reaction_message.reactionMessage.key.remoteJid = "user@s.whatsapp.net"
    reaction_message.reactionMessage.key.id = "m1"
    reaction_message.reactionMessage.text = "like"
    reaction_message.reactionMessage.senderTimestampMs = 999
    store.apply_messages_upsert(
        MessageUpsert(
            [
                WAMessage(
                    key=MessageKey("user@s.whatsapp.net", "reaction-1", participant="sender@s.whatsapp.net"),
                    message=reaction_message,
                )
            ],
            type="append",
        )
    )
    store.save_lid_pn_mapping("123:1@lid", "123@s.whatsapp.net", source="test")
    store.save_app_state("regular_low", {"version": {"hash": "abc", "indexValueMap": []}})

    reopened = SQLiteEventStore(tmp_path / "events.db")

    assert reopened.load_chat("user@s.whatsapp.net").unread_count == 0
    assert reopened.load_message_update("user@s.whatsapp.net", "m1")["status"] == proto.WebMessageInfo.Status.READ
    assert reopened.load_message_receipt("group@g.us", "g1", "sender@s.whatsapp.net", "reader@s.whatsapp.net") == {
        "read_timestamp": 789
    }
    assert reopened.get_pn_for_lid("123:1@lid") == "123@s.whatsapp.net"
    assert reopened.get_lid_for_pn("123@s.whatsapp.net") == "123@lid"
    assert reopened.load_app_state("regular_low") == {"version": {"hash": "abc", "indexValueMap": []}}


def test_sqlite_event_store_applies_history_sync(tmp_path):
    info = proto.WebMessageInfo()
    info.key.remoteJid = "history@s.whatsapp.net"
    info.key.id = "hm1"
    info.message.conversation = "from history"
    info.messageTimestamp = 321
    info.pushName = "Historian"
    history = HistorySyncResult(
        chats=[HistoryChat(id="history@s.whatsapp.net", name="History", conversation_timestamp=321, unread_count=2)],
        contacts=[HistoryContact(id="contact@s.whatsapp.net", name="Contact", notify="Notify")],
        messages=[info],
        lid_pn_mappings=[LidPnMapping("999:1@lid", "999@s.whatsapp.net")],
    )

    store = SQLiteEventStore(tmp_path / "events.db")
    update = store.apply_history_sync(history)
    reopened = SQLiteEventStore(tmp_path / "events.db")

    assert update.chats[0].name == "History"
    assert reopened.load_chat("history@s.whatsapp.net").unread_count == 2
    assert reopened.load_contact("contact@s.whatsapp.net").notify == "Notify"
    assert reopened.load_messages("history@s.whatsapp.net")[0].message.conversation == "from history"
    assert reopened.get_pn_for_lid("999:1@lid") == "999@s.whatsapp.net"


def test_socket_uses_sqlite_event_store_for_lid_pn_resolution(tmp_path):
    creds = JsonCredentialStore(tmp_path / "creds.json")
    creds.save_credentials({"me": {"id": "me@s.whatsapp.net"}})
    event_store = SQLiteEventStore(tmp_path / "events.db")
    event_store.save_lid_pn_mapping("999:1@lid", "123@s.whatsapp.net", source="test")

    client = make_socket(AuthState.from_store(creds), event_store=event_store)

    assert client.store is event_store
    assert client._lid_for_pn("123@s.whatsapp.net") == "999@lid"
    assert client._pn_for_lid("999:1@lid") == "123@s.whatsapp.net"


def test_group_metadata_persists_lid_pn_mapping_to_sqlite_event_store(tmp_path):
    async def scenario():
        creds = JsonCredentialStore(tmp_path / "creds.json")
        creds.save_credentials({"me": {"id": "me@s.whatsapp.net"}})
        event_store = SQLiteEventStore(tmp_path / "events.db")
        client = make_socket(AuthState.from_store(creds), event_store=event_store)

        async def fake_query_checked(node, *, timeout=30, drive_receive=True):
            return BinaryNode(
                "iq",
                {"id": "1", "type": "result"},
                [
                    BinaryNode(
                        "group",
                        {"jid": "group@g.us", "subject": "Group"},
                        [
                            BinaryNode(
                                "participant",
                                {"jid": "999:1@lid", "phone_number": "123@s.whatsapp.net"},
                            )
                        ],
                    )
                ],
            )

        client._query_checked = fake_query_checked  # type: ignore[method-assign]

        metadata = await client.group_metadata("group@g.us")

        assert metadata.participants[0].jid == "999:1@lid"
        assert event_store.get_pn_for_lid("999:1@lid") == "123@s.whatsapp.net"
        assert event_store.get_lid_for_pn("123@s.whatsapp.net") == "999@lid"
        assert client.auth_state.credentials["lid_pn_mappings"]["999@lid"] == "123@s.whatsapp.net"

    asyncio.run(scenario())
