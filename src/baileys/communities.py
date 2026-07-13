from __future__ import annotations

from .chat_groups import GroupMetadata, GroupParticipant, ParticipantUpdateResult, parse_group_metadata
from .message_send import generate_message_id
from .socket_nodes import find_child, node_content_bytes
from .wabinary import BinaryNode


def community_query_node(jid: str, query_type: str, content: list[BinaryNode], tag_id: str) -> BinaryNode:
    return BinaryNode("iq", {"id": tag_id, "type": query_type, "xmlns": "w:g2", "to": jid}, content)


def community_metadata_node(jid: str, tag_id: str) -> BinaryNode:
    return community_query_node(jid, "get", [BinaryNode("query", {"request": "interactive"})], tag_id)


def community_fetch_all_participating_node(tag_id: str) -> BinaryNode:
    return community_query_node(
        "@g.us",
        "get",
        [
            BinaryNode(
                "participating",
                {},
                [BinaryNode("participants", {}), BinaryNode("description", {})],
            )
        ],
        tag_id,
    )


def community_create_node(subject: str, description: str, tag_id: str) -> BinaryNode:
    desc_id = generate_message_id()[:12]
    return community_query_node(
        "@g.us",
        "set",
        [
            BinaryNode(
                "create",
                {"subject": subject},
                [
                    BinaryNode("description", {"id": desc_id}, [BinaryNode("body", {}, description.encode("utf-8"))]),
                    BinaryNode("parent", {"default_membership_approval_mode": "request_required"}),
                    BinaryNode("allow_non_admin_sub_group_creation", {}),
                    BinaryNode("create_general_chat", {}),
                ],
            )
        ],
        tag_id,
    )


def community_create_group_node(subject: str, participants: list[str], parent_community_jid: str, tag_id: str) -> BinaryNode:
    return community_query_node(
        "@g.us",
        "set",
        [
            BinaryNode(
                "create",
                {"subject": subject, "key": generate_message_id()},
                [*[BinaryNode("participant", {"jid": jid}) for jid in participants], BinaryNode("linked_parent", {"jid": parent_community_jid})],
            )
        ],
        tag_id,
    )


def community_leave_node(jid: str, tag_id: str) -> BinaryNode:
    return community_query_node("@g.us", "set", [BinaryNode("leave", {}, [BinaryNode("community", {"id": jid})])], tag_id)


def community_update_subject_node(jid: str, subject: str, tag_id: str) -> BinaryNode:
    return community_query_node(jid, "set", [BinaryNode("subject", {}, subject.encode("utf-8"))], tag_id)


def community_link_group_node(group_jid: str, parent_community_jid: str, tag_id: str) -> BinaryNode:
    return community_query_node(
        parent_community_jid,
        "set",
        [
            BinaryNode(
                "links",
                {},
                [
                    BinaryNode(
                        "link",
                        {"link_type": "sub_group"},
                        [BinaryNode("group", {"jid": group_jid})],
                    )
                ],
            )
        ],
        tag_id,
    )


def community_unlink_group_node(group_jid: str, parent_community_jid: str, tag_id: str) -> BinaryNode:
    return community_query_node(
        parent_community_jid,
        "set",
        [BinaryNode("unlink", {"unlink_type": "sub_group"}, [BinaryNode("group", {"jid": group_jid})])],
        tag_id,
    )


def community_linked_groups_node(jid: str, tag_id: str) -> BinaryNode:
    return community_query_node(jid, "get", [BinaryNode("sub_groups", {})], tag_id)


def community_membership_requests_node(jid: str, tag_id: str) -> BinaryNode:
    return community_query_node(jid, "get", [BinaryNode("membership_approval_requests", {})], tag_id)


def community_membership_requests_update_node(jid: str, participants: list[str], action: str, tag_id: str) -> BinaryNode:
    if action not in {"approve", "reject"}:
        raise ValueError(f"unsupported membership request action: {action}")
    return community_query_node(
        jid,
        "set",
        [
            BinaryNode(
                "membership_requests_action",
                {},
                [BinaryNode(action, {}, [BinaryNode("participant", {"jid": item}) for item in participants])],
            )
        ],
        tag_id,
    )


def community_update_description_node(jid: str, description: str | None, tag_id: str, *, previous_id: str | None = None) -> BinaryNode:
    attrs = {"id": generate_message_id()} if description else {"delete": "true"}
    if previous_id:
        attrs["prev"] = previous_id
    content = [BinaryNode("body", {}, description.encode("utf-8"))] if description else []
    return community_query_node(jid, "set", [BinaryNode("description", attrs, content)], tag_id)


def community_participants_update_node(jid: str, participants: list[str], action: str, tag_id: str) -> BinaryNode:
    attrs = {"linked_groups": "true"} if action == "remove" else {}
    return community_query_node(jid, "set", [BinaryNode(action, attrs, [BinaryNode("participant", {"jid": item}) for item in participants])], tag_id)


def community_invite_code_node(jid: str, tag_id: str) -> BinaryNode:
    return community_query_node(jid, "get", [BinaryNode("invite", {})], tag_id)


def community_revoke_invite_node(jid: str, tag_id: str) -> BinaryNode:
    return community_query_node(jid, "set", [BinaryNode("invite", {})], tag_id)


def community_accept_invite_node(code: str, tag_id: str) -> BinaryNode:
    return community_query_node("@g.us", "set", [BinaryNode("invite", {"code": code})], tag_id)


