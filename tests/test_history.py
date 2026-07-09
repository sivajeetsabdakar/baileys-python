from __future__ import annotations

import asyncio
import zlib

from baileys.generated import WAProto_pb2 as proto
from baileys.events import EventEmitter
from baileys.history import (
    download_and_process_history_sync_notification,
    get_history_sync_notification,
    process_history_sync,
)
from baileys.store import InMemoryStore


def test_process_history_sync_extracts_chats_contacts_messages_and_mappings():
    history = proto.HistorySync()
    history.syncType = proto.HistorySync.RECENT
    history.progress = 77
    history.phoneNumberToLidMappings.add(lidJid="123:1@lid", pnJid="123@s.whatsapp.net")
    conversation = history.conversations.add()
    conversation.id = "chat@s.whatsapp.net"
    conversation.name = "Chat"
    conversation.conversationTimestamp = 123
    conversation.unreadCount = 2
    message = conversation.messages.add().message
    message.key.remoteJid = conversation.id
    message.key.id = "m1"
    message.messageTimestamp = 123

    result = process_history_sync(history)

    assert result.sync_type == proto.HistorySync.RECENT
    assert result.progress == 77
    assert result.chats[0].id == "chat@s.whatsapp.net"
    assert result.contacts[0].name == "Chat"
    assert result.messages[0].key.id == "m1"
    assert result.lid_pn_mappings[0].lid == "123:1@lid"


def test_process_history_sync_extracts_pushnames():
    history = proto.HistorySync()
    history.syncType = proto.HistorySync.PUSH_NAME
    history.pushnames.add(id="user@s.whatsapp.net", pushname="User")

    result = process_history_sync(history)

    assert result.contacts[0].id == "user@s.whatsapp.net"
    assert result.contacts[0].notify == "User"


def test_download_and_process_history_sync_notification_inflates_inline_payload():
    async def scenario():
        history = proto.HistorySync()
        history.syncType = proto.HistorySync.RECENT
        conversation = history.conversations.add()
        conversation.id = "chat@s.whatsapp.net"
        message = conversation.messages.add().message
        message.key.remoteJid = conversation.id
        message.key.id = "m1"

        notification = proto.Message.HistorySyncNotification()
        notification.syncType = proto.Message.RECENT
        notification.progress = 100
        notification.chunkOrder = 3
        notification.initialHistBootstrapInlinePayload = zlib.compress(history.SerializeToString())

        result = await download_and_process_history_sync_notification(notification)

        assert result.sync_type == proto.Message.RECENT
        assert result.progress == 100
        assert result.chunk_order == 3
        assert result.messages[0].key.id == "m1"

    asyncio.run(scenario())


def test_get_history_sync_notification_finds_protocol_message():
    message = proto.Message()
    message.protocolMessage.historySyncNotification.progress = 55

    notification = get_history_sync_notification(message)

    assert notification is not None
    assert notification.progress == 55


def test_in_memory_store_applies_history_sync_events():
    async def scenario():
        history = proto.HistorySync()
        history.syncType = proto.HistorySync.RECENT
        conversation = history.conversations.add()
        conversation.id = "chat@s.whatsapp.net"
        conversation.name = "Chat"
        conversation.conversationTimestamp = 456
        message = conversation.messages.add().message
        message.key.remoteJid = conversation.id
        message.key.id = "m1"
        message.message.conversation = "hello"
        message.messageTimestamp = 456

        events = EventEmitter()
        store = InMemoryStore()
        store.bind(events)

        await events.emit("messaging-history.set", process_history_sync(history))
        await events.emit("messaging-history.set", process_history_sync(history))

        assert store.chats["chat@s.whatsapp.net"].name == "Chat"
        assert store.chats["chat@s.whatsapp.net"].conversation_timestamp == 456
        assert store.contacts["chat@s.whatsapp.net"].name == "Chat"
        assert len(store.messages["chat@s.whatsapp.net"]) == 1
        assert store.messages["chat@s.whatsapp.net"][0].message.conversation == "hello"

    asyncio.run(scenario())
