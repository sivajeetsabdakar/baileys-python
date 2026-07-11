from __future__ import annotations

import asyncio
import base64
import json

import baileys as b
from baileys.auth_state import AuthState, JsonCredentialStore
from baileys.business import (
    catalog_node,
    cover_photo_remove_node,
    cover_photo_update_node,
    parse_catalog,
    parse_product,
    parse_product_delete,
    product_create_node,
    product_delete_node,
)
from baileys.communities import (
    community_accept_invite_node,
    community_ephemeral_node,
    community_link_group_node,
    community_membership_requests_update_node,
    community_metadata_node,
    community_create_node,
    parse_community_linked_groups,
    parse_community_metadata,
    parse_membership_request_update,
)
from baileys.app_state import chat_modification_to_app_patch
from baileys.mex import QUERY_IDS, parse_wmex_result, wmex_query_node
from baileys.media import MediaConn, MediaHost, MediaUploadResult
from baileys.newsletter import (
    newsletter_fetch_messages_node,
    newsletter_metadata_query,
    parse_newsletter_metadata,
    parse_newsletter_notification_events,
)
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

    create = product_create_node(
        {
            "name": "Tea",
            "price": 1200,
            "currency": "INR",
            "is_hidden": False,
            "images": [{"url": "https://mmg.whatsapp.net/product/image/abc"}],
            "origin_country_code": None,
        },
        "tag-2",
    )
    product = create.content[0].content[0]
    assert product.tag == "product"
    assert product.attrs == {"compliance_category": "COUNTRY_ORIGIN_EXEMPT", "is_hidden": "false"}
    assert [child.tag for child in product.content] == ["name", "currency", "price", "media"]
    assert product.content[-1].content[0].content[0].content == b"https://mmg.whatsapp.net/product/image/abc"

    edit = product_create_node({"name": "Tea", "retailerId": "sku-1", "originCountryCode": "IN"}, "tag-2b")
    edit_product = edit.content[0].content[0]
    assert [child.tag for child in edit_product.content] == ["name", "retailer_id", "compliance_info"]

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
                                BinaryNode("retailer_id", {}, b"sku-1"),
                                BinaryNode("url", {}, b"https://example.test/item"),
                                BinaryNode(
                                    "media",
                                    {},
                                    [
                                        BinaryNode(
                                            "image",
                                            {},
                                            [
                                                BinaryNode("request_image_url", {}, b"https://mmg.whatsapp.net/requested"),
                                                BinaryNode("original_image_url", {}, b"https://mmg.whatsapp.net/original"),
                                            ],
                                        )
                                    ],
                                ),
                                BinaryNode("status_info", {}, [BinaryNode("status", {}, b"APPROVED")]),
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
    assert parsed.products[0].retailer_id == "sku-1"
    assert parsed.products[0].url == "https://example.test/item"
    assert parsed.products[0].image_urls == {
        "requested": "https://mmg.whatsapp.net/requested",
        "original": "https://mmg.whatsapp.net/original",
    }
    assert parsed.products[0].review_status == {"whatsapp": "APPROVED"}

    delete = product_delete_node(["p1", "p2"], "tag-3")
    assert delete.content[0].tag == "product_catalog_delete"
    assert parse_product_delete(BinaryNode("iq", {}, [BinaryNode("product_catalog_delete", {"deleted_count": "2"})])) == 2

    cover = cover_photo_update_node("fb1", "tok", 123, "tag-4")
    assert cover.content[0].content[0].attrs == {"id": "fb1", "op": "update", "token": "tok", "ts": "123"}
    remove_cover = cover_photo_remove_node("fb1", "tag-5")
    assert remove_cover.content[0].content[0].attrs == {"op": "delete", "id": "fb1"}


