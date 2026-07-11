from __future__ import annotations

import asyncio
import base64

import baileys as b
from baileys.auth_state import AuthState, JsonCredentialStore
from baileys.chat_groups import (
    block_status_node,
    on_whatsapp_node,
    group_metadata_node,
    group_participants_update_node,
    parse_group_metadata,
    parse_on_whatsapp,
    parse_privacy_settings,
    profile_picture_url_node,
)
from baileys.socket_nodes import IQError, parse_iq_error
from baileys.socket import make_socket
from baileys.wabinary import BinaryNode


def _minimal_creds() -> dict:
    return {"me": {"id": "me@s.whatsapp.net", "name": "Me"}}


def _creds_with_app_state() -> dict:
    key_id = base64.b64encode(b"k" * 32).decode("ascii")
    creds = _minimal_creds()
    creds.update(
        {
            "myAppStateKeyId": key_id,
            "app_state_sync_keys": {key_id: {"keyData": base64.b64encode(b"a" * 32).decode("ascii")}},
        }
    )
    return creds


def test_group_nodes_and_parsers_match_common_shapes():
    node = group_metadata_node("123@g.us", "tag-1")
    assert node.attrs == {"id": "tag-1", "type": "get", "xmlns": "w:g2", "to": "123@g.us"}
    assert node.content[0].tag == "query"

    update = group_participants_update_node("123@g.us", ["a@s.whatsapp.net"], "promote", "tag-2")
    assert update.content[0].tag == "promote"
    assert update.content[0].content[0].attrs["jid"] == "a@s.whatsapp.net"

    parsed = parse_group_metadata(
        BinaryNode(
            "iq",
            {"type": "result"},
            [
                BinaryNode(
                    "group",
                    {"id": "123", "subject": "Test", "size": "1", "addressing_mode": "lid"},
                    [
                        BinaryNode(
                            "participant",
                            {"jid": "a@lid", "type": "admin", "phone_number": "a@s.whatsapp.net"},
                        ),
                        BinaryNode("description", {"id": "d1"}, [BinaryNode("body", {}, b"hello")]),
                    ],
                )
            ],
        )
    )
    assert parsed.id == "123@g.us"
    assert parsed.subject == "Test"
    assert parsed.desc == "hello"
    assert parsed.participants[0].admin == "admin"
    assert parsed.participants[0].phone_number == "a@s.whatsapp.net"


def test_iq_error_parser_exposes_server_code_and_text():
    node = BinaryNode(
        "iq",
        {"type": "error", "id": "g1"},
        [BinaryNode("error", {"code": "463", "text": "account_reachout_restricted"})],
    )

    error = parse_iq_error(node)

    assert isinstance(error, IQError)
    assert error.code == "463"
    assert error.text == "account_reachout_restricted"


def test_privacy_profile_and_on_whatsapp_nodes_parse():
    privacy = parse_privacy_settings(
        BinaryNode(
            "iq",
            {},
            [BinaryNode("privacy", {}, [BinaryNode("category", {"name": "last", "value": "contacts"})])],
        )
    )
    assert privacy == {"last": "contacts"}

    picture = profile_picture_url_node("123@s.whatsapp.net", "pic-1", "image")
    assert picture.attrs["xmlns"] == "w:profile:picture"
    assert picture.content[0].attrs == {"type": "image", "query": "url"}

    block = block_status_node("123@lid", "unblock", "b1")
    assert block.attrs["xmlns"] == "blocklist"
    assert block.content[0].attrs["action"] == "unblock"
    assert block.content[0].attrs["jid"] == "123@lid"

    block = block_status_node("123@lid", "block", "b2", pn_jid="456@s.whatsapp.net")
    assert block.content[0].attrs == {"action": "block", "jid": "123@lid", "pn_jid": "456@s.whatsapp.net"}

    on_wa = parse_on_whatsapp(
        BinaryNode(
            "iq",
            {},
            [
                BinaryNode(
                    "usync",
                    {},
                    [BinaryNode("list", {}, [BinaryNode("user", {"jid": "123@s.whatsapp.net"}, [BinaryNode("contact", {"type": "in"})])])],
                )
            ],
        )
    )
    assert on_wa == [{"jid": "123@s.whatsapp.net", "exists": True}]

    on_wa_bool = parse_on_whatsapp(
        BinaryNode(
            "iq",
            {},
            [
                BinaryNode(
                    "usync",
                    {},
                    [
                        BinaryNode(
                            "list",
                            {},
                            [
                                BinaryNode(
                                    "user",
                                    {"id": "321@s.whatsapp.net"},
                                    [BinaryNode("contact", {"value": "true"})],
                                )
                            ],
                        )
                    ],
                )
            ],
        )
    )
    assert on_wa_bool == [{"jid": "321@s.whatsapp.net", "exists": True}]


def test_on_whatsapp_nodes_and_queries_match_expected_shape():
    on_query = on_whatsapp_node(["+1234567890@s.whatsapp.net"], "tag-3")
    assert on_query.attrs == {"id": "tag-3", "to": "s.whatsapp.net", "type": "get", "xmlns": "usync"}

    user_nodes = on_query.content[0].content[1].content  # iq > usync > list > users
    assert len(user_nodes) == 1
    assert user_nodes[0].tag == "user"
    assert user_nodes[0].attrs == {}
    assert len(user_nodes[0].content) == 1
    assert user_nodes[0].content[0].tag == "contact"
    assert user_nodes[0].content[0].content == b"+1234567890"


