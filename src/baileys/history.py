from __future__ import annotations

import zlib
from dataclasses import dataclass, field
from typing import Any

from .generated import WAProto_pb2 as proto
from .jid import isHostedLidUser, isHostedPnUser, isLidUser, isPnUser
from .media import download_external_blob


@dataclass(frozen=True)
class LidPnMapping:
    lid: str
    pn: str


@dataclass(frozen=True)
class HistoryChat:
    id: str
    name: str | None = None
    conversation_timestamp: int | None = None
    unread_count: int = 0
    raw: proto.Conversation | None = None


@dataclass(frozen=True)
class HistoryContact:
    id: str
    name: str | None = None
    notify: str | None = None
    username: str | None = None
    lid: str | None = None
    phone_number: str | None = None


@dataclass(frozen=True)
class HistorySyncResult:
    chats: list[HistoryChat] = field(default_factory=list)
    contacts: list[HistoryContact] = field(default_factory=list)
    messages: list[proto.WebMessageInfo] = field(default_factory=list)
    lid_pn_mappings: list[LidPnMapping] = field(default_factory=list)
    past_participants: list[Any] = field(default_factory=list)
    sync_type: int | None = None
    progress: int | None = None
    chunk_order: int | None = None
    peer_data_request_session_id: str | None = None


def process_history_sync(item: proto.HistorySync) -> HistorySyncResult:
    messages: list[proto.WebMessageInfo] = []
    contacts: list[HistoryContact] = []
    chats: list[HistoryChat] = []
    mappings: list[LidPnMapping] = []

    for mapping in item.phoneNumberToLidMappings:
        if mapping.lidJid and mapping.pnJid:
            mappings.append(LidPnMapping(lid=mapping.lidJid, pn=mapping.pnJid))

    if item.syncType in {
        proto.HistorySync.INITIAL_BOOTSTRAP,
        proto.HistorySync.RECENT,
        proto.HistorySync.FULL,
        proto.HistorySync.ON_DEMAND,
    }:
        for conversation in item.conversations:
            contacts.append(
                HistoryContact(
                    id=conversation.id,
                    name=conversation.displayName or conversation.name or conversation.username or None,
                    username=conversation.username or None,
                    lid=conversation.lidJid or conversation.accountLid or None,
                    phone_number=conversation.pnJid or None,
                )
            )
            if isLidUser(conversation.id) or isHostedLidUser(conversation.id):
                if conversation.pnJid:
                    mappings.append(LidPnMapping(lid=conversation.id, pn=conversation.pnJid))
                else:
                    pn = _extract_pn_from_messages(conversation.messages)
                    if pn:
                        mappings.append(LidPnMapping(lid=conversation.id, pn=pn))
            elif (isPnUser(conversation.id) or isHostedPnUser(conversation.id)) and conversation.lidJid:
                mappings.append(LidPnMapping(lid=conversation.lidJid, pn=conversation.id))

            for history_message in conversation.messages:
                if history_message.HasField("message"):
                    messages.append(history_message.message)

            chats.append(
                HistoryChat(
                    id=conversation.id,
                    name=conversation.displayName or conversation.name or None,
                    conversation_timestamp=int(conversation.conversationTimestamp)
                    if conversation.conversationTimestamp
                    else None,
                    unread_count=int(conversation.unreadCount) if conversation.unreadCount else 0,
                    raw=conversation,
                )
            )
    elif item.syncType == proto.HistorySync.PUSH_NAME:
        for pushname in item.pushnames:
            if pushname.id:
                contacts.append(HistoryContact(id=pushname.id, notify=pushname.pushname or None))

    return HistorySyncResult(
        chats=chats,
        contacts=contacts,
        messages=messages,
        lid_pn_mappings=mappings,
        past_participants=list(item.pastParticipants),
        sync_type=int(item.syncType),
        progress=int(item.progress) if item.progress else None,
    )


async def download_history_sync(notification: proto.Message.HistorySyncNotification, *, timeout: int = 45) -> proto.HistorySync:
    if notification.initialHistBootstrapInlinePayload:
        data = zlib.decompress(notification.initialHistBootstrapInlinePayload)
    else:
        blob = proto.ExternalBlobReference()
        blob.directPath = notification.directPath
        blob.mediaKey = notification.mediaKey
        blob.fileEncSha256 = notification.fileEncSha256
        blob.fileSha256 = notification.fileSha256
        blob.fileSizeBytes = int(notification.fileLength) if notification.fileLength else 0
        data = zlib.decompress(await download_external_blob(blob, "md-msg-hist", timeout=timeout))
    history = proto.HistorySync()
    history.ParseFromString(data)
    return history


async def download_and_process_history_sync_notification(
    notification: proto.Message.HistorySyncNotification,
    *,
    timeout: int = 45,
) -> HistorySyncResult:
    history = await download_history_sync(notification, timeout=timeout)
    result = process_history_sync(history)
    return HistorySyncResult(
        chats=result.chats,
        contacts=result.contacts,
        messages=result.messages,
        lid_pn_mappings=result.lid_pn_mappings,
        past_participants=result.past_participants,
        sync_type=int(notification.syncType) if notification.syncType else result.sync_type,
        progress=int(notification.progress) if notification.progress else result.progress,
        chunk_order=int(notification.chunkOrder) if notification.chunkOrder else None,
        peer_data_request_session_id=notification.peerDataRequestSessionId or None,
    )


def get_history_sync_notification(message: proto.Message) -> proto.Message.HistorySyncNotification | None:
    try:
        if not message.HasField("protocolMessage"):
            return None
        protocol = message.protocolMessage
        if not protocol.HasField("historySyncNotification"):
            return None
        return protocol.historySyncNotification
    except ValueError:
        return None


def _extract_pn_from_messages(messages: Any) -> str | None:
    for item in messages:
        if not item.HasField("message"):
            continue
        message = item.message
        if not message.HasField("key") or not message.key.fromMe or not message.userReceipt:
            continue
        user_jid = message.userReceipt[0].userJid
        if user_jid and (isPnUser(user_jid) or isHostedPnUser(user_jid)):
            return user_jid
    return None
