from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .events import EventEmitter, ListenerRef
from .messages import MessageKey, MessageUpsert, WAMessage


@dataclass
class Chat:
    id: str
    conversation_timestamp: int | None = None
    unread_count: int = 0
    name: str | None = None


@dataclass
class Contact:
    id: str
    name: str | None = None
    notify: str | None = None


class InMemoryStore:
    def __init__(self) -> None:
        self.messages: dict[str, list[WAMessage]] = {}
        self.chats: dict[str, Chat] = {}
        self.contacts: dict[str, Contact] = {}
        self.message_updates: dict[tuple[str | None, str | None, str | None], dict[str, Any]] = {}
        self.message_receipts: dict[tuple[str | None, str | None, str | None], dict[str, dict[str, Any]]] = {}
        self.reactions: dict[tuple[str | None, str | None, str | None], list[dict[str, Any]]] = {}
        self._listener_refs: list[ListenerRef] = []

    def bind(self, events: EventEmitter) -> None:
        async def on_messages_upsert(upsert: MessageUpsert) -> None:
            result = self.apply_messages_upsert(upsert)
            if result.chats:
                await events.emit("chats.upsert", result.chats)
            if result.contacts:
                await events.emit("contacts.upsert", result.contacts)
            if result.reactions:
                await events.emit("messages.reaction", result.reactions)

        async def on_messages_update(updates: list[dict[str, Any]]) -> None:
            result = self.apply_messages_update(updates)
            if result.chats:
                await events.emit("chats.update", result.chats)

        async def on_message_receipt_update(updates: list[dict[str, Any]]) -> None:
            self.apply_message_receipt_update(updates)

        self._listener_refs.append(events.on("messages.upsert", on_messages_upsert))
        self._listener_refs.append(events.on("messages.update", on_messages_update))
        self._listener_refs.append(events.on("message-receipt.update", on_message_receipt_update))

    def unbind(self, events: EventEmitter) -> None:
        for ref in self._listener_refs:
            events.off(ref.event, ref)
        self._listener_refs.clear()

    def apply_messages_upsert(self, upsert: MessageUpsert) -> "StoreUpdate":
        changed_chats: dict[str, Chat] = {}
        changed_contacts: dict[str, Contact] = {}
        reactions: list[dict[str, Any]] = []
        for message in upsert.messages:
            jid = message.key.remote_jid
            if not jid:
                continue

            bucket = self.messages.setdefault(jid, [])
            is_new = not _has_message(bucket, message)
            if is_new:
                bucket.append(message)

            chat = self.chats.get(jid)
            if chat is None:
                chat = Chat(id=jid)
                self.chats[jid] = chat
            if message.message_timestamp is not None:
                if chat.conversation_timestamp is None or message.message_timestamp > chat.conversation_timestamp:
                    chat.conversation_timestamp = message.message_timestamp
            if message.push_name and not chat.name:
                chat.name = message.push_name
            if is_new and upsert.type == "notify" and not message.key.from_me:
                chat.unread_count += 1
            changed_chats[jid] = chat

            if message.push_name:
                contact_id = message.key.participant or jid
                contact = self.contacts.get(contact_id)
                if contact is None:
                    contact = Contact(id=contact_id)
                    self.contacts[contact_id] = contact
                contact.notify = message.push_name
                if not contact.name:
                    contact.name = message.push_name
                changed_contacts[contact_id] = contact

            reaction = _reaction_update(message)
            if reaction is not None:
                reaction_key = _message_key_tuple(reaction["key"])
                self.reactions.setdefault(reaction_key, []).append(reaction)
                reactions.append(reaction)

        return StoreUpdate(chats=list(changed_chats.values()), contacts=list(changed_contacts.values()), reactions=reactions)

    def apply_messages_update(self, updates: list[dict[str, Any]]) -> "StoreUpdate":
        changed_chats: dict[str, Chat] = {}
        for item in updates:
            key = item.get("key") or {}
            update = item.get("update") or {}
            self.message_updates.setdefault(_message_key_tuple(key), {}).update(update)
            jid = key.get("remote_jid")
            if jid and update.get("status") is not None:
                chat = self.chats.get(jid)
                if chat is not None and not key.get("from_me") and update.get("status") >= 3:
                    chat.unread_count = 0
                    changed_chats[jid] = chat
        return StoreUpdate(chats=list(changed_chats.values()))

    def apply_message_receipt_update(self, updates: list[dict[str, Any]]) -> "StoreUpdate":
        for item in updates:
            key = item.get("key") or {}
            receipt = item.get("receipt") or {}
            user_jid = receipt.get("user_jid")
            if not user_jid:
                continue
            stored = dict(receipt)
            stored.pop("user_jid", None)
            self.message_receipts.setdefault(_message_key_tuple(key), {}).setdefault(user_jid, {}).update(stored)
        return StoreUpdate()

    def load_messages(self, jid: str, count: int | None = None) -> list[WAMessage]:
        messages = self.messages.get(jid, [])
        return list(messages if count is None else messages[-count:])


@dataclass(frozen=True)
class StoreUpdate:
    chats: list[Chat] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    reactions: list[dict[str, Any]] = field(default_factory=list)


def _has_message(messages: Iterable[WAMessage], candidate: WAMessage) -> bool:
    for message in messages:
        if message.key.id and message.key.id == candidate.key.id:
            return True
    return False


def _message_key_tuple(key: dict[str, Any] | MessageKey) -> tuple[str | None, str | None, str | None]:
    if isinstance(key, MessageKey):
        return key.remote_jid, key.id, key.participant
    return key.get("remote_jid"), key.get("id"), key.get("participant")


def _reaction_update(message: WAMessage) -> dict[str, Any] | None:
    if message.message is None:
        return None
    try:
        if not message.message.HasField("reactionMessage"):
            return None
    except ValueError:
        return None

    reaction = message.message.reactionMessage
    key = reaction.key
    return {
        "key": {
            "remote_jid": key.remoteJid or message.key.remote_jid,
            "id": key.id or None,
            "from_me": key.fromMe,
            "participant": key.participant or None,
        },
        "reaction": {
            "text": reaction.text,
            "sender_timestamp_ms": reaction.senderTimestampMs if reaction.senderTimestampMs else None,
            "from_jid": message.key.participant or message.key.remote_jid,
        },
    }


makeInMemoryStore = InMemoryStore
make_in_memory_store = InMemoryStore
