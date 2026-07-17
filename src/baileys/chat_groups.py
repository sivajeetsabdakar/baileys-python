from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .defaults import GROUP_SERVER, S_WHATSAPP_NET
from .jid import jid_normalized_user
from .message_send import generate_message_id
from .socket_nodes import find_child, node_content_bytes
from .wabinary import BinaryNode


@dataclass(frozen=True)
class GroupParticipant:
    jid: str
    admin: str | None = None
    phone_number: str | None = None


@dataclass(frozen=True)
class GroupMetadata:
    id: str
    subject: str | None = None
    owner: str | None = None
    desc: str | None = None
    desc_id: str | None = None
    size: int | None = None
    addressing_mode: str | None = None
    participants: list[GroupParticipant] = field(default_factory=list)


@dataclass(frozen=True)
class ParticipantUpdateResult:
    jid: str
    status: str
    content: BinaryNode | None = None


def group_query_node(jid: str, query_type: str, content: list[BinaryNode], tag_id: str) -> BinaryNode:
    return BinaryNode("iq", {"id": tag_id, "type": query_type, "xmlns": "w:g2", "to": jid}, content)


def group_metadata_node(jid: str, tag_id: str) -> BinaryNode:
    return group_query_node(jid, "get", [BinaryNode("query", {"request": "interactive"})], tag_id)


