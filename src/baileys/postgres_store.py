from __future__ import annotations

import json
import time
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any, Iterator

from .auth_state import AuthState
from .events import EventEmitter
from .generated import WAProto_pb2 as proto
from .history import HistorySyncResult
from .jid import jid_normalized_user
from .messages import MessageKey, MessageUpsert, WAMessage
from .replay import binary_node_from_json, binary_node_to_json
from .store import Chat, Contact, StoreUpdate
from .wabinary import BinaryNode


POSTGRES_SCHEMA_SQL = """
create table if not exists credentials (
    name text primary key,
    value jsonb not null
);

create table if not exists signal_keys (
    namespace text not null,
    key text not null,
    value jsonb not null,
    primary key(namespace, key)
);

create table if not exists recent_outbound (
    message_id text primary key,
    node_json jsonb not null,
    expires_at double precision not null
);
create index if not exists idx_recent_outbound_expires_at
    on recent_outbound(expires_at);

create table if not exists messages (
    remote_jid text not null,
    message_id text not null,
    participant text not null default '',
    from_me boolean not null default false,
    timestamp bigint,
    push_name text,
    broadcast boolean not null default false,
    message_blob bytea,
    updated_at bigint not null,
    primary key(remote_jid, message_id, participant)
);
create index if not exists idx_messages_remote_timestamp
    on messages(remote_jid, timestamp);

create table if not exists message_updates (
    remote_jid text not null,
    message_id text not null,
    participant text not null default '',
    update_json jsonb not null,
    updated_at bigint not null,
    primary key(remote_jid, message_id, participant)
);

create table if not exists message_receipts (
    remote_jid text not null,
    message_id text not null,
    participant text not null default '',
    user_jid text not null,
    receipt_json jsonb not null,
    updated_at bigint not null,
    primary key(remote_jid, message_id, participant, user_jid)
);

create table if not exists reactions (
    remote_jid text not null,
    message_id text not null,
    participant text not null default '',
    from_jid text not null default '',
    sender_timestamp_ms bigint,
    text text not null default '',
    reaction_json jsonb not null,
    updated_at bigint not null,
    primary key(remote_jid, message_id, participant, from_jid, sender_timestamp_ms, text)
);

create table if not exists chats (
    id text primary key,
    conversation_timestamp bigint,
    unread_count integer not null default 0,
    name text,
    updated_at bigint not null
);

create table if not exists contacts (
    id text primary key,
    name text,
    notify text,
    updated_at bigint not null
);

create table if not exists lid_pn_mappings (
    lid_jid text primary key,
    pn_jid text not null,
    source text not null default '',
    updated_at bigint not null
);
create index if not exists idx_lid_pn_mappings_pn_jid
    on lid_pn_mappings(pn_jid);

create table if not exists app_state (
    collection text primary key,
    state_json jsonb not null,
    updated_at bigint not null
);
"""


POSTGRES_SCHEMA_LOCK_ID = 749_319_120


@dataclass(frozen=True)
class PostgresMigration:
    version: int
    name: str
    sql: str


POSTGRES_MIGRATIONS = (
    PostgresMigration(1, "initial_store_schema", POSTGRES_SCHEMA_SQL),
)


@dataclass(frozen=True)
class PostgresConnectionFactory:
    conninfo: str | None = None
    pool: Any | None = None
    connection: Any | None = None

    @contextmanager
    def connection_context(self) -> Iterator[Any]:
        if self.pool is not None:
            with self.pool.connection() as connection:
                yield connection
            return
        if self.connection is not None:
            yield self.connection
            return
        if self.conninfo is None:
            raise RuntimeError("Postgres store requires conninfo, pool, or connection")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError("Install baileys-python[postgres] to use Postgres stores") from exc
        with psycopg.connect(self.conninfo, row_factory=dict_row) as connection:
            yield connection


class _PostgresStoreBase:
    def __init__(
        self,
        conninfo: str | None = None,
        *,
        pool: Any | None = None,
        connection: Any | None = None,
        init_schema: bool = True,
    ) -> None:
        self.factory = PostgresConnectionFactory(conninfo=conninfo, pool=pool, connection=connection)
        if init_schema:
            self.init_schema()

    def init_schema(self) -> None:
        with self.factory.connection_context() as db:
            _apply_postgres_migrations(db)


