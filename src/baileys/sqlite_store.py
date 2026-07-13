from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .auth_state import AuthState
from .events import EventEmitter
from .generated import WAProto_pb2 as proto
from .history import HistorySyncResult
from .messages import MessageKey, MessageUpsert, WAMessage
from .replay import binary_node_from_json, binary_node_to_json
from .store import Chat, Contact, StoreUpdate
from .wabinary import BinaryNode


@dataclass(frozen=True)
class SQLiteCredentialStore:
    path: Path

    def __init__(self, path: str | Path) -> None:
        object.__setattr__(self, "path", Path(path))
        _init_schema(self.path)

    def load_credentials(self) -> dict[str, Any]:
        with _connect(self.path) as db:
            row = db.execute("select value from credentials where name = 'default'").fetchone()
        if row is None:
            return {}
        return json.loads(str(row["value"]))

    def save_credentials(self, credentials: dict[str, Any]) -> None:
        payload = json.dumps(credentials, indent=2, sort_keys=True)
        with _connect(self.path) as db:
            db.execute(
                """
                insert into credentials(name, value)
                values('default', ?)
                on conflict(name) do update set value = excluded.value
                """,
                (payload,),
            )


@dataclass(frozen=True)
class SQLiteSignalKeyStore:
    path: Path

    def __init__(self, path: str | Path) -> None:
        object.__setattr__(self, "path", Path(path))
        _init_schema(self.path)

    def get(self, namespace: str, key: str) -> Any:
        with _connect(self.path) as db:
            row = db.execute(
                "select value from signal_keys where namespace = ? and key = ?",
                (namespace, key),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["value"]))

    def set(self, namespace: str, key: str, value: Any) -> None:
        payload = json.dumps(value, indent=2, sort_keys=True)
        with _connect(self.path) as db:
            db.execute(
                """
                insert into signal_keys(namespace, key, value)
                values(?, ?, ?)
                on conflict(namespace, key) do update set value = excluded.value
                """,
                (namespace, key, payload),
            )

    def delete(self, namespace: str, key: str) -> bool:
        with _connect(self.path) as db:
            cursor = db.execute(
                "delete from signal_keys where namespace = ? and key = ?",
                (namespace, key),
            )
            return cursor.rowcount > 0


