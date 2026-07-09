from __future__ import annotations

import asyncio
import base64
import json

import baileys as b
from baileys.auth_state import AuthState, JsonCredentialStore
from baileys.business import catalog_node, parse_catalog, parse_product_delete, product_create_node, product_delete_node
from baileys.communities import community_create_node, community_metadata_node, parse_community_metadata
from baileys.app_state import chat_modification_to_app_patch
from baileys.mex import QUERY_IDS, parse_wmex_result, wmex_query_node
from baileys.newsletter import newsletter_fetch_messages_node, newsletter_metadata_query, parse_newsletter_metadata
from baileys.socket import make_socket
from baileys.wabinary import BinaryNode


def _creds_with_app_state(tmp_path):
    key_id = base64.b64encode(b"k" * 32).decode("ascii")
    creds = {
        "me": {"id": "me@s.whatsapp.net", "name": "Me"},
        "myAppStateKeyId": key_id,
        "app_state_sync_keys": {key_id: {"keyData": base64.b64encode(b"a" * 32).decode("ascii")}},
    }
    store = JsonCredentialStore(tmp_path / "creds.json")
    store.save_credentials(creds)
    return AuthState.from_store(store)


def test_business_catalog_nodes_and_parsers():
    node = catalog_node("123@s.whatsapp.net", "tag-1", limit=5, cursor="abc")
    assert node.attrs["xmlns"] == "w:biz:catalog"
    catalog = node.content[0]
    assert catalog.tag == "product_catalog"
    assert catalog.attrs["jid"] == "123@s.whatsapp.net"
    assert catalog.content[-1].tag == "after"

    create = product_create_node({"name": "Tea", "price": 1200, "currency": "INR", "is_hidden": False}, "tag-2")
    product = create.content[0].content[0]
    assert product.tag == "product"
    assert [child.tag for child in product.content] == ["name", "currency", "price", "is_hidden"]

    parsed = parse_catalog(
        BinaryNode(
            "iq",
            {},
            [
                BinaryNode(
                    "product_catalog",
                    {"after": "next"},
                    [
                        BinaryNode(
                            "product",
                            {},
                            [
                                BinaryNode("id", {}, b"p1"),
                                BinaryNode("name", {}, b"Tea"),
                                BinaryNode("price", {}, b"1200"),
                            ],
                        )
                    ],
                )
            ],
        )
    )
    assert parsed.next_cursor == "next"
    assert parsed.products[0].id == "p1"
    assert parsed.products[0].price == 1200

    delete = product_delete_node(["p1", "p2"], "tag-3")
    assert delete.content[0].tag == "product_catalog_delete"
    assert parse_product_delete(BinaryNode("iq", {}, [BinaryNode("product_catalog_delete", {"deleted_count": "2"})])) == 2


def test_wmex_and_newsletter_shapes_parse():
    node = wmex_query_node({"newsletter_id": "1@newsletter"}, QUERY_IDS["METADATA"], "m1")
    assert node.attrs["xmlns"] == "w:mex"
    variables = json.loads(node.content[0].content.decode("utf-8"))["variables"]
    assert variables["newsletter_id"] == "1@newsletter"

    result = BinaryNode("iq", {}, [BinaryNode("result", {}, json.dumps({"data": {"xwa2_newsletter": {"id": "1@newsletter", "name": "News"}}}).encode())])
    parsed = parse_wmex_result(result, "xwa2_newsletter")
    assert parsed["id"] == "1@newsletter"
    assert parse_newsletter_metadata(parsed).name == "News"

    metadata_node, path = newsletter_metadata_query("jid", "1@newsletter", "m2")
    assert path == "xwa2_newsletter"
    assert metadata_node.content[0].attrs["query_id"] == QUERY_IDS["METADATA"]

    fetch = newsletter_fetch_messages_node("1@newsletter", 10, since=5, after=6, tag_id="m3")
    assert fetch.attrs["xmlns"] == "newsletter"
    assert fetch.content[0].attrs == {"count": "10", "since": "5", "after": "6"}