class PostgresCredentialStore(_PostgresStoreBase):
    def load_credentials(self) -> dict[str, Any]:
        with self.factory.connection_context() as db:
            row = _execute(db, "select value from credentials where name = %s", ("default",)).fetchone()
        return _json_value(row, "value") if row is not None else {}

    def save_credentials(self, credentials: dict[str, Any]) -> None:
        with self.factory.connection_context() as db:
            _execute(
                db,
                """
                insert into credentials(name, value)
                values('default', %s::jsonb)
                on conflict(name) do update set value = excluded.value
                """,
                (_json_dumps(credentials),),
            )


class PostgresSignalKeyStore(_PostgresStoreBase):
    def get(self, namespace: str, key: str) -> Any:
        with self.factory.connection_context() as db:
            row = _execute(
                db,
                "select value from signal_keys where namespace = %s and key = %s",
                (namespace, key),
            ).fetchone()
        return _json_value(row, "value") if row is not None else None

    def set(self, namespace: str, key: str, value: Any) -> None:
        with self.factory.connection_context() as db:
            _execute(
                db,
                """
                insert into signal_keys(namespace, key, value)
                values(%s, %s, %s::jsonb)
                on conflict(namespace, key) do update set value = excluded.value
                """,
                (namespace, key, _json_dumps(value)),
            )

    def delete(self, namespace: str, key: str) -> bool:
        with self.factory.connection_context() as db:
            cursor = _execute(
                db,
                "delete from signal_keys where namespace = %s and key = %s",
                (namespace, key),
            )
            return int(getattr(cursor, "rowcount", 0) or 0) > 0


class PostgresReplayStore(_PostgresStoreBase):
    def save_recent_outbound(self, message_id: str, node: BinaryNode, expires_at: float) -> None:
        if not message_id:
            return
        with self.factory.connection_context() as db:
            _execute(
                db,
                """
                insert into recent_outbound(message_id, node_json, expires_at)
                values(%s, %s::jsonb, %s)
                on conflict(message_id) do update set
                    node_json = excluded.node_json,
                    expires_at = excluded.expires_at
                """,
                (message_id, _json_dumps(binary_node_to_json(node)), float(expires_at)),
            )

    def load_recent_outbound(self, message_id: str) -> BinaryNode | None:
        with self.factory.connection_context() as db:
            row = _execute(
                db,
                "select node_json, expires_at from recent_outbound where message_id = %s",
                (message_id,),
            ).fetchone()
            if row is None:
                return None
            if float(_row_get(row, "expires_at")) <= time.time():
                _execute(db, "delete from recent_outbound where message_id = %s", (message_id,))
                return None
        return binary_node_from_json(_json_value(row, "node_json"))

    def delete_recent_outbound(self, message_id: str) -> None:
        with self.factory.connection_context() as db:
            _execute(db, "delete from recent_outbound where message_id = %s", (message_id,))

    def prune_expired(self, now: float | None = None) -> int:
        cutoff = time.time() if now is None else now
        with self.factory.connection_context() as db:
            cursor = _execute(db, "delete from recent_outbound where expires_at <= %s", (float(cutoff),))
            return int(getattr(cursor, "rowcount", 0) or 0)