def test_client_phase5_methods_call_query_and_emit_events(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_creds_with_app_state())
        client = make_socket(AuthState.from_store(store))
        queries = []
        group_updates = []
        chat_updates = []
        client.ev.on("groups.update", lambda payload: group_updates.append(payload))
        client.ev.on("chats.update", lambda payload: chat_updates.append(payload))

        async def fake_query(node, **kwargs):
            queries.append(node)
            if node.attrs.get("xmlns") == "w:g2":
                return BinaryNode("iq", {}, [BinaryNode("group", {"id": "123", "subject": "Group"})])
            if node.attrs.get("xmlns") == "privacy":
                return BinaryNode("iq", {}, [BinaryNode("privacy", {}, [BinaryNode("category", {"name": "last", "value": "all"})])])
            return BinaryNode("iq", {"type": "result"})

        client.query = fake_query  # type: ignore[method-assign]

        metadata = await client.group_metadata("123@g.us")
        privacy = await client.fetch_privacy_settings()
        await client.chat_modify({"archive": True}, "chat@s.whatsapp.net")

        assert metadata.subject == "Group"
        assert privacy == {"last": "all"}
        assert group_updates[0][0].id == "123@g.us"
        assert chat_updates[0][0]["archive"] is True
        assert queries[0].attrs["xmlns"] == "w:g2"
        assert queries[-1].attrs["xmlns"] == "w:sync:app:state"
        assert queries[-1].content[0].tag == "sync"
        assert client.groupMetadata.__func__ is client.group_metadata.__func__
        assert client.fetchPrivacySettings.__func__ is client.fetch_privacy_settings.__func__
        assert b.GroupMetadata is not None

    asyncio.run(scenario())


def test_group_participant_update_raises_iq_error_and_skips_event(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_creds_with_app_state())
        client = make_socket(AuthState.from_store(store))
        participant_updates = []
        client.ev.on("group-participants.update", lambda payload: participant_updates.append(payload))

        async def fake_query(node, **kwargs):
            return BinaryNode(
                "iq",
                {"type": "error", "id": node.attrs.get("id", "x")},
                [BinaryNode("error", {"code": "463", "text": "account_reachout_restricted"})],
            )

        client.query = fake_query  # type: ignore[method-assign]

        try:
            await client.group_participants_update("123@g.us", ["a@s.whatsapp.net"], "add")
        except IQError as exc:
            assert exc.code == "463"
            assert exc.text == "account_reachout_restricted"
        else:
            raise AssertionError("expected IQError")

        assert participant_updates == []

    asyncio.run(scenario())


def test_group_participant_add_can_fallback_to_invite(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_creds_with_app_state())
        client = make_socket(AuthState.from_store(store))
        invite_events = []
        sent_invites = []
        client.ev.on("group-participants.invite", lambda payload: invite_events.append(payload))

        async def fake_query(node, **kwargs):
            return BinaryNode(
                "iq",
                {"type": "error", "id": node.attrs.get("id", "x")},
                [BinaryNode("error", {"code": "463", "text": "account_reachout_restricted"})],
            )

        async def fake_send_group_invite(to_jid, group_jid, **kwargs):
            sent_invites.append((to_jid, group_jid, kwargs))
            return {"message_id": "invite-1", "remote_jid": to_jid}

        client.query = fake_query  # type: ignore[method-assign]
        client.send_group_invite = fake_send_group_invite  # type: ignore[method-assign]

        result = await client.group_participants_update_or_invite(
            "123@g.us",
            ["a@s.whatsapp.net"],
            "add",
            wait_for_ack=2,
        )

        assert result["fallback"] == "group_invite"
        assert sent_invites == [("a@s.whatsapp.net", "123@g.us", {"timeout": 30, "wait_for_ack": 2})]
        assert invite_events[0]["reason"] == "account_reachout_restricted"

    asyncio.run(scenario())


def test_group_description_update_sends_previous_description_id(tmp_path):
    async def scenario():
        store = JsonCredentialStore(tmp_path / "creds.json")
        store.save_credentials(_creds_with_app_state())
        client = make_socket(AuthState.from_store(store))
        queries = []

        async def fake_query(node, **kwargs):
            queries.append(node)
            if node.attrs.get("xmlns") == "w:g2" and node.attrs.get("type") == "get":
                return BinaryNode(
                    "iq",
                    {"type": "result"},
                    [
                        BinaryNode(
                            "group",
                            {"id": "123", "subject": "Group"},
                            [BinaryNode("description", {"id": "desc-1"}, [BinaryNode("body", {}, b"old")])],
                        )
                    ],
                )
            return BinaryNode("iq", {"type": "result"})

        client.query = fake_query  # type: ignore[method-assign]

        await client.group_update_description("123@g.us", "new")

        assert queries[0].content[0].tag == "query"
        description = queries[1].content[0]
        assert description.tag == "description"
        assert description.attrs["prev"] == "desc-1"

    asyncio.run(scenario())


def test_presence_update_sends_expected_nodes(tmp_path):
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
        client.ev.on("connection.update", lambda payload: updates.append(payload))

        await client.send_presence_update("available")
        await client.send_presence_update("recording", "chat@s.whatsapp.net")

        assert client._web.sent[0].tag == "presence"
        assert client._web.sent[0].attrs["type"] == "available"
        assert client._web.sent[1].tag == "chatstate"
        assert client._web.sent[1].content[0].attrs == {"media": "audio"}
        assert updates[-1] == {"isOnline": True}
        assert client.sendPresenceUpdate.__func__ is client.send_presence_update.__func__

    asyncio.run(scenario())