def group_fetch_all_participating_node(tag_id: str) -> BinaryNode:
    return group_query_node(
        f"@{GROUP_SERVER}",
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


def group_create_node(subject: str, participants: Iterable[str], tag_id: str) -> BinaryNode:
    return group_query_node(
        f"@{GROUP_SERVER}",
        "set",
        [
            BinaryNode(
                "create",
                {"subject": subject, "key": generate_message_id()},
                [BinaryNode("participant", {"jid": jid}) for jid in participants],
            )
        ],
        tag_id,
    )


def group_leave_node(jid: str, tag_id: str) -> BinaryNode:
    return group_query_node(f"@{GROUP_SERVER}", "set", [BinaryNode("leave", {}, [BinaryNode("group", {"id": jid})])], tag_id)


def group_update_subject_node(jid: str, subject: str, tag_id: str) -> BinaryNode:
    return group_query_node(jid, "set", [BinaryNode("subject", {}, subject.encode("utf-8"))], tag_id)


def group_update_description_node(jid: str, description: str | None, tag_id: str, *, previous_id: str | None = None) -> BinaryNode:
    attrs = {"id": generate_message_id()} if description else {"delete": "true"}
    if previous_id:
        attrs["prev"] = previous_id
    content = [BinaryNode("body", {}, description.encode("utf-8"))] if description else []
    return group_query_node(jid, "set", [BinaryNode("description", attrs, content)], tag_id)


def group_participants_update_node(jid: str, participants: Iterable[str], action: str, tag_id: str) -> BinaryNode:
    if action not in {"add", "remove", "promote", "demote"}:
        raise ValueError(f"unsupported participant action: {action}")
    return group_query_node(
        jid,
        "set",
        [BinaryNode(action, {}, [BinaryNode("participant", {"jid": participant}) for participant in participants])],
        tag_id,
    )


def group_membership_requests_node(jid: str, tag_id: str) -> BinaryNode:
    return group_query_node(jid, "get", [BinaryNode("membership_approval_requests", {})], tag_id)


def group_membership_requests_update_node(jid: str, participants: Iterable[str], action: str, tag_id: str) -> BinaryNode:
    if action not in {"approve", "reject"}:
        raise ValueError(f"unsupported membership request action: {action}")
    return group_query_node(
        jid,
        "set",
        [
            BinaryNode(
                "membership_requests_action",
                {},
                [BinaryNode(action, {}, [BinaryNode("participant", {"jid": participant}) for participant in participants])],
            )
        ],
        tag_id,
    )


def group_invite_code_node(jid: str, tag_id: str) -> BinaryNode:
    return group_query_node(jid, "get", [BinaryNode("invite", {})], tag_id)


def group_revoke_invite_node(jid: str, tag_id: str) -> BinaryNode:
    return group_query_node(jid, "set", [BinaryNode("invite", {})], tag_id)


def group_accept_invite_node(code: str, tag_id: str) -> BinaryNode:
    return group_query_node(f"@{GROUP_SERVER}", "set", [BinaryNode("invite", {"code": code})], tag_id)


def group_get_invite_info_node(code: str, tag_id: str) -> BinaryNode:
    return group_query_node(f"@{GROUP_SERVER}", "get", [BinaryNode("invite", {"code": code})], tag_id)


def group_setting_update_node(jid: str, setting: str, value: str, tag_id: str) -> BinaryNode:
    if setting not in {"announcement", "not_announcement", "locked", "unlocked", "ephemeral"}:
        raise ValueError(f"unsupported group setting: {setting}")
    attrs = {"expiration": value} if setting == "ephemeral" else {}
    tag = "ephemeral" if setting == "ephemeral" else setting
    return group_query_node(jid, "set", [BinaryNode(tag, attrs)], tag_id)


def group_toggle_ephemeral_node(jid: str, ephemeral_expiration: int, tag_id: str) -> BinaryNode:
    content = (
        BinaryNode("ephemeral", {"expiration": str(ephemeral_expiration)})
        if ephemeral_expiration
        else BinaryNode("not_ephemeral", {})
    )
    return group_query_node(jid, "set", [content], tag_id)


def group_member_add_mode_node(jid: str, mode: str, tag_id: str) -> BinaryNode:
    if mode not in {"admin_add", "all_member_add"}:
        raise ValueError(f"unsupported group member add mode: {mode}")
    return group_query_node(jid, "set", [BinaryNode("member_add_mode", {}, mode.encode("utf-8"))], tag_id)


def group_join_approval_mode_node(jid: str, mode: str, tag_id: str) -> BinaryNode:
    if mode not in {"on", "off"}:
        raise ValueError(f"unsupported group join approval mode: {mode}")
    return group_query_node(
        jid,
        "set",
        [BinaryNode("membership_approval_mode", {}, [BinaryNode("group_join", {"state": mode})])],
        tag_id,
    )


def parse_group_metadata(node: BinaryNode) -> GroupMetadata:
    group = find_child(node, "group")
    if group is None and node.tag == "group":
        group = node
    if group is None:
        raise ValueError(f"group metadata response missing group child: {node!r}")
    participants: list[GroupParticipant] = []
    desc = None
    desc_id = None
    if isinstance(group.content, list):
        for child in group.content:
            if child.tag == "participant" and child.attrs.get("jid"):
                participants.append(
                    GroupParticipant(
                        jid=child.attrs["jid"],
                        admin=child.attrs.get("type"),
                        phone_number=child.attrs.get("phone_number"),
                    )
                )
            elif child.tag == "description":
                desc_id = child.attrs.get("id")
                body = find_child(child, "body")
                if isinstance(body.content if body else None, bytes):
                    desc = body.content.decode("utf-8", errors="replace")
    group_id = group.attrs.get("jid") or group.attrs.get("id") or ""
    if group_id and "@" not in group_id:
        group_id = f"{group_id}@{GROUP_SERVER}"
    return GroupMetadata(
        id=group_id,
        subject=group.attrs.get("subject"),
        owner=group.attrs.get("creator") or group.attrs.get("owner"),
        desc=desc,
        desc_id=desc_id,
        size=int(group.attrs["size"]) if group.attrs.get("size") else len(participants) or None,
        addressing_mode=group.attrs.get("addressing_mode"),
        participants=participants,
    )


def parse_group_participating(node: BinaryNode) -> dict[str, GroupMetadata]:
    groups_node = find_child(node, "groups")
    if groups_node is None or not isinstance(groups_node.content, list):
        return {}
    groups: dict[str, GroupMetadata] = {}
    for child in groups_node.content:
        if child.tag != "group":
            continue
        metadata = parse_group_metadata(BinaryNode("iq", node.attrs, [child]))
        groups[metadata.id] = metadata
    return groups


def parse_participant_update(node: BinaryNode, action: str) -> list[ParticipantUpdateResult]:
    action_node = find_child(node, action)
    if action_node is None:
        return []
    results = []
    if isinstance(action_node.content, list):
        for child in action_node.content:
            if child.tag == "participant" and child.attrs.get("jid"):
                results.append(ParticipantUpdateResult(jid=child.attrs["jid"], status=child.attrs.get("error") or "200", content=child))
    return results


def parse_invite_code(node: BinaryNode) -> str | None:
    invite = find_child(node, "invite")
    return invite.attrs.get("code") if invite is not None else None


def parse_accept_invite(node: BinaryNode) -> str | None:
    group = find_child(node, "group")
    return group.attrs.get("jid") if group is not None else None


def privacy_fetch_node(tag_id: str) -> BinaryNode:
    return BinaryNode("iq", {"id": tag_id, "xmlns": "privacy", "to": S_WHATSAPP_NET, "type": "get"}, [BinaryNode("privacy", {})])


def privacy_update_node(name: str, value: str, tag_id: str) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"id": tag_id, "xmlns": "privacy", "to": S_WHATSAPP_NET, "type": "set"},
        [BinaryNode("privacy", {}, [BinaryNode("category", {"name": name, "value": value})])],
    )


