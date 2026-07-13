from __future__ import annotations

import json
import time
from typing import Any

import baileys as b
from baileys.auth_state import AuthState
from baileys.generated import WAProto_pb2 as proto
from baileys.messages import MessageKey, MessageUpsert, WAMessage
from baileys.postgres_store import (
    POSTGRES_MIGRATIONS,
    POSTGRES_SCHEMA_SQL,
    apply_postgres_migrations,
    PostgresConnectionFactory,
    PostgresCredentialStore,
    PostgresEventStore,
    PostgresReplayStore,
    PostgresSignalKeyStore,
    makePostgresEventStore,
    use_postgres_auth_state,
)
from baileys.wabinary import BinaryNode


class FakeCursor:
    def __init__(self, row: Any = None, rows: list[Any] | None = None, rowcount: int = 0) -> None:
        self._row = row
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchone(self) -> Any:
        return self._row

    def fetchall(self) -> list[Any]:
        return self._rows


class FakePostgresConnection:
    def __init__(self) -> None:
        self.schema_migrations: dict[int, str] = {}
        self.advisory_locks: list[int] = []
        self.transaction_entries = 0
        self.credentials: dict[str, Any] = {}
        self.signal_keys: dict[tuple[str, str], Any] = {}
        self.recent_outbound: dict[str, dict[str, Any]] = {}
        self.messages: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.message_updates: dict[tuple[str, str, str], Any] = {}
        self.message_receipts: dict[tuple[str, str, str, str], Any] = {}
        self.reactions: dict[tuple[Any, ...], Any] = {}
        self.chats: dict[str, dict[str, Any]] = {}
        self.contacts: dict[str, dict[str, Any]] = {}
        self.lid_pn: dict[str, dict[str, Any]] = {}
        self.app_state: dict[str, Any] = {}

    def transaction(self) -> FakeTransaction:
        return FakeTransaction(self)

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> FakeCursor:
        normalized = " ".join(sql.lower().split())
        if normalized.startswith("create table") or normalized.startswith("create index"):
            return FakeCursor()
        if normalized.startswith("select pg_advisory_xact_lock"):
            self.advisory_locks.append(int(params[0]))
            return FakeCursor(row={"pg_advisory_xact_lock": ""})
        if normalized.startswith("select version from baileys_schema_migrations"):
            rows = [{"version": version} for version in sorted(self.schema_migrations)]
            return FakeCursor(rows=rows)
        if normalized.startswith("insert into baileys_schema_migrations"):
            if int(params[0]) in self.schema_migrations:
                return FakeCursor(rowcount=0)
            self.schema_migrations[int(params[0])] = str(params[1])
            return FakeCursor(rowcount=1)

        if normalized.startswith("select value from credentials"):
            return FakeCursor(row={"value": self.credentials.get("default")} if "default" in self.credentials else None)
        if normalized.startswith("insert into credentials"):
            self.credentials["default"] = _json(params[0])
            return FakeCursor(rowcount=1)

        if normalized.startswith("select value from signal_keys"):
            key = (params[0], params[1])
            return FakeCursor(row={"value": self.signal_keys[key]} if key in self.signal_keys else None)
        if normalized.startswith("insert into signal_keys"):
            self.signal_keys[(params[0], params[1])] = _json(params[2])
            return FakeCursor(rowcount=1)
        if normalized.startswith("delete from signal_keys"):
            key = (params[0], params[1])
            existed = key in self.signal_keys
            self.signal_keys.pop(key, None)
            return FakeCursor(rowcount=1 if existed else 0)

        if normalized.startswith("insert into recent_outbound"):
            self.recent_outbound[params[0]] = {"node_json": _json(params[1]), "expires_at": params[2]}
            return FakeCursor(rowcount=1)
        if normalized.startswith("select node_json, expires_at from recent_outbound"):
            item = self.recent_outbound.get(params[0])
            return FakeCursor(row=dict(item) if item else None)
        if normalized.startswith("delete from recent_outbound where message_id"):
            existed = params[0] in self.recent_outbound
            self.recent_outbound.pop(params[0], None)
            return FakeCursor(rowcount=1 if existed else 0)
        if normalized.startswith("delete from recent_outbound where expires_at"):
            expired = [key for key, value in self.recent_outbound.items() if value["expires_at"] <= params[0]]
            for key in expired:
                self.recent_outbound.pop(key, None)
            return FakeCursor(rowcount=len(expired))

        if normalized.startswith("select 1 from messages"):
            key = (params[0], params[1], params[2])
            return FakeCursor(row={"exists": 1} if key in self.messages else None)
        if normalized.startswith("insert into messages"):
            row = {
                "remote_jid": params[0],
                "message_id": params[1],
                "participant": params[2],
                "from_me": params[3],
                "timestamp": params[4],
                "push_name": params[5],
                "broadcast": params[6],
                "message_blob": params[7],
                "updated_at": params[8],
            }
            self.messages[(params[0], params[1], params[2])] = row
            return FakeCursor(rowcount=1)
        if normalized.startswith("select * from messages where remote_jid = %s and message_id"):
            return FakeCursor(row=self.messages.get((params[0], params[1], params[2])))
        if normalized.startswith("select * from messages where remote_jid = %s"):
            rows = [row for key, row in self.messages.items() if key[0] == params[0]]
            rows.sort(key=lambda row: (row["timestamp"] or 0, row["updated_at"]))
            if "limit %s" in normalized:
                rows = rows[-int(params[1]) :]
            return FakeCursor(rows=rows)

        if normalized.startswith("insert into chats"):
            self.chats[params[0]] = {
                "id": params[0],
                "conversation_timestamp": params[1],
                "unread_count": params[2],
                "name": params[3],
                "updated_at": params[4],
            }
            return FakeCursor(rowcount=1)
        if normalized.startswith("select * from chats"):
            return FakeCursor(row=self.chats.get(params[0]))

        if normalized.startswith("insert into contacts"):
            self.contacts[params[0]] = {"id": params[0], "name": params[1], "notify": params[2], "updated_at": params[3]}
            return FakeCursor(rowcount=1)
        if normalized.startswith("select * from contacts"):
            return FakeCursor(row=self.contacts.get(params[0]))

        if normalized.startswith("insert into message_updates"):
            self.message_updates[(params[0], params[1], params[2])] = _json(params[3])
            return FakeCursor(rowcount=1)
        if normalized.startswith("select update_json from message_updates"):
            value = self.message_updates.get((params[0], params[1], params[2]))
            return FakeCursor(row={"update_json": value} if value is not None else None)

        if normalized.startswith("insert into message_receipts"):
            self.message_receipts[(params[0], params[1], params[2], params[3])] = _json(params[4])
            return FakeCursor(rowcount=1)
        if normalized.startswith("select receipt_json from message_receipts"):
            value = self.message_receipts.get((params[0], params[1], params[2], params[3]))
            return FakeCursor(row={"receipt_json": value} if value is not None else None)

        if normalized.startswith("insert into reactions"):
            key = (params[0], params[1], params[2], params[3], params[4], params[5])
            self.reactions.setdefault(key, _json(params[6]))
            return FakeCursor(rowcount=1)

        if normalized.startswith("insert into lid_pn_mappings"):
            self.lid_pn[params[0]] = {"lid_jid": params[0], "pn_jid": params[1], "source": params[2], "updated_at": params[3]}
            return FakeCursor(rowcount=1)
        if normalized.startswith("select pn_jid from lid_pn_mappings"):
            return FakeCursor(row=self.lid_pn.get(params[0]))
        if normalized.startswith("select lid_jid from lid_pn_mappings"):
            row = next((item for item in self.lid_pn.values() if item["pn_jid"] == params[0]), None)
            return FakeCursor(row=row)

        if normalized.startswith("insert into app_state"):
            self.app_state[params[0]] = _json(params[1])
            return FakeCursor(rowcount=1)
        if normalized.startswith("select state_json from app_state"):
            value = self.app_state.get(params[0])
            return FakeCursor(row={"state_json": value} if value is not None else None)

        return FakeCursor()


