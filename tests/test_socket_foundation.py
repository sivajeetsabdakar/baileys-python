from __future__ import annotations

import asyncio

import baileys as b
from baileys import AuthState, JsonCredentialStore, makeWASocket, make_socket
from baileys.auth_store import creds_from_generated_signal_material
from baileys.crypto import hmac_sign
from baileys.message_send import OutboundMessage
from baileys.events import EventEmitter
from baileys.jid import jid_decode_tuple
from baileys.generated import WAProto_pb2 as proto
from baileys.noise import generate_noise_key_pair
from baileys.pairing_code import configure_successful_pairing
from baileys.registration import build_registration_payload
from baileys.signal_crypto import sign, verify
from baileys.query import QueryManager
from baileys.socket_nodes import find_child
from baileys import socket as socket_module
from baileys.socket import WhatsAppClient, _session_key_for_jid
from baileys.wabinary import BinaryNode
from signal_protocol import curve, identity_key


def _minimal_creds() -> dict:
    return {
        "me": {"id": "me@s.whatsapp.net"},
        "identity_public": "id-pub",
        "identity_private": "id-priv",
        "registration_id": 123,
        "signed_pre_key_id": 4,
        "signed_pre_key_public": "spk-pub",
        "signed_pre_key_private": "spk-priv",
        "signed_pre_key_signature": "spk-sig",
    }


def _signal_key_pair() -> curve.KeyPair:
    public_key, private_key = curve.generate_keypair()
    return curve.KeyPair.from_public_and_private(public_key, private_key)


def _generated_creds() -> dict:
    identity = identity_key.IdentityKeyPair.generate()
    signed_pair = _signal_key_pair()
    signature = identity.private_key().calculate_signature(signed_pair.public_key().serialize())
    creds = creds_from_generated_signal_material(
        identity_pair=identity,
        registration_id=1234,
        signed_pre_key_id=1,
        signed_pre_key_pair=signed_pair,
        signed_pre_key_signature=signature,
    )
    creds["me"] = {"id": "me:1@s.whatsapp.net"}
    return creds


def test_make_socket_exports_and_coerces_json_auth_path(tmp_path):
    creds_path = tmp_path / "creds.json"
    JsonCredentialStore(creds_path).save_credentials(_minimal_creds())

    client = make_socket(creds_path)

    assert isinstance(client, WhatsAppClient)
    assert makeWASocket(creds_path).websocket_url == client.websocket_url
    assert b.make_socket is make_socket
    assert b.makeWASocket is makeWASocket
    assert client.creds["registration_id"] == 123


def test_make_socket_allows_missing_creds_for_qr_first_login(tmp_path):
    creds_path = tmp_path / "future-creds.json"

    client = make_socket(creds_path)

    assert client.creds == {}
    assert client.auth_state.credential_store.path == creds_path


def test_make_socket_accepts_auth_state(tmp_path):
    store = JsonCredentialStore(tmp_path / "creds.json")
    store.save_credentials(_minimal_creds())
    state = AuthState.from_store(store)

    client = make_socket(state)

    assert client.auth_state is state
    assert client.origin == b.SocketConfig().origin


def test_event_emitter_on_once_off_and_wait_for():
    async def scenario():
        emitter = EventEmitter()
        seen = []

        def sync_handler(payload):
            seen.append(("sync", payload))

        async def async_handler(payload):
            seen.append(("async", payload))

        ref = emitter.on("node", sync_handler)
        emitter.once("node", async_handler)
        assert await emitter.emit("node", {"id": 1}) == 2
        assert await emitter.emit("node", {"id": 2}) == 1
        assert emitter.off("node", ref)
        assert await emitter.emit("node", {"id": 3}) == 0
        assert seen == [
            ("sync", {"id": 1}),
            ("async", {"id": 1}),
            ("sync", {"id": 2}),
        ]

        waiter = asyncio.create_task(emitter.wait_for("connection.update", timeout=1))
        await asyncio.sleep(0)
        await emitter.emit("connection.update", {"connection": "open"})
        assert await waiter == {"connection": "open"}

    asyncio.run(scenario())


def test_query_manager_resolves_by_node_id_and_cancels_pending():
    async def scenario():
        manager = QueryManager()
        waiter = asyncio.create_task(manager.wait_for("abc", timeout=1))
        await asyncio.sleep(0)

        assert manager.pending_ids == ("abc",)
        assert manager.resolve(BinaryNode("iq", {"id": "abc", "type": "result"}))
        assert (await waiter).attrs["type"] == "result"
        assert manager.pending_ids == ()

        manager.create_waiter("left")
        assert manager.cancel_all() == 1
        assert manager.pending_ids == ()

    asyncio.run(scenario())