def test_community_nodes_and_parser():
    node = community_create_node("Community", "Description", "c1")
    create = node.content[0]
    assert create.tag == "create"
    assert create.content[1].tag == "parent"

    metadata = community_metadata_node("123@g.us", "c2")
    assert metadata.content[0].attrs["request"] == "interactive"

    parsed = parse_community_metadata(
        BinaryNode(
            "iq",
            {},
            [
                BinaryNode(
                    "community",
                    {"id": "123", "subject": "Community", "size": "1"},
                    [BinaryNode("participant", {"jid": "a@lid", "phone_number": "a@s.whatsapp.net"})],
                )
            ],
        )
    )
    assert parsed.id == "123@g.us"
    assert parsed.participants[0].phone_number == "a@s.whatsapp.net"


def test_label_chat_modifications_build_app_state_patches():
    label = chat_modification_to_app_patch({"addLabel": {"id": "7", "name": "Follow up", "color": 3}}, "123@s.whatsapp.net")
    assert label.patch_type == "regular"
    assert label.index == ["label_edit", "7"]
    assert label.sync_action.labelEditAction.name == "Follow up"
    assert label.sync_action.labelEditAction.color == 3

    add_chat = chat_modification_to_app_patch({"addChatLabel": {"labelId": "7"}}, "123@s.whatsapp.net")
    assert add_chat.index == ["label_jid", "7", "123@s.whatsapp.net"]
    assert add_chat.sync_action.labelAssociationAction.labeled is True

    remove_message = chat_modification_to_app_patch(
        {"removeMessageLabel": {"labelId": "7", "messageId": "ABC"}},
        "123@s.whatsapp.net",
    )
    assert remove_message.index == ["label_message", "7", "123@s.whatsapp.net", "ABC", "0", "0"]
    assert remove_message.sync_action.labelAssociationAction.labeled is False


def test_phase7_client_methods_call_expected_queries(tmp_path):
    async def scenario():
        client = make_socket(_creds_with_app_state(tmp_path))
        queries = []
        sent = []

        async def fake_query(node, **kwargs):
            queries.append(node)
            if node.attrs.get("xmlns") == "w:mex":
                path = "xwa2_newsletter"
                return BinaryNode("iq", {}, [BinaryNode("result", {}, json.dumps({"data": {path: {"id": "n@newsletter"}}}).encode())])
            if node.tag == "call":
                return BinaryNode("call", node.attrs, [BinaryNode("link_create", {"token": "abc"})])
            if node.attrs.get("xmlns") == "w:biz:catalog" and node.content[0].tag == "product_catalog_delete":
                return BinaryNode("iq", {}, [BinaryNode("product_catalog_delete", {"deleted_count": "1"})])
            if node.attrs.get("xmlns") == "w:g2":
                return BinaryNode("iq", {}, [BinaryNode("group", {"id": "123", "subject": "Group"})])
            return BinaryNode("iq", {"type": "result"})

        async def fake_send(node):
            sent.append(node)

        client.query = fake_query  # type: ignore[method-assign]
        client.send_node = fake_send  # type: ignore[method-assign]

        await client.update_business_profile({"description": "hello"})
        assert await client.product_delete(["p1"]) == {"deleted": 1}
        assert (await client.newsletter_metadata("jid", "n@newsletter")).id == "n@newsletter"
        assert (await client.community_metadata("123@g.us")).id == "123@g.us"
        assert await client.create_call_link("audio") == "abc"
        await client.reject_call("call-1", "user@s.whatsapp.net")

        assert queries[0].content[0].tag == "business_profile"
        assert sent[0].tag == "call"
        assert client.newsletterMetadata.__func__ is client.newsletter_metadata.__func__
        assert client.communityMetadata.__func__ is client.community_metadata.__func__
        assert client.productDelete.__func__ is client.product_delete.__func__

    asyncio.run(scenario())