class FakeTransaction:
    def __init__(self, connection: FakePostgresConnection) -> None:
        self.connection = connection

    def __enter__(self) -> FakeTransaction:
        self.connection.transaction_entries += 1
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False


def _json(value: Any) -> Any:
    if isinstance(value, str):
        return json.loads(value)
    return value


def _text_message(text: str) -> proto.Message:
    message = proto.Message()
    message.conversation = text
    return message


def test_postgres_schema_and_connection_boundary_are_optional():
    assert "create table if not exists credentials" in POSTGRES_SCHEMA_SQL
    assert "create table if not exists app_state" in POSTGRES_SCHEMA_SQL
    assert "create table if not exists recent_outbound" in POSTGRES_SCHEMA_SQL
    assert POSTGRES_MIGRATIONS[0].version == 1
    assert POSTGRES_MIGRATIONS[0].sql == POSTGRES_SCHEMA_SQL

    try:
        with PostgresConnectionFactory().connection_context():
            raise AssertionError("connection should not open without configuration")
    except RuntimeError as exc:
        assert "conninfo, pool, or connection" in str(exc)


def test_postgres_migrations_are_versioned_idempotent_and_locked():
    db = FakePostgresConnection()

    first = apply_postgres_migrations(connection=db)
    second = apply_postgres_migrations(connection=db)

    assert first == [1]
    assert second == []
    assert db.schema_migrations == {1: "initial_store_schema"}
    assert len(db.advisory_locks) == 2
    assert db.transaction_entries == 2


