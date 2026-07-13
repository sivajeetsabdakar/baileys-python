from __future__ import annotations

import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import pytest

from baileys.generated import WAProto_pb2 as proto
from baileys.messages import MessageKey, MessageUpsert, WAMessage
from baileys.postgres_store import (
    PostgresCredentialStore,
    PostgresEventStore,
    PostgresReplayStore,
    PostgresSignalKeyStore,
    apply_postgres_migrations,
    use_postgres_auth_state,
)
from baileys.wabinary import BinaryNode


pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class PostgresSchema:
    conninfo: str = field(repr=False)
    schema: str


def _text_message(text: str) -> proto.Message:
    message = proto.Message()
    message.conversation = text
    return message


@pytest.fixture()
def postgres_schema():
    conninfo = os.getenv("BAILEYS_POSTGRES_TEST_DSN")
    if not conninfo:
        pytest.skip("set BAILEYS_POSTGRES_TEST_DSN to run Postgres integration tests")
    psycopg = pytest.importorskip("psycopg")
    from psycopg import sql

    schema = f"baileys_test_{uuid.uuid4().hex}"
    with psycopg.connect(conninfo, autocommit=True) as connection:
        connection.execute(sql.SQL("create schema {}").format(sql.Identifier(schema)))
    try:
        yield PostgresSchema(conninfo, schema)
    finally:
        with psycopg.connect(conninfo, autocommit=True) as connection:
            connection.execute(sql.SQL("drop schema if exists {} cascade").format(sql.Identifier(schema)))


def _connect_to_schema(conninfo: str, schema: str):
    import psycopg
    from psycopg import sql
    from psycopg.rows import dict_row

    connection = psycopg.connect(conninfo, autocommit=True, row_factory=dict_row)
    connection.execute(sql.SQL("set search_path to {}").format(sql.Identifier(schema)))
    return connection


@pytest.fixture()
def postgres_connection(postgres_schema):
    connection = _connect_to_schema(postgres_schema.conninfo, postgres_schema.schema)
    apply_postgres_migrations(connection=connection, schema=postgres_schema.schema)
    try:
        yield connection
    finally:
        connection.close()


def test_postgres_migrations_are_safe_for_concurrent_writers(postgres_schema):
    first = _connect_to_schema(postgres_schema.conninfo, postgres_schema.schema)
    second = _connect_to_schema(postgres_schema.conninfo, postgres_schema.schema)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda connection: apply_postgres_migrations(connection=connection, schema=postgres_schema.schema),
                    [first, second],
                )
            )
    finally:
        first.close()
        second.close()

    assert sorted(version for result in results for version in result) == [1]
    assert sorted(results, key=len) == [[], [1]]


def test_postgres_stores_round_trip_against_real_database(postgres_connection):
    credentials = {"me": {"id": "me@s.whatsapp.net"}, "next_pre_key_id": 10}
    node = BinaryNode("message", {"id": "m1"}, [BinaryNode("enc", {"type": "msg"}, b"cipher")])

    PostgresCredentialStore(connection=postgres_connection, init_schema=False).save_credentials(credentials)
    auth_state = use_postgres_auth_state(connection=postgres_connection, init_schema=False)
    signal = PostgresSignalKeyStore(connection=postgres_connection, init_schema=False)
    replay = PostgresReplayStore(connection=postgres_connection, init_schema=False)

    signal.set("session", "peer@s.whatsapp.net", {"record": "abc"})
    replay.save_recent_outbound("m1", node, time.time() + 60)
    replay.save_recent_outbound("expired", node, time.time() - 1)

    assert auth_state.credentials == credentials
    assert signal.get("session", "peer@s.whatsapp.net") == {"record": "abc"}
    assert signal.delete("session", "peer@s.whatsapp.net") is True
    assert signal.get("session", "peer@s.whatsapp.net") is None
    assert replay.load_recent_outbound("m1") == node
    assert replay.load_recent_outbound("expired") is None
    assert replay.prune_expired(time.time() + 120) == 1

    event_store = PostgresEventStore(connection=postgres_connection, init_schema=False)
    message = WAMessage(
        key=MessageKey("user@s.whatsapp.net", "m1"),
        message=_text_message("hello from postgres"),
        message_timestamp=123,
        push_name="Alice",
    )
    first = event_store.apply_messages_upsert(MessageUpsert([message], type="notify"))
    second = event_store.apply_messages_upsert(MessageUpsert([message], type="notify"))
    event_store.apply_messages_update(
        [
            {
                "key": {"remote_jid": "user@s.whatsapp.net", "id": "m1", "from_me": False},
                "update": {"status": proto.WebMessageInfo.Status.READ},
            }
        ]
    )
    event_store.apply_message_receipt_update(
        [
            {
                "key": {"remote_jid": "group@g.us", "id": "g1", "participant": "sender@s.whatsapp.net"},
                "receipt": {"user_jid": "reader@s.whatsapp.net", "read_timestamp": 789},
            }
        ]
    )
    event_store.save_lid_pn_mapping("999:1@lid", "999@s.whatsapp.net", source="integration")
    event_store.save_app_state("regular_low", {"version": {"hash": "abc"}})

    reopened = PostgresEventStore(connection=postgres_connection, init_schema=False)
    assert first.chats[0].id == "user@s.whatsapp.net"
    assert second.chats[0].id == "user@s.whatsapp.net"
    assert reopened.load_messages("user@s.whatsapp.net")[0].message.conversation == "hello from postgres"
    assert reopened.load_chat("user@s.whatsapp.net").unread_count == 0
    assert reopened.load_contact("user@s.whatsapp.net").notify == "Alice"
    assert reopened.load_message_update("user@s.whatsapp.net", "m1")["status"] == proto.WebMessageInfo.Status.READ
    assert reopened.load_message_receipt("group@g.us", "g1", "sender@s.whatsapp.net", "reader@s.whatsapp.net") == {
        "read_timestamp": 789
    }
    assert reopened.get_pn_for_lid("999:1@lid") == "999@s.whatsapp.net"
    assert reopened.get_lid_for_pn("999@s.whatsapp.net") == "999@lid"
    assert reopened.load_app_state("regular_low") == {"version": {"hash": "abc"}}