def test_parse_product_handles_hidden_attrs_and_uploaded_image_urls():
    product = parse_product(
        BinaryNode(
            "product",
            {"id": "p2", "name": "Coffee", "is_hidden": "true"},
            [BinaryNode("media", {}, [BinaryNode("image", {}, [BinaryNode("url", {}, b"https://mmg.whatsapp.net/product")])])],
        )
    )
    assert product.id == "p2"
    assert product.hidden is True
    assert product.image_urls == {"url": "https://mmg.whatsapp.net/product"}


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

    events = parse_newsletter_notification_events(
        BinaryNode(
            "notification",
            {"from": "1@newsletter", "participant": "admin@s.whatsapp.net", "type": "newsletter"},
            [
                BinaryNode("reaction", {"message_id": "77"}, [BinaryNode("reaction", {}, b"+1")]),
                BinaryNode("view", {"message_id": "78"}, b"12"),
                BinaryNode("participant", {"jid": "user@s.whatsapp.net", "action": "promote", "role": "ADMIN"}),
                BinaryNode(
                    "update",
                    {},
                    [BinaryNode("settings", {}, [BinaryNode("name", {}, b"News"), BinaryNode("description", {}, b"Updates")])],
                ),
            ],
        )
    )
    assert [event for event, _ in events] == [
        "newsletter.reaction",
        "newsletter.view",
        "newsletter-participants.update",
        "newsletter-settings.update",
    ]
    assert events[0][1].reaction == {"count": 1, "code": "+1"}
    assert events[1][1].count == 12
    assert events[2][1].new_role == "ADMIN"
    assert events[3][1].update == {"name": "News", "description": "Updates"}

    mex_events = parse_newsletter_notification_events(
        BinaryNode(
            "notification",
            {"type": "mex", "from": "server@s.whatsapp.net"},
            [
                BinaryNode(
                    "mex",
                    {},
                    json.dumps(
                        {
                            "operation": "NotificationNewsletterAdminPromote",
                            "updates": [{"jid": "1@newsletter", "user": "user@s.whatsapp.net"}],
                        }
                    ).encode(),
                )
            ],
        )
    )
    assert mex_events[0][0] == "newsletter-participants.update"
    assert mex_events[0][1].action == "promote"


def test_client_dispatch_emits_newsletter_events(tmp_path):
    async def scenario():
        client = make_socket(_creds_with_app_state(tmp_path))
        reactions = []
        views = []
        participants = []
        settings = []
        client.ev.on("newsletter.reaction", lambda payload: reactions.append(payload))
        client.ev.on("newsletter.view", lambda payload: views.append(payload))
        client.ev.on("newsletter-participants.update", lambda payload: participants.append(payload))
        client.ev.on("newsletter-settings.update", lambda payload: settings.append(payload))

        info = await client.dispatch_notification_node(
            BinaryNode(
                "notification",
                {"id": "n1", "from": "1@newsletter", "participant": "admin@s.whatsapp.net", "type": "newsletter"},
                [
                    BinaryNode("reaction", {"message_id": "77"}, [BinaryNode("reaction", {}, b"+1")]),
                    BinaryNode("view", {"message_id": "78"}, b"3"),
                    BinaryNode("participant", {"jid": "user@s.whatsapp.net", "action": "promote", "role": "ADMIN"}),
                    BinaryNode("update", {}, [BinaryNode("settings", {}, [BinaryNode("name", {}, b"News")])]),
                ],
            )
        )

        assert info.category == "newsletter"
        assert reactions[0].server_id == "77"
        assert views[0].count == 3
        assert participants[0].user == "user@s.whatsapp.net"
        assert settings[0].update == {"name": "News"}

    asyncio.run(scenario())


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

    link = community_link_group_node("456@g.us", "123@g.us", "c3")
    assert link.content[0].tag == "links"
    assert link.content[0].content[0].content[0].attrs["jid"] == "456@g.us"

    accept = community_accept_invite_node("invite-code", "c4")
    assert accept.content[0].attrs["code"] == "invite-code"

    ephemeral = community_ephemeral_node("123@g.us", 60, "c5")
    assert ephemeral.content[0].tag == "ephemeral"
    not_ephemeral = community_ephemeral_node("123@g.us", 0, "c6")
    assert not_ephemeral.content[0].tag == "not_ephemeral"

    update = community_membership_requests_update_node("123@g.us", ["a@s.whatsapp.net"], "approve", "c7")
    assert update.content[0].content[0].tag == "approve"
    results = parse_membership_request_update(
        BinaryNode(
            "iq",
            {},
            [
                BinaryNode(
                    "membership_requests_action",
                    {},
                    [BinaryNode("approve", {}, [BinaryNode("participant", {"jid": "a@s.whatsapp.net"})])],
                )
            ],
        ),
        "approve",
    )
    assert results[0].status == "200"

    linked = parse_community_linked_groups(BinaryNode("iq", {}, [BinaryNode("sub_groups", {}, [BinaryNode("group", {"id": "456", "subject": "Child", "size": "2"})])]))
    assert linked[0]["id"] == "456@g.us"
    assert linked[0]["size"] == 2


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