def test_postgres_auth_signal_and_replay_store_contract():
    db = FakePostgresConnection()
    credentials = {"me": {"id": "me@s.whatsapp.net"}, "next_pre_key_id": 1}
    node = BinaryNode("message", {"id": "m1"}, [BinaryNode("enc", {"type": "msg"}, b"cipher")])

    PostgresCredentialStore(connection=db).save_credentials(credentials)
    signal = PostgresSignalKeyStore(connection=db, init_schema=False)
    signal.set("session", "peer@s.whatsapp.net", {"record": "abc"})
    replay = PostgresReplayStore(connection=db, init_schema=False)
    replay.save_recent_outbound("m1", node, time.time() + 60)
    replay.save_recent_outbound("expired", node, time.time() - 1)

    auth_state = use_postgres_auth_state(connection=db, init_schema=False)

    assert isinstance(auth_state, AuthState)
    assert auth_state.credentials == credentials
    assert signal.get("session", "peer@s.whatsapp.net") == {"record": "abc"}
    assert signal.delete("session", "peer@s.whatsapp.net") is True
    assert signal.delete("session", "peer@s.whatsapp.net") is False
    assert replay.load_recent_outbound("m1") == node
    assert replay.load_recent_outbound("expired") is None
    assert replay.prune_expired(time.time() + 120) == 1
    assert replay.load_recent_outbound("m1") is None


def test_postgres_event_store_matches_core_sqlite_semantics():
    db = FakePostgresConnection()
    store = PostgresEventStore(connection=db)
    message = WAMessage(
        key=MessageKey("user@s.whatsapp.net", "m1"),
        message=_text_message("hello"),
        message_timestamp=123,
        push_name="Alice",
    )

    first = store.apply_messages_upsert(MessageUpsert([message], type="notify"))
    second = store.apply_messages_upsert(MessageUpsert([message], type="notify"))
    store.apply_messages_update(
        [
            {
                "key": {"remote_jid": "user@s.whatsapp.net", "id": "m1", "from_me": False},
                "update": {"status": proto.WebMessageInfo.Status.READ},
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
    store.save_lid_pn_mapping("999:1@lid", "999@s.whatsapp.net", source="test")
    store.save_app_state("regular_low", {"version": {"hash": "abc"}})

    assert makePostgresEventStore is PostgresEventStore
    assert b.makePostgresEventStore is PostgresEventStore
    assert first.chats[0].id == "user@s.whatsapp.net"
    assert second.chats[0].id == "user@s.whatsapp.net"
    assert store.load_messages("user@s.whatsapp.net")[0].message.conversation == "hello"
    assert store.load_chat("user@s.whatsapp.net").unread_count == 0
    assert store.load_contact("user@s.whatsapp.net").notify == "Alice"
    assert store.load_message_update("user@s.whatsapp.net", "m1")["status"] == proto.WebMessageInfo.Status.READ
    assert store.load_message_receipt("group@g.us", "g1", "sender@s.whatsapp.net", "reader@s.whatsapp.net") == {
        "read_timestamp": 789
    }
    assert store.get_pn_for_lid("999:1@lid") == "999@s.whatsapp.net"
    assert store.get_lid_for_pn("999@s.whatsapp.net") == "999@lid"
    assert store.load_app_state("regular_low") == {"version": {"hash": "abc"}}