def parse_privacy_settings(node: BinaryNode) -> dict[str, str]:
    privacy = find_child(node, "privacy")
    if privacy is None or not isinstance(privacy.content, list):
        return {}
    return {
        child.attrs["name"]: child.attrs.get("value", "")
        for child in privacy.content
        if child.tag == "category" and child.attrs.get("name")
    }


def blocklist_fetch_node(tag_id: str) -> BinaryNode:
    return BinaryNode("iq", {"id": tag_id, "xmlns": "blocklist", "to": S_WHATSAPP_NET, "type": "get"})


def block_status_node(jid: str, action: str, tag_id: str, *, pn_jid: str | None = None) -> BinaryNode:
    if action not in {"block", "unblock"}:
        raise ValueError(f"unsupported block action: {action}")
    attrs = {"action": action, "jid": jid_normalized_user(jid)}
    if action == "block":
        if pn_jid is None:
            raise ValueError("pn_jid is required when blocking a contact")
        attrs["pn_jid"] = jid_normalized_user(pn_jid)
    return BinaryNode(
        "iq",
        {"id": tag_id, "xmlns": "blocklist", "to": S_WHATSAPP_NET, "type": "set"},
        [BinaryNode("item", attrs)],
    )


def parse_blocklist(node: BinaryNode) -> list[str]:
    list_node = find_child(node, "list")
    if list_node is None or not isinstance(list_node.content, list):
        return []
    return [child.attrs["jid"] for child in list_node.content if child.tag == "item" and child.attrs.get("jid")]


def profile_picture_query_content(picture_type: str = "preview", tc_token_content: list[BinaryNode] | None = None) -> list[BinaryNode]:
    picture = BinaryNode("picture", {"type": picture_type, "query": "url"})
    if tc_token_content:
        picture.content = tc_token_content
    return [picture]


def profile_picture_url_node(
    jid: str,
    tag_id: str,
    picture_type: str = "preview",
    tc_token_content: list[BinaryNode] | None = None,
) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"id": tag_id, "target": jid_normalized_user(jid), "to": S_WHATSAPP_NET, "type": "get", "xmlns": "w:profile:picture"},
        profile_picture_query_content(picture_type, tc_token_content),
    )


def parse_profile_picture_url(node: BinaryNode) -> str | None:
    picture = find_child(node, "picture")
    return picture.attrs.get("url") if picture is not None else None


def profile_status_update_node(status: str, tag_id: str) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "set", "xmlns": "status"},
        [BinaryNode("status", {}, status.encode("utf-8"))],
    )


def profile_picture_update_node(jid: str, data: bytes, tag_id: str, *, own_jid: str | None = None) -> BinaryNode:
    attrs = {"id": tag_id, "to": S_WHATSAPP_NET, "type": "set", "xmlns": "w:profile:picture"}
    if own_jid is None or jid_normalized_user(jid) != jid_normalized_user(own_jid):
        attrs["target"] = jid_normalized_user(jid)
    return BinaryNode("iq", attrs, [BinaryNode("picture", {"type": "image"}, data)])


def profile_picture_remove_node(jid: str, tag_id: str, *, own_jid: str | None = None) -> BinaryNode:
    attrs = {"id": tag_id, "to": S_WHATSAPP_NET, "type": "set", "xmlns": "w:profile:picture"}
    if own_jid is None or jid_normalized_user(jid) != jid_normalized_user(own_jid):
        attrs["target"] = jid_normalized_user(jid)
    return BinaryNode("iq", attrs)


def on_whatsapp_node(jids: Iterable[str], tag_id: str) -> BinaryNode:
    users = []
    for jid in jids:
        phone = jid.replace("+", "").split("@", 1)[0].split(":", 1)[0]
        users.append(
            BinaryNode("user", {}, [BinaryNode("contact", {}, f"+{phone}".encode("utf-8"))]),
        )
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "get", "xmlns": "usync"},
        [
            BinaryNode(
                "usync",
                {"context": "interactive", "mode": "query", "sid": tag_id, "last": "true", "index": "0"},
                [BinaryNode("query", {}, [BinaryNode("contact", {})]), BinaryNode("list", {}, users)],
            )
        ],
    )


def parse_on_whatsapp(node: BinaryNode) -> list[dict[str, Any]]:
    usync = find_child(node, "usync")
    list_node = find_child(usync, "list")
    if list_node is None or not isinstance(list_node.content, list):
        return []
    results = []
    for user in list_node.content:
        contact = find_child(user, "contact")
        if not (user.attrs.get("jid") or user.attrs.get("id")) or contact is None:
            continue
        contact_exists = (
            contact.attrs.get("type") == "in"
            or contact.attrs.get("value") == "true"
            or contact.attrs.get("value") == "1"
        )
        results.append(
            {
                "jid": user.attrs.get("jid") or user.attrs.get("id") or "",
                "exists": contact_exists,
            }
        )
    return results