def community_invite_info_node(code: str, tag_id: str) -> BinaryNode:
    return community_query_node("@g.us", "get", [BinaryNode("invite", {"code": code})], tag_id)


def community_revoke_invite_v4_node(jid: str, invited_jid: str, tag_id: str) -> BinaryNode:
    return community_query_node(jid, "set", [BinaryNode("revoke", {}, [BinaryNode("participant", {"jid": invited_jid})])], tag_id)


def community_accept_invite_v4_node(jid: str, code: str, expiration: int | str, admin_jid: str, tag_id: str) -> BinaryNode:
    return community_query_node(jid, "set", [BinaryNode("accept", {"code": code, "expiration": str(expiration), "admin": admin_jid})], tag_id)


def community_ephemeral_node(jid: str, expiration: int, tag_id: str) -> BinaryNode:
    child = BinaryNode("ephemeral", {"expiration": str(expiration)}) if expiration else BinaryNode("not_ephemeral", {})
    return community_query_node(jid, "set", [child], tag_id)


def community_setting_update_node(jid: str, setting: str, tag_id: str) -> BinaryNode:
    if setting not in {"announcement", "not_announcement", "locked", "unlocked"}:
        raise ValueError(f"unsupported community setting: {setting}")
    return community_query_node(jid, "set", [BinaryNode(setting, {})], tag_id)


def community_member_add_mode_node(jid: str, mode: str, tag_id: str) -> BinaryNode:
    if mode not in {"admin_add", "all_member_add"}:
        raise ValueError(f"unsupported community member add mode: {mode}")
    return community_query_node(jid, "set", [BinaryNode("member_add_mode", {}, mode.encode("utf-8"))], tag_id)


def community_join_approval_mode_node(jid: str, mode: str, tag_id: str) -> BinaryNode:
    if mode not in {"on", "off"}:
        raise ValueError(f"unsupported community join approval mode: {mode}")
    return community_query_node(jid, "set", [BinaryNode("membership_approval_mode", {}, [BinaryNode("community_join", {"state": mode})])], tag_id)


def parse_community_metadata(node: BinaryNode) -> GroupMetadata:
    community = find_child(node, "community")
    if community is None:
        return parse_group_metadata(node)
    group = BinaryNode("group", community.attrs, community.content)
    return parse_group_metadata(BinaryNode("iq", node.attrs, [group]))


def parse_community_participating(node: BinaryNode) -> dict[str, GroupMetadata]:
    communities = find_child(node, "communities")
    if communities is None or not isinstance(communities.content, list):
        return {}
    results: dict[str, GroupMetadata] = {}
    for child in communities.content:
        if child.tag != "community":
            continue
        metadata = parse_community_metadata(BinaryNode("iq", node.attrs, [child]))
        results[metadata.id] = metadata
    return results


def parse_community_participant_update(node: BinaryNode, action: str) -> list[ParticipantUpdateResult]:
    action_node = find_child(node, action)
    if action_node is None:
        return []
    results = []
    if isinstance(action_node.content, list):
        for child in action_node.content:
            if child.tag == "participant" and child.attrs.get("jid"):
                results.append(ParticipantUpdateResult(jid=child.attrs["jid"], status=child.attrs.get("error") or "200", content=child))
    return results


def parse_community_invite_code(node: BinaryNode) -> str | None:
    invite = find_child(node, "invite")
    return invite.attrs.get("code") if invite is not None else None


def parse_community_accept_invite(node: BinaryNode) -> str | None:
    community = find_child(node, "community")
    if community is None:
        return node.attrs.get("from")
    return community.attrs.get("jid") or community.attrs.get("id")


def parse_community_linked_groups(node: BinaryNode) -> list[dict[str, object]]:
    sub_groups = find_child(node, "sub_groups")
    if sub_groups is None or not isinstance(sub_groups.content, list):
        return []
    groups: list[dict[str, object]] = []
    for child in sub_groups.content:
        if child.tag != "group":
            continue
        raw_id = child.attrs.get("id")
        groups.append(
            {
                "id": f"{raw_id}@g.us" if raw_id and "@" not in raw_id else raw_id,
                "subject": child.attrs.get("subject") or "",
                "creation": _optional_int(child.attrs.get("creation")),
                "owner": child.attrs.get("creator"),
                "size": _optional_int(child.attrs.get("size")),
                "raw": child,
            }
        )
    return groups


def parse_membership_requests(node: BinaryNode) -> list[dict[str, str]]:
    requests = find_child(node, "membership_approval_requests")
    if requests is None or not isinstance(requests.content, list):
        return []
    return [child.attrs for child in requests.content if child.tag == "membership_approval_request"]


def parse_membership_request_update(node: BinaryNode, action: str) -> list[ParticipantUpdateResult]:
    wrapper = find_child(node, "membership_requests_action")
    action_node = find_child(wrapper, action) if wrapper is not None else None
    if action_node is None or not isinstance(action_node.content, list):
        return []
    return [
        ParticipantUpdateResult(jid=child.attrs["jid"], status=child.attrs.get("error") or "200", content=child)
        for child in action_node.content
        if child.tag == "participant" and child.attrs.get("jid")
    ]


def binary_text(node: BinaryNode | None) -> str | None:
    content = node_content_bytes(node)
    return content.decode("utf-8", errors="replace") if content is not None else None


def _optional_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None
