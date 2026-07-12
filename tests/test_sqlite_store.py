from __future__ import annotations

import asyncio
import time

import baileys as b
from baileys.receipts import RetryRequest
from baileys.socket import make_socket
from baileys.sqlite_store import SQLiteCredentialStore, SQLiteReplayStore, SQLiteSignalKeyStore, use_sqlite_auth_state
from baileys.wabinary import BinaryNode


class FakeWeb:
    def __init__(self) -> None:
        self.sent = []

    async def send_node(self, node: BinaryNode) -> None:
        self.sent.append(node)


def test_sqlite_credential_and_signal_stores_persist_across_instances(tmp_path):
    db_path = tmp_path / "auth.db"
    credentials = {"me": {"id": "me@s.whatsapp.net"}, "registration_id": 123}

    SQLiteCredentialStore(db_path).save_credentials(credentials)
    signal = SQLiteSignalKeyStore(db_path)
    signal.set("session", "peer@s.whatsapp.net", {"record": "abc"})

    assert SQLiteCredentialStore(db_path).load_credentials() == credentials
    assert SQLiteSignalKeyStore(db_path).get("session", "peer@s.whatsapp.net") == {"record": "abc"}
    assert SQLiteSignalKeyStore(db_path).delete("session", "peer@s.whatsapp.net") is True
    assert SQLiteSignalKeyStore(db_path).get("session", "peer@s.whatsapp.net") is None
    assert SQLiteSignalKeyStore(db_path).delete("session", "peer@s.whatsapp.net") is False


def test_use_sqlite_auth_state_returns_normal_auth_state(tmp_path):
    db_path = tmp_path / "auth.db"
    state = use_sqlite_auth_state(db_path)

    assert state.credentials == {}
    assert isinstance(state.credential_store, SQLiteCredentialStore)
    assert isinstance(state.signal_store, SQLiteSignalKeyStore)

    state.credentials = {"me": {"id": "me@s.whatsapp.net"}}
    state.save_credentials()

    assert use_sqlite_auth_state(db_path).credentials == {"me": {"id": "me@s.whatsapp.net"}}
    assert b.useSqliteAuthState(db_path).credentials == {"me": {"id": "me@s.whatsapp.net"}}


def test_sqlite_replay_store_persists_and_prunes_entries(tmp_path):
    db_path = tmp_path / "auth.db"
    node = BinaryNode("message", {"id": "m1"}, [BinaryNode("enc", {"type": "msg"}, b"ciphertext")])
    replay = SQLiteReplayStore(db_path)

    replay.save_recent_outbound("m1", node, time.time() + 60)

    assert SQLiteReplayStore(db_path).load_recent_outbound("m1") == node
    SQLiteReplayStore(db_path).save_recent_outbound("expired", node, time.time() - 1)
    assert SQLiteReplayStore(db_path).load_recent_outbound("expired") is None
    assert SQLiteReplayStore(db_path).prune_expired(time.time() + 120) == 1
    assert SQLiteReplayStore(db_path).load_recent_outbound("m1") is None


def test_socket_can_replay_recent_outbound_from_sqlite_store(tmp_path):
    async def scenario():
        db_path = tmp_path / "auth.db"
        auth = use_sqlite_auth_state(db_path)
        auth.credentials = {"me": {"id": "me@s.whatsapp.net", "name": "Me"}}
        auth.save_credentials()
        node = BinaryNode("message", {"id": "m1", "to": "chat@s.whatsapp.net", "type": "text"})

        first = make_socket(use_sqlite_auth_state(db_path), replay_store=SQLiteReplayStore(db_path))
        first._web = FakeWeb()
        await first.relay_message("chat@s.whatsapp.net", node)

        second = make_socket(use_sqlite_auth_state(db_path), replay_store=SQLiteReplayStore(db_path))
        second._web = FakeWeb()
        resent = await second.resend_message_for_retry(
            RetryRequest(
                key=b.MessageKey("chat@s.whatsapp.net", "m1", from_me=True),
                ids=["m1"],
                retry_count=1,
                error_code=None,
                node=BinaryNode("receipt", {"type": "retry"}),
            )
        )

        assert resent is True
        assert second._web.sent == [node]

    asyncio.run(scenario())