def usync_status_node(jids: Iterable[str], tag_id: str) -> BinaryNode:
    return _usync_protocol_node(jids, tag_id, "status")


def usync_disappearing_mode_node(jids: Iterable[str], tag_id: str) -> BinaryNode:
    return _usync_protocol_node(jids, tag_id, "disappearing_mode")


def _usync_protocol_node(jids: Iterable[str], tag_id: str, protocol: str) -> BinaryNode:
    users = [BinaryNode("user", {"jid": jid_normalized_user(jid)}, []) for jid in jids]
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "get", "xmlns": "usync"},
        [
            BinaryNode(
                "usync",
                {"context": "interactive", "mode": "query", "sid": tag_id, "last": "true", "index": "0"},
                [BinaryNode("query", {}, [BinaryNode(protocol, {})]), BinaryNode("list", {}, users)],
            )
        ],
    )


def parse_usync_status(node: BinaryNode) -> list[dict[str, Any]]:
    results = []
    for user, status in _parse_usync_child(node, "status"):
        content = node_content_bytes(status)
        value = content.decode("utf-8", errors="replace") if content else None
        if value is None and status.attrs.get("code") == "401":
            value = ""
        elif value == "":
            value = None
        results.append(
            {
                "jid": user.attrs.get("jid") or user.attrs.get("id") or "",
                "status": value,
                "set_at": int(status.attrs.get("t") or 0),
                "raw": status,
            }
        )
    return results


def parse_usync_disappearing_mode(node: BinaryNode) -> list[dict[str, Any]]:
    results = []
    for user, disappearing in _parse_usync_child(node, "disappearing_mode"):
        results.append(
            {
                "jid": user.attrs.get("jid") or user.attrs.get("id") or "",
                "duration": int(disappearing.attrs.get("duration") or 0),
                "set_at": int(disappearing.attrs.get("t") or 0),
                "raw": disappearing,
            }
        )
    return results


def _parse_usync_child(node: BinaryNode, tag: str) -> list[tuple[BinaryNode, BinaryNode]]:
    usync = find_child(node, "usync")
    list_node = find_child(usync, "list")
    if list_node is None or not isinstance(list_node.content, list):
        return []
    results = []
    for user in list_node.content:
        if user.tag != "user":
            continue
        child = find_child(user, tag)
        if child is not None:
            results.append((user, child))
    return results


def available_presence_node(name: str, presence_type: str) -> BinaryNode:
    if presence_type not in {"available", "unavailable"}:
        raise ValueError(f"unsupported availability presence: {presence_type}")
    return BinaryNode("presence", {"name": name.replace("@", ""), "type": presence_type})


def chatstate_presence_node(from_jid: str, to_jid: str, presence_type: str) -> BinaryNode:
    if presence_type not in {"composing", "paused", "recording"}:
        raise ValueError(f"unsupported chatstate presence: {presence_type}")
    tag = "composing" if presence_type == "recording" else presence_type
    attrs = {"media": "audio"} if presence_type == "recording" else {}
    return BinaryNode("chatstate", {"from": from_jid, "to": to_jid}, [BinaryNode(tag, attrs)])


def presence_subscribe_node(jid: str, tag_id: str) -> BinaryNode:
    return BinaryNode("presence", {"to": jid_normalized_user(jid), "id": tag_id, "type": "subscribe"})


def default_disappearing_mode_node(duration: int, tag_id: str) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"id": tag_id, "xmlns": "disappearing_mode", "to": S_WHATSAPP_NET, "type": "set"},
        [BinaryNode("disappearing_mode", {"duration": str(duration)})],
    )


def dirty_clean_node(kind: str, tag_id: str, *, from_timestamp: int | None = None) -> BinaryNode:
    attrs = {"type": kind}
    if from_timestamp is not None:
        attrs["timestamp"] = str(from_timestamp)
    return BinaryNode(
        "iq",
        {"id": tag_id, "xmlns": "urn:xmpp:whatsapp:dirty", "to": S_WHATSAPP_NET, "type": "set"},
        [BinaryNode("clean", attrs)],
    )


def chat_modify_node(modification: dict[str, Any], jid: str, tag_id: str) -> BinaryNode:
    patch = dict(modification)
    patch.setdefault("jid", jid)
    patch.setdefault("timestamp", int(time.time()))
    return BinaryNode(
        "iq",
        {"id": tag_id, "type": "set", "xmlns": "w:sync:app:state", "to": S_WHATSAPP_NET},
        [BinaryNode("collection", {"name": "regular_high"}, [BinaryNode("mutation", patch)])],
    )