class PostgresEventStore(_PostgresStoreBase):
    def __init__(
        self,
        conninfo: str | None = None,
        *,
        pool: Any | None = None,
        connection: Any | None = None,
        init_schema: bool = True,
    ) -> None:
        self._listener_refs = []
        super().__init__(conninfo, pool=pool, connection=connection, init_schema=init_schema)

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
        with self.factory.connection_context() as db:
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
        with self.factory.connection_context() as db:
            for item in updates:
                key = item.get("key") or {}
                update = item.get("update") or {}
                remote_jid, message_id, participant = _message_key_tuple(key)
                existing = self._load_message_update(db, remote_jid, message_id, participant)
                existing.update(update)
                _execute(
                    db,
                    """
                    insert into message_updates(remote_jid, message_id, participant, update_json, updated_at)
                    values(%s, %s, %s, %s::jsonb, %s)
                    on conflict(remote_jid, message_id, participant) do update set
                        update_json = excluded.update_json,
                        updated_at = excluded.updated_at
                    """,
                    (remote_jid or "", message_id or "", participant or "", _json_dumps(existing), int(time.time())),
                )
                if remote_jid and update.get("status") is not None:
                    chat = self._load_chat(db, remote_jid)
                    if chat is not None and not key.get("from_me") and update.get("status") >= 3:
                        chat.unread_count = 0
                        self._save_chat(db, chat)
                        changed_chats[remote_jid] = chat
        return StoreUpdate(chats=list(changed_chats.values()))

    def apply_message_receipt_update(self, updates: list[dict[str, Any]]) -> StoreUpdate:
        with self.factory.connection_context() as db:
            for item in updates:
                key = item.get("key") or {}
                receipt = dict(item.get("receipt") or {})
                user_jid = receipt.pop("user_jid", None)
                if not user_jid:
                    continue
                remote_jid, message_id, participant = _message_key_tuple(key)
                existing = self._load_message_receipt(db, remote_jid, message_id, participant, user_jid)
                existing.update(receipt)
                _execute(
                    db,
                    """
                    insert into message_receipts(remote_jid, message_id, participant, user_jid, receipt_json, updated_at)
                    values(%s, %s, %s, %s, %s::jsonb, %s)
                    on conflict(remote_jid, message_id, participant, user_jid) do update set
                        receipt_json = excluded.receipt_json,
                        updated_at = excluded.updated_at
                    """,
                    (remote_jid or "", message_id or "", participant or "", user_jid, _json_dumps(existing), int(time.time())),
                )
        return StoreUpdate()

    def apply_history_sync(self, history: HistorySyncResult) -> StoreUpdate:
        changed_chats: dict[str, Chat] = {}
        changed_contacts: dict[str, Contact] = {}
        with self.factory.connection_context() as db:
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
                self._upsert_message(
                    db,
                    WAMessage(
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
                    ),
                )
        return StoreUpdate(chats=list(changed_chats.values()), contacts=list(changed_contacts.values()))

    def load_messages(self, jid: str, count: int | None = None) -> list[WAMessage]:
        with self.factory.connection_context() as db:
            if count is None:
                rows = _execute(
                    db,
                    """
                    select * from messages
                    where remote_jid = %s
                    order by coalesce(timestamp, 0), updated_at
                    """,
                    (jid,),
                ).fetchall()
            else:
                rows = _execute(
                    db,
                    """
                    select * from messages
                    where remote_jid = %s
                    order by coalesce(timestamp, 0) desc, updated_at desc
                    limit %s
                    """,
                    (jid, int(count)),
                ).fetchall()
                rows = list(reversed(rows))
        return [_message_from_row(row) for row in rows]

    def load_message(self, jid: str, message_id: str, participant: str | None = None) -> WAMessage | None:
        with self.factory.connection_context() as db:
            row = _execute(
                db,
                "select * from messages where remote_jid = %s and message_id = %s and participant = %s",
                (jid, message_id, participant or ""),
            ).fetchone()
        return _message_from_row(row) if row is not None else None

    def load_chat(self, jid: str) -> Chat | None:
        with self.factory.connection_context() as db:
            return self._load_chat(db, jid)

    def load_contact(self, jid: str) -> Contact | None:
        with self.factory.connection_context() as db:
            return self._load_contact(db, jid)

    def load_message_update(self, remote_jid: str | None, message_id: str | None, participant: str | None = None) -> dict[str, Any]:
        with self.factory.connection_context() as db:
            return self._load_message_update(db, remote_jid, message_id, participant)

    def load_message_receipt(
        self,
        remote_jid: str | None,
        message_id: str | None,
        participant: str | None,
        user_jid: str,
    ) -> dict[str, Any]:
        with self.factory.connection_context() as db:
            return self._load_message_receipt(db, remote_jid, message_id, participant, user_jid)

    def save_lid_pn_mapping(self, lid_jid: str, pn_jid: str, source: str = "") -> None:
        with self.factory.connection_context() as db:
            self._save_lid_pn_mapping(db, lid_jid, pn_jid, source)

    def get_pn_for_lid(self, lid_jid: str) -> str | None:
        with self.factory.connection_context() as db:
            row = _execute(
                db,
                "select pn_jid from lid_pn_mappings where lid_jid = %s",
                (jid_normalized_user(lid_jid),),
            ).fetchone()
        return str(_row_get(row, "pn_jid")) if row is not None else None

    def get_lid_for_pn(self, pn_jid: str) -> str | None:
        with self.factory.connection_context() as db:
            row = _execute(
                db,
                "select lid_jid from lid_pn_mappings where pn_jid = %s",
                (jid_normalized_user(pn_jid),),
            ).fetchone()
        return str(_row_get(row, "lid_jid")) if row is not None else None

    def save_app_state(self, collection: str, state: dict[str, Any]) -> None:
        with self.factory.connection_context() as db:
            _execute(
                db,
                """
                insert into app_state(collection, state_json, updated_at)
                values(%s, %s::jsonb, %s)
                on conflict(collection) do update set
                    state_json = excluded.state_json,
                    updated_at = excluded.updated_at
                """,
                (collection, _json_dumps(state), int(time.time())),
            )

    def load_app_state(self, collection: str) -> dict[str, Any] | None:
        with self.factory.connection_context() as db:
            row = _execute(db, "select state_json from app_state where collection = %s", (collection,)).fetchone()
        return _json_value(row, "state_json") if row is not None else None

    def _upsert_message(self, db: Any, message: WAMessage) -> bool:
        remote_jid = message.key.remote_jid or ""
        message_id = message.key.id or ""
        participant = message.key.participant or ""
        existed = _execute(
            db,
            "select 1 from messages where remote_jid = %s and message_id = %s and participant = %s",
            (remote_jid, message_id, participant),
        ).fetchone() is not None
        _execute(
            db,
            """
            insert into messages(
                remote_jid, message_id, participant, from_me, timestamp,
                push_name, broadcast, message_blob, updated_at
            )
            values(%s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                bool(message.key.from_me),
                message.message_timestamp,
                message.push_name,
                bool(message.broadcast),
                message.message.SerializeToString() if message.message is not None else None,
                int(time.time()),
            ),
        )
        return not existed

    def _save_chat(self, db: Any, chat: Chat) -> None:
        _execute(
            db,
            """
            insert into chats(id, conversation_timestamp, unread_count, name, updated_at)
            values(%s, %s, %s, %s, %s)
            on conflict(id) do update set
                conversation_timestamp = excluded.conversation_timestamp,
                unread_count = excluded.unread_count,
                name = excluded.name,
                updated_at = excluded.updated_at
            """,
            (chat.id, chat.conversation_timestamp, chat.unread_count, chat.name, int(time.time())),
        )

    def _load_chat(self, db: Any, jid: str) -> Chat | None:
        row = _execute(db, "select * from chats where id = %s", (jid,)).fetchone()
        if row is None:
            return None
        return Chat(
            id=str(_row_get(row, "id")),
            conversation_timestamp=int(_row_get(row, "conversation_timestamp")) if _row_get(row, "conversation_timestamp") is not None else None,
            unread_count=int(_row_get(row, "unread_count") or 0),
            name=_row_get(row, "name"),
        )

    def _save_contact(self, db: Any, contact: Contact) -> None:
        _execute(
            db,
            """
            insert into contacts(id, name, notify, updated_at)
            values(%s, %s, %s, %s)
            on conflict(id) do update set
                name = excluded.name,
                notify = excluded.notify,
                updated_at = excluded.updated_at
            """,
            (contact.id, contact.name, contact.notify, int(time.time())),
        )

    def _load_contact(self, db: Any, jid: str) -> Contact | None:
        row = _execute(db, "select * from contacts where id = %s", (jid,)).fetchone()
        if row is None:
            return None
        return Contact(id=str(_row_get(row, "id")), name=_row_get(row, "name"), notify=_row_get(row, "notify"))

    def _load_message_update(self, db: Any, remote_jid: str | None, message_id: str | None, participant: str | None) -> dict[str, Any]:
        row = _execute(
            db,
            "select update_json from message_updates where remote_jid = %s and message_id = %s and participant = %s",
            (remote_jid or "", message_id or "", participant or ""),
        ).fetchone()
        return _json_value(row, "update_json") if row is not None else {}

    def _load_message_receipt(self, db: Any, remote_jid: str | None, message_id: str | None, participant: str | None, user_jid: str) -> dict[str, Any]:
        row = _execute(
            db,
            """
            select receipt_json from message_receipts
            where remote_jid = %s and message_id = %s and participant = %s and user_jid = %s
            """,
            (remote_jid or "", message_id or "", participant or "", user_jid),
        ).fetchone()
        return _json_value(row, "receipt_json") if row is not None else {}

    def _save_reaction(self, db: Any, reaction: dict[str, Any]) -> None:
        key = reaction.get("key") or {}
        body = reaction.get("reaction") or {}
        _execute(
            db,
            """
            insert into reactions(
                remote_jid, message_id, participant, from_jid,
                sender_timestamp_ms, text, reaction_json, updated_at
            )
            values(%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            on conflict(remote_jid, message_id, participant, from_jid, sender_timestamp_ms, text)
            do nothing
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

    def _save_lid_pn_mapping(self, db: Any, lid_jid: str, pn_jid: str, source: str = "") -> None:
        _execute(
            db,
            """
            insert into lid_pn_mappings(lid_jid, pn_jid, source, updated_at)
            values(%s, %s, %s, %s)
            on conflict(lid_jid) do update set
                pn_jid = excluded.pn_jid,
                source = excluded.source,
                updated_at = excluded.updated_at
            """,
            (jid_normalized_user(lid_jid), jid_normalized_user(pn_jid), source, int(time.time())),
        )


def use_postgres_auth_state(
    conninfo: str | None = None,
    *,
    pool: Any | None = None,
    connection: Any | None = None,
    init_schema: bool = True,
) -> AuthState:
    return AuthState.from_store(
        PostgresCredentialStore(conninfo, pool=pool, connection=connection, init_schema=init_schema),
        signal_store=PostgresSignalKeyStore(conninfo, pool=pool, connection=connection, init_schema=False),
        allow_missing=True,
    )


usePostgresAuthState = use_postgres_auth_state
make_postgres_event_store = PostgresEventStore
makePostgresEventStore = PostgresEventStore


def apply_postgres_migrations(
    conninfo: str | None = None,
    *,
    pool: Any | None = None,
    connection: Any | None = None,
    schema: str | None = None,
) -> list[int]:
    factory = PostgresConnectionFactory(conninfo=conninfo, pool=pool, connection=connection)
    with factory.connection_context() as db:
        return _apply_postgres_migrations(db, schema=schema)


applyPostgresMigrations = apply_postgres_migrations


def _apply_postgres_migrations(db: Any, *, schema: str | None = None) -> list[int]:
    with _transaction(db):
        if schema:
            _set_local_search_path(db, schema)
        _execute(db, "select pg_advisory_xact_lock(%s)", (POSTGRES_SCHEMA_LOCK_ID,))
        _execute(
            db,
            """
            create table if not exists baileys_schema_migrations (
                version integer primary key,
                name text not null,
                applied_at timestamptz not null default now()
            )
            """,
        )
        rows = _execute(db, "select version from baileys_schema_migrations").fetchall()
        applied = {int(_row_get(row, "version")) for row in rows}
        newly_applied: list[int] = []
        for migration in POSTGRES_MIGRATIONS:
            if migration.version in applied:
                continue
            _execute(db, migration.sql)
            cursor = _execute(
                db,
                """
                insert into baileys_schema_migrations(version, name)
                values(%s, %s)
                on conflict(version) do nothing
                """,
                (migration.version, migration.name),
            )
            if int(getattr(cursor, "rowcount", 0) or 0) > 0:
                newly_applied.append(migration.version)
    return newly_applied


def _set_local_search_path(db: Any, schema: str) -> None:
    try:
        from psycopg import sql
    except ImportError:
        escaped = schema.replace('"', '""')
        _execute(db, f'set local search_path to "{escaped}"')
        return
    _execute(db, sql.SQL("set local search_path to {}").format(sql.Identifier(schema)))


@contextmanager
def _transaction(db: Any) -> Iterator[None]:
    transaction = getattr(db, "transaction", None)
    with (transaction() if callable(transaction) else nullcontext()):
        yield


def _execute(db: Any, sql: Any, params: tuple[Any, ...] = ()) -> Any:
    execute = getattr(db, "execute", None)
    if callable(execute):
        return execute(sql, params)
    with db.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor


def _row_get(row: Any, key: str, index: int = 0) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    try:
        return row[key]
    except (KeyError, TypeError):
        return row[index]


def _json_value(row: Any, key: str) -> Any:
    value = _row_get(row, key)
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    return json.loads(str(value))


def _message_from_row(row: Any) -> WAMessage:
    message = None
    blob = _row_get(row, "message_blob")
    if blob is not None:
        message = proto.Message()
        message.ParseFromString(bytes(blob))
    return WAMessage(
        key=MessageKey(
            remote_jid=str(_row_get(row, "remote_jid")) or None,
            id=str(_row_get(row, "message_id")) or None,
            from_me=bool(_row_get(row, "from_me")),
            participant=str(_row_get(row, "participant")) or None,
        ),
        message=message,
        message_timestamp=int(_row_get(row, "timestamp")) if _row_get(row, "timestamp") is not None else None,
        push_name=_row_get(row, "push_name"),
        broadcast=bool(_row_get(row, "broadcast")),
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