def test_phase7_client_methods_call_expected_queries(tmp_path, monkeypatch):
    async def scenario():
        client = make_socket(_creds_with_app_state(tmp_path))
        queries = []
        sent = []
        media_requests = []

        async def fake_query(node, **kwargs):
            queries.append(node)
            if node.attrs.get("xmlns") == "w:mex":
                path = "xwa2_newsletter"
                return BinaryNode("iq", {}, [BinaryNode("result", {}, json.dumps({"data": {path: {"id": "n@newsletter"}}}).encode())])
            if node.attrs.get("xmlns") == "w:biz:catalog" and node.content[0].tag == "product_catalog_add":
                return BinaryNode("iq", {}, [node.content[0]])
            if node.tag == "call":
                return BinaryNode("call", node.attrs, [BinaryNode("link_create", {"token": "abc"})])
            if node.attrs.get("xmlns") == "w:biz:catalog" and node.content[0].tag == "product_catalog_delete":
                return BinaryNode("iq", {}, [BinaryNode("product_catalog_delete", {"deleted_count": "1"})])
            if node.attrs.get("xmlns") == "w:g2":
                return BinaryNode("iq", {}, [BinaryNode("group", {"id": "123", "subject": "Group"})])
            return BinaryNode("iq", {"type": "result"})

        async def fake_send(node):
            sent.append(node)

        async def fake_media_conn(**kwargs):
            return MediaConn(auth="auth", ttl=3600, hosts=[MediaHost(hostname="mmg.whatsapp.net")])

        async def fake_upload_raw_media(data, media_conn, file_sha256, media_type, **kwargs):
            media_requests.append((data, media_type, media_conn.hosts[0].hostname))
            return MediaUploadResult(host="mmg.whatsapp.net", direct_path="/product/image/uploaded")

        client.query = fake_query  # type: ignore[method-assign]
        client.send_node = fake_send  # type: ignore[method-assign]
        client._get_media_conn = fake_media_conn  # type: ignore[method-assign]
        monkeypatch.setattr("baileys.socket.upload_raw_media", fake_upload_raw_media)

        await client.update_business_profile({"description": "hello"})
        created = await client.product_create({"name": "Tea", "images": [b"image-bytes"]})
        assert created.image_urls == {"url": "https://mmg.whatsapp.net/product/image/uploaded"}
        assert media_requests == [(b"image-bytes", "product-catalog-image", "mmg.whatsapp.net")]
        assert await client.product_delete(["p1"]) == {"deleted": 1}
        assert (await client.newsletter_metadata("jid", "n@newsletter")).id == "n@newsletter"
        assert (await client.community_metadata("123@g.us")).id == "123@g.us"
        assert await client.create_call_link("audio") == "abc"
        await client.send_wam_buffer(b"WAM\x05")
        await client.reject_call("call-1", "user@s.whatsapp.net")

        assert queries[0].content[0].tag == "business_profile"
        assert any(node.attrs.get("xmlns") == "w:stats" for node in queries)
        assert any(
            node.attrs.get("xmlns") == "w:biz:catalog"
            and node.content[0].tag == "product_catalog_add"
            and node.content[0].content[0].content[-1].tag == "media"
            for node in queries
        )
        assert sent[0].tag == "call"
        assert client.newsletterMetadata.__func__ is client.newsletter_metadata.__func__
        assert client.communityMetadata.__func__ is client.community_metadata.__func__
        assert client.communityAcceptInvite.__func__ is client.community_accept_invite.__func__
        assert client.newsletterUpdatePicture.__func__ is client.newsletter_update_picture.__func__
        assert client.productDelete.__func__ is client.product_delete.__func__

    asyncio.run(scenario())