@dataclass(frozen=True)
class SQLiteReplayStore:
    path: Path

    def __init__(self, path: str | Path) -> None:
        object.__setattr__(self, "path", Path(path))
        _init_schema(self.path)

    def save_recent_outbound(self, message_id: str, node: BinaryNode, expires_at: float) -> None:
        if not message_id:
            return
        payload = json.dumps(binary_node_to_json(node), separators=(",", ":"), sort_keys=True)
        with _connect(self.path) as db:
            db.execute(
                """
                insert into recent_outbound(message_id, node_json, expires_at)
                values(?, ?, ?)
                on conflict(message_id) do update set
                    node_json = excluded.node_json,
                    expires_at = excluded.expires_at
                """,
                (message_id, payload, float(expires_at)),
            )

    def load_recent_outbound(self, message_id: str) -> BinaryNode | None:
        with _connect(self.path) as db:
            row = db.execute(
                "select node_json, expires_at from recent_outbound where message_id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) <= time.time():
                db.execute("delete from recent_outbound where message_id = ?", (message_id,))
                return None
        return binary_node_from_json(json.loads(str(row["node_json"])))

    def delete_recent_outbound(self, message_id: str) -> None:
        with _connect(self.path) as db:
            db.execute("delete from recent_outbound where message_id = ?", (message_id,))

    def prune_expired(self, now: float | None = None) -> int:
        cutoff = time.time() if now is None else now
        with _connect(self.path) as db:
            cursor = db.execute("delete from recent_outbound where expires_at <= ?", (float(cutoff),))
            return cursor.rowcount


@dataclass(frozen=True)
class SQLiteEventStore:
    path: Path

    def __init__(self, path: str | Path) -> None:
        object.__setattr__(self, "path", Path(path))
        object.__setattr__(self, "_listener_refs", [])
        _init_schema(self.path)

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

        async def on_history_set(history: HistorySyncResult) -> None:
            self.apply_history_sync(history)

        self._listener_refs.append(events.on("messages.upsert", on_messages_upsert))
        self._listener_refs.append(events.on("messages.update", on_messages_update))
        self._listener_refs.append(events.on("message-receipt.update", on_message_receipt_update))
        self._listener_refs.append(events.on("messaging-history.set", on_history_set))

    def unbind(self, events: EventEmitter) -> None:
        for ref in list(self._listener_refs):
            events.off(ref.event, ref)
        self._listener_refs.clear()

    def apply_messages_upsert(self, upsert: MessageUpsert) -> StoreUpdate:
        changed_chats: dict[str, Chat] = {}
        changed_contacts: dict[str, Contact] = {}
        reactions: list[dict[str, Any]] = []
        with _connect(self.path) as db:
            for message in upsert.messages:
                jid = message.key.remote_jid
                if not jid:
                    continue
                is_new = self._upsert_message(db, message)
                chat = self._load_chat(db, jid) or Chat(id=jid)
                if message.message_timestamp is not None:
                    if chat.conversation_timestamp is None or message.message_timestamp > chat.conversation_timestamp:
                        chat.conversation_timestamp = message.message_timestamp
                if message.push_name and not chat.name:
                    chat.name = message.push_name
                if is_new and upsert.type == "notify" and not message.key.from_me:
                    chat.unread_count += 1
                self._save_chat(db, chat)
                changed_chats[jid] = chat

                if message.push_name:
                    contact_id = message.key.participant or jid
                    contact = self._load_contact(db, contact_id) or Contact(id=contact_id)
                    contact.notify = message.push_name
                    if not contact.name:
                        contact.name = message.push_name
                    self._save_contact(db, contact)
                    changed_contacts[contact_id] = contact

                reaction = _reaction_update(message)
                if reaction is not None:
                    self._save_reaction(db, reaction)
                    reactions.append(reaction)
        return StoreUpdate(chats=list(changed_chats.values()), contacts=list(changed_contacts.values()), reactions=reactions)

    def apply_messages_update(self, updates: list[dict[str, Any]]) -> StoreUpdate:
        changed_chats: dict[str, Chat] = {}
        with _connect(self.path) as db:
            for item in updates:
                key = item.get("key") or {}
                update = item.get("update") or {}
                remote_jid, message_id, participant = _message_key_tuple(key)
                existing = self._load_message_update(db, remote_jid, message_id, participant)
                existing.update(update)
                db.execute(
                    """
                    insert into message_updates(remote_jid, message_id, participant, update_json, updated_at)
                    values(?, ?, ?, ?, ?)
                    on conflict(remote_jid, message_id, participant) do update set
                        update_json = excluded.update_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        remote_jid or "",
                        message_id or "",
                        participant or "",
                        _json_dumps(existing),
                        int(time.time()),
                    ),
                )
                if remote_jid and update.get("status") is not None:
                    chat = self._load_chat(db, remote_jid)
                    if chat is not None and not key.get("from_me") and update.get("status") >= 3:
                        chat.unread_count = 0
                        self._save_chat(db, chat)
                        changed_chats[remote_jid] = chat
        return StoreUpdate(chats=list(changed_chats.values()))

    def apply_message_receipt_update(self, updates: list[dict[str, Any]]) -> StoreUpdate:
        with _connect(self.path) as db:
            for item in updates:
                key = item.get("key") or {}
                receipt = dict(item.get("receipt") or {})
                user_jid = receipt.pop("user_jid", None)
                if not user_jid:
                    continue
                remote_jid, message_id, participant = _message_key_tuple(key)
                existing = self.load_message_receipt(remote_jid, message_id, participant, user_jid)
                existing.update(receipt)
                db.execute(
                    """
                    insert into message_receipts(remote_jid, message_id, participant, user_jid, receipt_json, updated_at)
                    values(?, ?, ?, ?, ?, ?)
                    on conflict(remote_jid, message_id, participant, user_jid) do update set
                        receipt_json = excluded.receipt_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        remote_jid or "",
                        message_id or "",
                        participant or "",
                        user_jid,
                        _json_dumps(existing),
                        int(time.time()),
                    ),
                )
        return StoreUpdate()

    def apply_history_sync(self, history: HistorySyncResult) -> StoreUpdate:
        changed_chats: dict[str, Chat] = {}
        changed_contacts: dict[str, Contact] = {}
        with _connect(self.path) as db:
            for item in history.chats:
                chat = self._load_chat(db, item.id) or Chat(id=item.id)
                if item.conversation_timestamp is not None:
                    chat.conversation_timestamp = item.conversation_timestamp
                if item.name:
                    chat.name = item.name
                chat.unread_count = item.unread_count
                self._save_chat(db, chat)
                changed_chats[item.id] = chat

            for item in history.contacts:
                contact = self._load_contact(db, item.id) or Contact(id=item.id)
                if item.name:
                    contact.name = item.name
                if item.notify:
                    contact.notify = item.notify
                self._save_contact(db, contact)
                changed_contacts[item.id] = contact

            for mapping in history.lid_pn_mappings:
                self._save_lid_pn_mapping(db, mapping.lid, mapping.pn, source="history")

            for info in history.messages:
                jid = info.key.remoteJid or None
                if not jid:
                    continue
                message = WAMessage(
                    key=MessageKey(
                        remote_jid=jid,
                        id=info.key.id or None,
                        from_me=info.key.fromMe,
                        participant=info.key.participant or None,
                    ),
                    message=info.message if info.HasField("message") else None,
                    message_timestamp=int(info.messageTimestamp) if info.messageTimestamp else None,
                    push_name=info.pushName or None,
                    broadcast=bool(info.broadcast),
                )
                self._upsert_message(db, message)
        return StoreUpdate(chats=list(changed_chats.values()), contacts=list(changed_contacts.values()))

    def load_messages(self, jid: str, count: int | None = None) -> list[WAMessage]:
        with _connect(self.path) as db:
            if count is None:
                rows = db.execute(
                    """
                    select * from messages
                    where remote_jid = ?
                    order by coalesce(timestamp, 0), rowid
                    """,
                    (jid,),
                ).fetchall()
            else:
                rows = db.execute(
                    """
                    select * from messages
                    where remote_jid = ?
                    order by coalesce(timestamp, 0) desc, rowid desc
                    limit ?
                    """,
                    (jid, int(count)),
                ).fetchall()
                rows = list(reversed(rows))
        return [_message_from_row(row) for row in rows]

    def load_message(self, jid: str, message_id: str, participant: str | None = None) -> WAMessage | None:
        with _connect(self.path) as db:
            row = db.execute(
                """
                select * from messages
                where remote_jid = ? and message_id = ? and participant = ?
                """,
                (jid, message_id, participant or ""),
            ).fetchone()
        return _message_from_row(row) if row is not None else None

    def load_chat(self, jid: str) -> Chat | None:
        with _connect(self.path) as db:
            return self._load_chat(db, jid)

    def load_contact(self, jid: str) -> Contact | None:
        with _connect(self.path) as db:
            return self._load_contact(db, jid)

    def load_message_update(
        self,
        remote_jid: str | None,
        message_id: str | None,
        participant: str | None = None,
    ) -> dict[str, Any]:
        with _connect(self.path) as db:
            return self._load_message_update(db, remote_jid, message_id, participant)

    def load_message_receipt(
        self,
        remote_jid: str | None,
        message_id: str | None,
        participant: str | None,
        user_jid: str,
    ) -> dict[str, Any]:
        with _connect(self.path) as db:
            row = db.execute(
                """
                select receipt_json from message_receipts
                where remote_jid = ? and message_id = ? and participant = ? and user_jid = ?
                """,
                (remote_jid or "", message_id or "", participant or "", user_jid),
            ).fetchone()
        return json.loads(str(row["receipt_json"])) if row is not None else {}

    def save_lid_pn_mapping(self, lid_jid: str, pn_jid: str, source: str = "") -> None:
        with _connect(self.path) as db:
            self._save_lid_pn_mapping(db, lid_jid, pn_jid, source)

    def get_pn_for_lid(self, lid_jid: str) -> str | None:
        with _connect(self.path) as db:
            row = db.execute("select pn_jid from lid_pn_mappings where lid_jid = ?", (lid_jid,)).fetchone()
        return str(row["pn_jid"]) if row is not None else None

    def get_lid_for_pn(self, pn_jid: str) -> str | None:
        with _connect(self.path) as db:
            row = db.execute("select lid_jid from lid_pn_mappings where pn_jid = ?", (pn_jid,)).fetchone()
        return str(row["lid_jid"]) if row is not None else None

    def save_app_state(self, collection: str, state: dict[str, Any]) -> None:
        with _connect(self.path) as db:
            db.execute(
                """
                insert into app_state(collection, state_json, updated_at)
                values(?, ?, ?)
                on conflict(collection) do update set
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (collection, _json_dumps(state), int(time.time())),
            )

    def load_app_state(self, collection: str) -> dict[str, Any] | None:
        with _connect(self.path) as db:
            row = db.execute("select state_json from app_state where collection = ?", (collection,)).fetchone()
        return json.loads(str(row["state_json"])) if row is not None else None

    def _upsert_message(self, db: sqlite3.Connection, message: WAMessage) -> bool:
        remote_jid = message.key.remote_jid or ""
        message_id = message.key.id or ""
        participant = message.key.participant or ""
        existed = (
            db.execute(
                "select 1 from messages where remote_jid = ? and message_id = ? and participant = ?",
                (remote_jid, message_id, participant),
            ).fetchone()
            is not None
        )
        db.execute(
            """
            insert into messages(
                remote_jid, message_id, participant, from_me, timestamp,
                push_name, broadcast, message_blob, updated_at
            )
            values(?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(remote_jid, message_id, participant) do update set
                from_me = excluded.from_me,
                timestamp = excluded.timestamp,
                push_name = excluded.push_name,
                broadcast = excluded.broadcast,
                message_blob = excluded.message_blob,
                updated_at = excluded.updated_at
            """,
            (
                remote_jid,
                message_id,
                participant,
                1 if message.key.from_me else 0,
                message.message_timestamp,
                message.push_name,
                1 if message.broadcast else 0,
                message.message.SerializeToString() if message.message is not None else None,
                int(time.time()),
            ),
        )
        return not existed

    def _save_chat(self, db: sqlite3.Connection, chat: Chat) -> None:
        db.execute(
            """
            insert into chats(id, conversation_timestamp, unread_count, name, updated_at)
            values(?, ?, ?, ?, ?)
            on conflict(id) do update set
                conversation_timestamp = excluded.conversation_timestamp,
                unread_count = excluded.unread_count,
                name = excluded.name,
                updated_at = excluded.updated_at
            """,
            (chat.id, chat.conversation_timestamp, chat.unread_count, chat.name, int(time.time())),
        )

    def _load_chat(self, db: sqlite3.Connection, jid: str) -> Chat | None:
        row = db.execute("select * from chats where id = ?", (jid,)).fetchone()
        if row is None:
            return None
        return Chat(
            id=str(row["id"]),
            conversation_timestamp=int(row["conversation_timestamp"]) if row["conversation_timestamp"] is not None else None,
            unread_count=int(row["unread_count"] or 0),
            name=row["name"],
        )

    def _save_contact(self, db: sqlite3.Connection, contact: Contact) -> None:
        db.execute(
            """
            insert into contacts(id, name, notify, updated_at)
            values(?, ?, ?, ?)
            on conflict(id) do update set
                name = excluded.name,
                notify = excluded.notify,
                updated_at = excluded.updated_at
            """,
            (contact.id, contact.name, contact.notify, int(time.time())),
        )

    def _load_contact(self, db: sqlite3.Connection, jid: str) -> Contact | None:
        row = db.execute("select * from contacts where id = ?", (jid,)).fetchone()
        if row is None:
            return None
        return Contact(id=str(row["id"]), name=row["name"], notify=row["notify"])

    def _load_message_update(
        self,
        db: sqlite3.Connection,
        remote_jid: str | None,
        message_id: str | None,
        participant: str | None,
    ) -> dict[str, Any]:
        row = db.execute(
            """
            select update_json from message_updates
            where remote_jid = ? and message_id = ? and participant = ?
            """,
            (remote_jid or "", message_id or "", participant or ""),
        ).fetchone()
        return json.loads(str(row["update_json"])) if row is not None else {}

    def _save_reaction(self, db: sqlite3.Connection, reaction: dict[str, Any]) -> None:
        key = reaction.get("key") or {}
        body = reaction.get("reaction") or {}
        db.execute(
            """
            insert or ignore into reactions(
                remote_jid, message_id, participant, from_jid,
                sender_timestamp_ms, text, reaction_json, updated_at
            )
            values(?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key.get("remote_jid") or "",
                key.get("id") or "",
                key.get("participant") or "",
                body.get("from_jid") or "",
                body.get("sender_timestamp_ms"),
                body.get("text") or "",
                _json_dumps(reaction),
                int(time.time()),
            ),
        )

    def _save_lid_pn_mapping(self, db: sqlite3.Connection, lid_jid: str, pn_jid: str, source: str = "") -> None:
        db.execute(
            """
            insert into lid_pn_mappings(lid_jid, pn_jid, source, updated_at)
            values(?, ?, ?, ?)
            on conflict(lid_jid) do update set
                pn_jid = excluded.pn_jid,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (lid_jid, pn_jid, source, int(time.time())),
        )


def use_sqlite_auth_state(path: str | Path) -> AuthState:
    database = Path(path)
    return AuthState.from_store(
        SQLiteCredentialStore(database),
        signal_store=SQLiteSignalKeyStore(database),
        allow_missing=True,
    )


useSqliteAuthState = use_sqlite_auth_state
make_sqlite_event_store = SQLiteEventStore
makeSqliteEventStore = SQLiteEventStore


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("pragma journal_mode = wal")
    db.execute("pragma foreign_keys = on")
    return db


def _init_schema(path: Path) -> None:
    with _connect(path) as db:
        db.executescript(
            """
            create table if not exists credentials (
                name text primary key,
                value text not null
            );

            create table if not exists signal_keys (
                namespace text not null,
                key text not null,
                value text not null,
                primary key(namespace, key)
            );

            create table if not exists recent_outbound (
                message_id text primary key,
                node_json text not null,
                expires_at real not null
            );

            create index if not exists idx_recent_outbound_expires_at
                on recent_outbound(expires_at);

            create table if not exists messages (
                remote_jid text not null,
                message_id text not null,
                participant text not null default '',
                from_me integer not null default 0,
                timestamp integer,
                push_name text,
                broadcast integer not null default 0,
                message_blob blob,
                updated_at integer not null,
                primary key(remote_jid, message_id, participant)
            );

            create index if not exists idx_messages_remote_timestamp
                on messages(remote_jid, timestamp);

            create table if not exists message_updates (
                remote_jid text not null,
                message_id text not null,
                participant text not null default '',
                update_json text not null,
                updated_at integer not null,
                primary key(remote_jid, message_id, participant)
            );

            create table if not exists message_receipts (
                remote_jid text not null,
                message_id text not null,
                participant text not null default '',
                user_jid text not null,
                receipt_json text not null,
                updated_at integer not null,
                primary key(remote_jid, message_id, participant, user_jid)
            );

            create table if not exists reactions (
                remote_jid text not null,
                message_id text not null,
                participant text not null default '',
                from_jid text not null default '',
                sender_timestamp_ms integer,
                text text not null default '',
                reaction_json text not null,
                updated_at integer not null,
                primary key(remote_jid, message_id, participant, from_jid, sender_timestamp_ms, text)
            );

            create table if not exists chats (
                id text primary key,
                conversation_timestamp integer,
                unread_count integer not null default 0,
                name text,
                updated_at integer not null
            );

            create table if not exists contacts (
                id text primary key,
                name text,
                notify text,
                updated_at integer not null
            );

            create table if not exists lid_pn_mappings (
                lid_jid text primary key,
                pn_jid text not null,
                source text not null default '',
                updated_at integer not null
            );

            create index if not exists idx_lid_pn_mappings_pn_jid
                on lid_pn_mappings(pn_jid);

            create table if not exists app_state (
                collection text primary key,
                state_json text not null,
                updated_at integer not null
            );
            """
        )


def _message_from_row(row: sqlite3.Row) -> WAMessage:
    message = None
    blob = row["message_blob"]
    if blob is not None:
        message = proto.Message()
        message.ParseFromString(bytes(blob))
    return WAMessage(
        key=MessageKey(
            remote_jid=str(row["remote_jid"]) or None,
            id=str(row["message_id"]) or None,
            from_me=bool(row["from_me"]),
            participant=str(row["participant"]) or None,
        ),
        message=message,
        message_timestamp=int(row["timestamp"]) if row["timestamp"] is not None else None,
        push_name=row["push_name"],
        broadcast=bool(row["broadcast"]),
    )


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


def _json_dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)
