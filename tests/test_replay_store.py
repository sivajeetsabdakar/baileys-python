from __future__ import annotations

import asyncio
import time

import baileys as b
from baileys.auth_state import AuthState, JsonCredentialStore
from baileys.receipts import RetryRequest
from baileys.replay import InMemoryReplayStore, binary_node_from_json, binary_node_to_json
from baileys.socket import make_socket
from baileys.wabinary import BinaryNode


def _minimal_creds() -> dict:
    return {"me": {"id": "me@s.whatsapp.net", "name": "Me"}}


class FakeWeb:
    def __init__(self) -> None:
        self.sent = []

    async def send_node(self, node: BinaryNode) -> None:
        self.sent.append(node)


def test_binary_node_json_round_trip_preserves_content_types():
    node = BinaryNode(
        "message",
        {"id": "m1", "to": "chat@s.whatsapp.net"},
        [
            BinaryNode("enc", {"type": "msg"}, b"ciphertext"),
            BinaryNode("meta", {}, "text"),
        ],
    )

    restored = binary_node_from_json(binary_node_to_json(node))

    assert restored == node


def test_in_memory_replay_store_expires_entries():
    store = InMemoryReplayStore()
    node = BinaryNode("message", {"id": "m1"})

    store.save_recent_outbound("m1", node, time.time() - 1)

    assert store.load_recent_outbound("m1") is None
    assert store.prune_expired() == 0


def test_socket_replay_store_can_resend_across_client_instances(tmp_path):
    async def scenario():
        replay_store = InMemoryReplayStore()
        creds_path = tmp_path / "creds.json"
        store = JsonCredentialStore(creds_path)
        store.save_credentials(_minimal_creds())
        node = BinaryNode("message", {"id": "m1", "to": "chat@s.whatsapp.net", "type": "text"})

        first = make_socket(AuthState.from_store(store), replay_store=replay_store)
        first._web = FakeWeb()
        await first.relay_message("chat@s.whatsapp.net", node)

        second = make_socket(AuthState.from_store(store), replay_store=replay_store)
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
        assert second.loadRecentOutbound("m1") == node
        assert second.pruneRecentOutbound() == 0

    asyncio.run(scenario())