def test_client_receive_nodes_routes_query_matches_and_events(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.nodes = [
                BinaryNode("iq", {"id": "q1", "type": "result"}),
                BinaryNode("message", {"id": "m1"}),
            ]

        async def receive_nodes(self, timeout=30):
            return self.nodes

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        seen = []
        client.ev.on("node", lambda node: seen.append(node.tag))

        waiter = asyncio.create_task(client.queries.wait_for("q1", timeout=1))
        await asyncio.sleep(0)
        nodes = await client.receive_nodes()

        assert [node.tag for node in nodes] == ["iq", "message"]
        assert (await waiter).attrs["id"] == "q1"
        assert seen == ["message"]

    asyncio.run(scenario())


def test_dispatch_node_auto_replies_to_server_ping_and_emits_kind_event(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.sent = []

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        seen = []
        client.ev.on("node.server_ping", lambda node: seen.append(node.attrs["id"]))

        kind = await client.dispatch_node(
            BinaryNode("iq", {"id": "ping-1", "type": "get", "xmlns": "urn:xmpp:ping", "t": "123"})
        )

        assert kind.value == "server_ping"
        assert client._web.sent[0].attrs == {"to": "s.whatsapp.net", "type": "result", "id": "ping-1", "t": "123"}
        assert seen == ["ping-1"]

    asyncio.run(scenario())


def test_dispatch_offline_preview_requests_offline_batch(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.sent = []

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()

        kind = await client.dispatch_node(BinaryNode("ib", {}, [BinaryNode("offline_preview", {"count": "1"})]))

        assert kind.value == "offline_preview"
        assert client._web.sent[0].tag == "ib"
        assert client._web.sent[0].content[0].tag == "offline_batch"

    asyncio.run(scenario())


def test_dispatch_offline_completion_emits_update(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        offline = []
        connection = []
        client.ev.on("offline.update", lambda payload: offline.append(payload))
        client.ev.on("connection.update", lambda payload: connection.append(payload))

        kind = await client.dispatch_node(BinaryNode("ib", {}, [BinaryNode("offline", {"count": "3"})]))

        assert kind.value == "offline"
        assert offline[0].count == 3
        assert offline[0].preview is False
        assert connection[-1] == {"connection": "open", "received_pending_notifications": True}

    asyncio.run(scenario())


def test_dispatch_dirty_emits_app_state_dirty(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        dirty = []
        client.ev.on("app-state.dirty", lambda payload: dirty.append(payload))

        kind = await client.dispatch_node(
            BinaryNode("ib", {}, [BinaryNode("dirty", {"type": "groups", "timestamp": "123"})])
        )

        assert kind.value == "dirty"
        assert dirty[0].type == "groups"
        assert dirty[0].timestamp == 123

    asyncio.run(scenario())


def test_dispatch_notification_emits_typed_category_and_ack(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.sent = []

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        all_notifications = []
        device_notifications = []
        client.ev.on("notifications.upsert", lambda payload: all_notifications.append(payload))
        client.ev.on("notifications.devices", lambda payload: device_notifications.append(payload))

        kind = await client.dispatch_node(
            BinaryNode(
                "notification",
                {"id": "n1", "from": "user@s.whatsapp.net", "type": "devices", "t": "456"},
                [BinaryNode("devices", {"hash": "abc"})],
            )
        )

        assert kind.value == "notification"
        assert all_notifications[0].id == "n1"
        assert all_notifications[0].category == "devices"
        assert all_notifications[0].timestamp == 456
        assert device_notifications == all_notifications
        assert client._web.sent[0].attrs == {
            "id": "n1",
            "to": "user@s.whatsapp.net",
            "class": "notification",
            "type": "devices",
        }

    asyncio.run(scenario())


def test_dispatch_call_emits_call_update_and_ack(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.sent = []

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        calls = []
        client.ev.on("calls.update", lambda payload: calls.extend(payload))

        kind = await client.dispatch_node(
            BinaryNode("call", {"id": "c1", "from": "caller@s.whatsapp.net", "t": "789"}, [BinaryNode("offer", {})])
        )

        assert kind.value == "call"
        assert calls[0].id == "c1"
        assert calls[0].child_tags == ("offer",)
        assert client._web.sent[0].attrs == {
            "id": "c1",
            "to": "caller@s.whatsapp.net",
            "class": "call",
        }

    asyncio.run(scenario())


def test_dispatch_stream_error_emits_disconnect_reason(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.closed = False

        async def close(self):
            self.closed = True

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        updates = []
        client.ev.on("connection.update", lambda payload: updates.append(payload))

        kind = await client.dispatch_node(BinaryNode("stream:error", {}, [BinaryNode("conflict", {})]))

        assert kind.value == "stream_error"
        assert updates[-1]["connection"] == "close"
        assert updates[-1]["disconnect_reason"] == b.DisconnectReason.connectionReplaced
        assert updates[-1]["disconnect_reason_name"] == "connectionReplaced"
        assert updates[-1]["last_disconnect"].reason == "conflict"
        assert client._web is None

    asyncio.run(scenario())


def test_dispatch_failure_emits_disconnect_reason(tmp_path):
    class FakeWeb:
        async def close(self):
            pass

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        updates = []
        client.ev.on("connection.update", lambda payload: updates.append(payload))

        kind = await client.dispatch_node(BinaryNode("failure", {"reason": "401"}))

        assert kind.value == "failure"
        assert updates[-1]["disconnect_reason"] == b.DisconnectReason.loggedOut
        assert updates[-1]["disconnect_reason_name"] == "loggedOut"
        assert updates[-1]["last_disconnect"].message == "Connection Failure"

    asyncio.run(scenario())


def test_dispatch_receipt_emits_update_and_sends_ack(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.sent = []

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        updates = []
        client.ev.on("messages.update", lambda payload: updates.extend(payload))

        node = BinaryNode(
            "receipt",
            {"id": "r1", "from": "user@s.whatsapp.net", "type": "read", "t": "123"},
            [BinaryNode("list", {}, [BinaryNode("item", {"id": "r2"})])],
        )
        kind = await client.dispatch_node(node)

        assert kind.value == "receipt"
        assert [update["key"]["id"] for update in updates] == ["r1", "r2"]
        assert updates[0]["key"]["remote_jid"] == "user@s.whatsapp.net"
        assert updates[0]["key"]["from_me"] is True
        assert updates[0]["update"] == {
            "status": proto.WebMessageInfo.Status.READ,
            "message_timestamp": 123,
        }
        assert client._web.sent[0].tag == "ack"
        assert client._web.sent[0].attrs == {
            "id": "r1",
            "to": "user@s.whatsapp.net",
            "class": "receipt",
            "type": "read",
        }

    asyncio.run(scenario())


def test_dispatch_group_receipt_emits_user_receipt_update(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.sent = []

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        updates = []
        client.ev.on("message-receipt.update", lambda payload: updates.extend(payload))

        node = BinaryNode(
            "receipt",
            {
                "id": "g1",
                "from": "group@g.us",
                "participant": "sender@c.us",
                "type": "read",
                "t": "456",
            },
            [BinaryNode("list", {}, [BinaryNode("item", {"id": "g2"})])],
        )

        kind = await client.dispatch_node(node)

        assert kind.value == "receipt"
        assert [update["key"]["id"] for update in updates] == ["g1", "g2"]
        assert updates[0]["key"] == {
            "remote_jid": "group@g.us",
            "id": "g1",
            "from_me": True,
            "participant": "sender@c.us",
        }
        assert updates[0]["receipt"] == {
            "user_jid": "sender@s.whatsapp.net",
            "read_timestamp": 456,
        }
        assert client._web.sent[0].tag == "ack"

    asyncio.run(scenario())


def test_dispatch_retry_receipt_emits_outcome_and_calls_resend_hook(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        outcomes = []
        requests = []
        client.ev.on("messages.retry", lambda payload: outcomes.append(payload))

        async def fake_resend(request):
            requests.append(request)
            return True

        client.resend_message_for_retry = fake_resend
        node = BinaryNode(
            "receipt",
            {"id": "m1", "from": "user@s.whatsapp.net", "type": "retry"},
            [BinaryNode("retry", {"id": "m1", "count": "1", "error": "0"})],
        )

        await client.dispatch_receipt_node(node)

        assert len(requests) == 1
        assert requests[0].key.from_me is True
        assert requests[0].key.participant == "user@s.whatsapp.net"
        assert outcomes[0].request is requests[0]
        assert outcomes[0].will_retry is True
        assert outcomes[0].resent is True
        assert outcomes[0].reason == "resent"

    asyncio.run(scenario())


def test_dispatch_retry_receipt_respects_max_retry_count(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store), max_msg_retry_count=1)
        outcomes = []
        calls = []
        client.ev.on("messages.retry", lambda payload: outcomes.append(payload))

        async def fake_resend(request):
            calls.append(request)
            return True

        client.resend_message_for_retry = fake_resend
        node = BinaryNode(
            "receipt",
            {"id": "m1", "from": "user@s.whatsapp.net", "type": "retry"},
            [BinaryNode("retry", {"id": "m1", "count": "1"})],
        )

        await client.dispatch_receipt_node(node)
        await client.dispatch_receipt_node(node)

        assert len(calls) == 1
        assert [outcome.local_retry_count for outcome in outcomes] == [1, 2]
        assert outcomes[-1].will_retry is False
        assert outcomes[-1].reason == "max_retries_exceeded"

    asyncio.run(scenario())


def test_dispatch_retry_receipt_for_not_from_me_does_not_resend(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        outcomes = []
        client.ev.on("messages.retry", lambda payload: outcomes.append(payload))

        async def unexpected_resend(request):
            raise AssertionError("retry receipt not for our sent message should not resend")

        client.resend_message_for_retry = unexpected_resend
        node = BinaryNode(
            "receipt",
            {
                "id": "m1",
                "from": "user@s.whatsapp.net",
                "recipient": "me@s.whatsapp.net",
                "type": "retry",
            },
            [BinaryNode("retry", {"id": "m1", "count": "1"})],
        )

        await client.dispatch_receipt_node(node)

        assert outcomes[0].will_retry is False
        assert outcomes[0].reason == "not_from_me"

    asyncio.run(scenario())


def test_logout_sends_remove_companion_device_and_clears_auth(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        sent = []
        updates = []
        creds_updates = []
        client.ev.on("connection.update", lambda payload: updates.append(payload))
        client.ev.on("creds.update", lambda payload: creds_updates.append(payload))

        async def fake_send_node(node):
            sent.append(node)

        client.send_node = fake_send_node

        await client.logout()

        assert sent[0].tag == "iq"
        assert sent[0].attrs["xmlns"] == "md"
        assert sent[0].attrs["to"] == "s.whatsapp.net"
        assert sent[0].content[0].tag == "remove-companion-device"
        assert sent[0].content[0].attrs == {"jid": "me@s.whatsapp.net", "reason": "user_initiated"}
        assert client.auth_state.credentials == {}
        assert store.load_credentials() == {}
        assert creds_updates[-1] == {}
        assert updates[-1]["disconnect_reason"] == b.DisconnectReason.loggedOut
        assert updates[-1]["last_disconnect"].message == "Intentional Logout"

    asyncio.run(scenario())


def test_send_receipt_and_read_messages_build_receipt_nodes(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.sent = []

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()

        direct = await client.send_receipt("user@s.whatsapp.net", ["m1", "m2"], receipt_type="read")
        bulk = await client.read_messages(
            [
                b.MessageKey("group@g.us", "g1", participant="sender@s.whatsapp.net"),
                b.MessageKey("group@g.us", "g2", participant="sender@s.whatsapp.net"),
            ]
        )

        assert direct.attrs["id"] == "m1"
        assert direct.attrs["type"] == "read"
        assert direct.content[0].content[0].attrs["id"] == "m2"
        assert bulk[0].attrs["to"] == "group@g.us"
        assert bulk[0].attrs["participant"] == "sender@s.whatsapp.net"
        assert bulk[0].content[0].content[0].attrs["id"] == "g2"
        assert [sent.tag for sent in client._web.sent] == ["receipt", "receipt"]

    asyncio.run(scenario())


def test_wait_for_success_sends_session_init_nodes(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.creds = _minimal_creds()
            self.sent = []

        async def wait_for_success(self, timeout=60, reply_to_pings=True):
            return BinaryNode("success", {"t": "1000"})

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store), auto_prekey_maintenance=False)
        client._web = FakeWeb()

        node = await client.wait_for_success()

        assert node.attrs == {"t": "1000"}
        assert [sent.tag for sent in client._web.sent] == ["iq", "ib"]
        assert client._web.sent[0].attrs["xmlns"] == "passive"
        assert client._web.sent[1].content[0].tag == "unified_session"

    asyncio.run(scenario())


def test_wait_for_success_runs_prekey_maintenance_with_direct_receive(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.creds = _generated_creds()
            self.sent = []
            self.pending = []

        async def wait_for_success(self, timeout=60, reply_to_pings=True):
            return BinaryNode("success", {"t": "1000"})

        async def send_node(self, node):
            self.sent.append(node)
            if node.content[0].tag == "count":
                self.pending.append(BinaryNode("iq", {"id": node.attrs["id"], "type": "result"}, [BinaryNode("count", {"value": "2"})]))
            elif node.content[0].tag == "registration":
                self.pending.append(BinaryNode("iq", {"id": node.attrs["id"], "type": "result"}))

        async def receive_nodes(self, timeout=30):
            if not self.pending:
                raise TimeoutError("no pending node")
            return [self.pending.pop(0)]

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_generated_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        events = []
        client.ev.on("prekeys.update", lambda payload: events.append(payload))

        await client.wait_for_success()

        saved = store.load_credentials()
        assert [sent.content[0].tag for sent in client._web.sent] == ["active", "unified_session", "count", "registration"]
        assert saved["first_unuploaded_pre_key_id"] == 6
        assert set(saved["pre_keys"]) == {"1", "2", "3", "4", "5"}
        assert events[-1]["maintenance"] == "uploaded"
        assert events[-1]["reason"] == "server_count_low"

    asyncio.run(scenario())


def test_maintain_prekeys_skips_upload_when_server_count_is_healthy(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        creds = _generated_creds()
        creds["next_pre_key_id"] = 1
        store.save_credentials(creds)
        client = make_socket(AuthState.from_store(store))
        sent = []
        events = []
        client.ev.on("prekeys.update", lambda payload: events.append(payload))

        async def fake_send_node(node):
            sent.append(node)
            client.queries.resolve(
                BinaryNode("iq", {"id": node.attrs["id"], "type": "result"}, [BinaryNode("count", {"value": "20"})])
            )

        client.send_node = fake_send_node

        result = await client.maintain_pre_keys()

        assert result.server_count == 20
        assert result.uploaded is None
        assert [node.content[0].tag for node in sent] == ["count"]
        assert events == [{"server_count": 20, "maintenance": "ok"}]

    asyncio.run(scenario())


def test_receive_loop_dispatches_until_stopped_by_handler(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.count = 0

        async def receive_nodes(self, timeout=30):
            self.count += 1
            return [BinaryNode("message", {"id": f"m{self.count}"})]

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        seen = []

        def on_message(node):
            seen.append(node.attrs["id"])
            client._closing = True

        client.ev.on("node.message", on_message)
        await client.receive_forever(timeout=0.01)

        assert seen == ["m1"]

    asyncio.run(scenario())


def test_receive_loop_emits_close_without_leaking_task_exception(tmp_path):
    class FakeWeb:
        async def receive_nodes(self, timeout=30):
            raise RuntimeError("socket closed")

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store), auto_reconnect=False)
        client._web = FakeWeb()
        updates = []
        client.ev.on("connection.update", lambda payload: updates.append(payload))

        await client.receive_forever(timeout=0.01)
        await client.stop_receive_loop()

        assert any(update.get("last_disconnect") for update in updates)
        assert updates[-1] == {"connection": "close", "is_receive_loop_running": False}

    asyncio.run(scenario())


def test_reconnect_policy_retries_only_retryable_disconnects():
    policy = b.ReconnectPolicy(initial_delay=0.5, max_delay=2, multiplier=3)

    assert policy.delay_for_attempt(1) == 0.5
    assert policy.delay_for_attempt(2) == 1.5
    assert policy.delay_for_attempt(3) == 2
    assert policy.should_reconnect(RuntimeError("socket gone"))
    assert policy.should_reconnect(b.DisconnectError("lost", b.DisconnectReason.connectionLost))
    assert not policy.should_reconnect(b.DisconnectError("logout", b.DisconnectReason.loggedOut))
    assert not policy.should_reconnect(b.DisconnectError("replaced", b.DisconnectReason.connectionReplaced))


def test_receive_loop_reconnects_after_transport_error(tmp_path):
    class BrokenWeb:
        async def receive_nodes(self, timeout=30):
            raise RuntimeError("socket closed")

        async def close(self):
            pass

    class StableWeb:
        async def receive_nodes(self, timeout=30):
            return [BinaryNode("message", {"id": "after-reconnect"})]

        async def close(self):
            pass

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(
            AuthState.from_store(store),
            reconnect_initial_delay=0,
            reconnect_max_attempts=2,
            auto_prekey_maintenance=False,
        )
        client._web = BrokenWeb()
        attempts = []
        updates = []
        seen = []
        client.ev.on("connection.update", lambda payload: updates.append(payload))

        def on_message(node):
            seen.append(node.attrs["id"])
            client._closing = True

        async def fake_connect_and_wait(**kwargs):
            attempts.append(kwargs)
            client._web = StableWeb()
            return BinaryNode("success", {"t": "1000"})

        client.ev.on("node.message", on_message)
        client.connect_and_wait = fake_connect_and_wait

        await client.receive_forever(timeout=0.01, keepalive_interval=60)

        assert len(attempts) == 1
        assert attempts[0]["initialize"] is True
        assert seen == ["after-reconnect"]
        reconnecting = [update for update in updates if update.get("reconnect") and update["connection"] == "connecting"]
        assert reconnecting[0]["attempt"] == 1
        assert reconnecting[0]["delay"] == 0
        assert any(update.get("reconnect") and update["connection"] == "open" for update in updates)

    asyncio.run(scenario())


def test_receive_loop_does_not_reconnect_after_logged_out_failure(tmp_path):
    class LoggedOutWeb:
        async def receive_nodes(self, timeout=30):
            return [BinaryNode("failure", {"reason": "401"})]

        async def close(self):
            pass

    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store), reconnect_initial_delay=0)
        client._web = LoggedOutWeb()
        updates = []
        client.ev.on("connection.update", lambda payload: updates.append(payload))

        async def unexpected_reconnect(**kwargs):
            raise AssertionError("logged out failures must not reconnect")

        client.connect_and_wait = unexpected_reconnect

        await client.receive_forever(timeout=0.01)

        assert updates[-1] == {"connection": "close", "is_receive_loop_running": False}
        assert not any(update.get("reconnect") for update in updates)
        assert any(update.get("disconnect_reason") == b.DisconnectReason.loggedOut for update in updates)

    asyncio.run(scenario())


def test_build_and_request_pairing_code(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        emitted = []
        sent = []
        client.ev.on("connection.update", lambda payload: emitted.append(payload))

        async def fake_send_node(node):
            sent.append(node)
            client.queries.resolve(BinaryNode("iq", {"id": node.attrs["id"], "type": "result"}))

        client.send_node = fake_send_node
        request = await client.request_pairing_code(
            "+1 (555) 123-4567",
            custom_pairing_code="ABCDEFGH",
            companion_ephemeral_public=b"1" * 32,
            noise_public=b"2" * 32,
        )

        assert request.code == "ABCDEFGH"
        assert request.jid == "15551234567@s.whatsapp.net"
        assert sent[0].attrs["xmlns"] == "md"
        assert emitted[-1] == {"pairing_code": "ABCDEFGH", "pairing_jid": "15551234567@s.whatsapp.net"}

    asyncio.run(scenario())


def test_prekey_digest_upload_and_rotation_product_methods(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_generated_creds())
        client = make_socket(AuthState.from_store(store))
        sent = []
        emitted_prekeys = []
        client.ev.on("prekeys.update", lambda payload: emitted_prekeys.append(payload))

        async def fake_send_node(node):
            sent.append(node)
            if node.content and node.content[0].tag == "digest":
                content = [BinaryNode("digest", {"count": "12"})]
            else:
                content = []
            client.queries.resolve(BinaryNode("iq", {"id": node.attrs["id"], "type": "result"}, content))

        client.send_node = fake_send_node

        digest = await client.digest_key_bundle()
        upload = await client.upload_pre_keys(2)
        rotation = await client.rotate_signed_pre_key()

        saved = store.load_credentials()
        assert digest.attrs == {"count": "12"}
        assert upload.uploaded_ids == [1, 2]
        assert set(saved["pre_keys"]) == {"1", "2"}
        assert saved["next_pre_key_id"] == 3
        assert saved["first_unuploaded_pre_key_id"] == 3
        assert rotation.key_id == 2
        assert saved["signed_pre_key_id"] == 2
        assert emitted_prekeys == [{"uploaded": [1, 2]}]
        assert [node.content[0].tag for node in sent] == ["digest", "registration", "rotate"]

    asyncio.run(scenario())


def test_prekey_upload_does_not_persist_when_query_fails(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        original = _generated_creds()
        store.save_credentials(original)
        client = make_socket(AuthState.from_store(store))

        async def failing_send_node(node):
            raise RuntimeError("network down")

        client.send_node = failing_send_node

        try:
            await client.upload_pre_keys(2)
        except RuntimeError as exc:
            assert str(exc) == "network down"
        else:
            raise AssertionError("upload_pre_keys should fail")

        assert store.load_credentials() == original
        assert client.auth_state.credentials == original

    asyncio.run(scenario())


def _pair_success_fixture():
    static_noise = generate_noise_key_pair()
    primary = generate_noise_key_pair()
    _, meta = build_registration_payload()

    device_identity = proto.ADVDeviceIdentity()
    device_identity.rawId = 123
    device_identity.timestamp = 456
    device_identity.keyIndex = 7
    account = proto.ADVSignedDeviceIdentity()
    account.details = device_identity.SerializeToString()
    account.accountSignatureKey = primary.public
    account.accountSignature = sign(primary.private, bytes([6, 0]) + account.details + bytes(meta["identity_public"]))

    signed_hmac = proto.ADVSignedDeviceIdentityHMAC()
    signed_hmac.details = account.SerializeToString()
    signed_hmac.hmac = hmac_sign(signed_hmac.details, __import__("base64").b64decode(str(meta["adv_secret_key"])))

    node = BinaryNode(
        "iq",
        {"id": "pair-success-1", "type": "set"},
        [
            BinaryNode(
                "pair-success",
                {},
                [
                    BinaryNode("device-identity", {}, signed_hmac.SerializeToString()),
                    BinaryNode("platform", {"name": "Chrome"}),
                    BinaryNode("device", {"jid": "123:4@s.whatsapp.net", "lid": "999:4@lid"}),
                    BinaryNode("biz", {"name": "Test Biz"}),
                ],
            )
        ],
    )
    return static_noise, primary, meta, node


def test_configure_successful_pairing_builds_signed_reply_and_credentials():
    static_noise, primary, meta, node = _pair_success_fixture()

    success = configure_successful_pairing(node, static_noise=static_noise, meta=meta)

    assert success.reply.attrs == {"to": "s.whatsapp.net", "type": "result", "id": "pair-success-1"}
    pair_sign = success.reply.content[0]
    assert pair_sign.tag == "pair-device-sign"
    device_identity_node = pair_sign.content[0]
    assert device_identity_node.attrs == {"key-index": "7"}

    account = proto.ADVSignedDeviceIdentity()
    account.ParseFromString(success.account)
    device_message = bytes([6, 1]) + account.details + bytes(meta["identity_public"]) + primary.public
    assert verify(bytes(meta["identity_public"]), device_message, account.deviceSignature)
    assert success.credentials["me"] == {
        "id": "123:4@s.whatsapp.net",
        "lid": "999:4@lid",
        "name": "Test Biz",
    }
    assert success.credentials["noise_public"]


def test_client_finalize_pair_success_sends_reply_and_persists_credentials(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.sent = []

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        static_noise, _, meta, node = _pair_success_fixture()
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        updates = []
        client.ev.on("connection.update", lambda payload: updates.append(payload))

        success = await client.finalize_pair_success(node, static_noise=static_noise, meta=meta)

        assert client._web.sent[0] == success.reply
        assert store.load_credentials()["me"]["id"] == "123:4@s.whatsapp.net"
        assert updates[-1]["pairing"] == "success"

    asyncio.run(scenario())


def test_build_outbound_message_normalizes_plain_phone_jid(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_generated_creds())
        client = make_socket(AuthState.from_store(store))
        original_builder = socket_module.build_message_content_node

        async def fake_prepare(_: str, timeout: float, force_sessions: bool) -> None:
            pass

        def fake_build_message_content_node(
            creds: dict,
            recipient_jid: str,
            content: str | proto.Message | dict[str, object],
            *,
            message_id: str | None = None,
            direct_enc: bool = True,
            recipient_device_jids: object | None = None,
            own_fanout_jids: object = (),
            include_phash: bool = False,
        ) -> OutboundMessage:
            return OutboundMessage(
                node=BinaryNode(
                    "message",
                    {"id": message_id or "msg-id", "to": recipient_jid, "type": "text"},
                    [],
                ),
                message_id=message_id or "msg-id",
                signal_type="msg",
                recipient_address=None,  # type: ignore[arg-type]
                participant_jids=[f"{jid_decode_tuple(recipient_jid)[0]}:0@s.whatsapp.net"],
                signal_types={f"{jid_decode_tuple(recipient_jid)[0]}:0@s.whatsapp.net": "msg"},
            )

        client._prepare_direct_session = fake_prepare  # type: ignore[method-assign]
        socket_module.build_message_content_node = fake_build_message_content_node  # type: ignore[assignment]

        try:
            outbound = await client._build_outbound_message(
                "1234567890",
                "hello",
                message_id="msg-1",
                use_usync=False,
                force_sessions=False,
                include_phash=False,
                timeout=5,
            )
        finally:
            socket_module.build_message_content_node = original_builder

        assert outbound.node.attrs["to"] == "1234567890@s.whatsapp.net"
        assert outbound.participant_jids == ["1234567890:0@s.whatsapp.net"]

    asyncio.run(scenario())


def test_on_whatsapp_batches_and_falls_back_per_jid_on_timeout(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))

        queries: list[BinaryNode] = []

        async def fake_query(node: BinaryNode, **kwargs):
            queries.append(node)
            list_node = find_child(find_child(node, "usync"), "list")
            if not isinstance(list_node.content if list_node else None, list):
                return BinaryNode("iq", {"type": "result"}, [BinaryNode("usync", {}, [BinaryNode("list", {})])])
            user_jids = [user.attrs.get("jid") or user.attrs.get("id") for user in list_node.content]
            if len(user_jids) > 1:
                raise TimeoutError("timeout")
            user = list_node.content[0]
            user_jid = user_jids[0]
            if user_jid is None:
                contact = find_child(user, "contact")
                contact_value = contact.content if contact is not None and isinstance(contact.content, (bytes, str)) else b""
                if isinstance(contact_value, bytes):
                    contact_value = contact_value.decode("utf-8")
                user_jid = str(contact_value).lstrip("+")
            return BinaryNode(
                "iq",
                {"type": "result"},
                [
                    BinaryNode(
                        "usync",
                        {},
                        [
                            BinaryNode(
                                "list",
                                {},
                                [BinaryNode("user", {"id": user_jid}, [BinaryNode("contact", {"type": "in"})])],
                            )
                        ],
                    )
                ],
            )

        client.query = fake_query  # type: ignore[method-assign]

        results = await client.on_whatsapp("111", "222", "333", timeout=2)

        assert [result["jid"] for result in results] == [
            "111",
            "222",
            "333",
        ]
        assert len(queries) == 4
        first = find_child(find_child(queries[0], "usync"), "list")
        assert first is not None and len(first.content) == 3

    asyncio.run(scenario())


def test_on_whatsapp_skips_unsupported_lid_jids(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))

        async def fake_query(node: BinaryNode, **kwargs):
            list_node = find_child(find_child(node, "usync"), "list")
            assert list_node is not None
            phones = []
            for user in list_node.content:
                contact = find_child(user, "contact")
                if contact is None or not isinstance(contact.content, (bytes, str)):
                    continue
                phones.append(contact.content.decode("utf-8") if isinstance(contact.content, bytes) else str(contact.content))
            assert phones == ["+456"]
            return BinaryNode(
                "iq",
                {"type": "result"},
                [
                    BinaryNode("usync", {}, [BinaryNode("list", {}, [])]),
                ],
            )

        client.query = fake_query  # type: ignore[method-assign]

        results = await client.on_whatsapp("123@lid", "456")
        assert results == []

    asyncio.run(scenario())


def test_dispatch_pair_success_auto_finalizes_qr_context(tmp_path):
    class FakeWeb:
        def __init__(self):
            self.sent = []

        async def send_node(self, node):
            self.sent.append(node)

    async def scenario():
        static_noise, _, meta, node = _pair_success_fixture()
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_minimal_creds())
        client = make_socket(AuthState.from_store(store))
        client._web = FakeWeb()
        client._qr_static_noise = static_noise
        client._qr_meta = meta

        kind = await client.dispatch_node(node)

        assert kind.value == "unknown"
        assert client._web.sent[0].tag == "iq"
        assert store.load_credentials()["platform"] == "Chrome"
        assert client._qr_static_noise is None
        assert client._qr_meta is None

    asyncio.run(scenario())


def test_session_key_normalization_handles_malformed_jids():
    assert _session_key_for_jid("919272419368:s.whatsapp.net") == "919272419368:0"
    assert _session_key_for_jid("111@lid") == "111:0"
    assert _session_key_for_jid("111:2@lid") == "111:2"


def test_forced_session_fetch_still_checks_post_fetch_store(tmp_path):
    store = JsonCredentialStore(tmp_path / "creds.json")
    creds = _minimal_creds()
    creds["signal_sessions"] = {"123:0": "session"}
    store.save_credentials(creds)
    client = make_socket(AuthState.from_store(store))

    assert client._missing_session_jids(["123@s.whatsapp.net"], force=True) == ["123@s.whatsapp.net"]
    assert (
        client._missing_session_jids_from_credentials(
            client.auth_state.credentials,
            ["123@s.whatsapp.net"],
            force=True,
        )
        == []
    )
