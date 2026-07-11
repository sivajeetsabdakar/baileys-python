from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable

from baileys.defaults import S_WHATSAPP_NET
from baileys.jid import JidParts, jid_decode, jid_encode, jid_normalized_user
from baileys.socket_nodes import find_child, node_content_bytes
from baileys.wabinary import BinaryNode


@dataclass(frozen=True)
class DeviceInfo:
    user: str
    server: str
    device: int
    jid: str
    key_index: int | None = None
    is_hosted: bool = False


@dataclass(frozen=True)
class USyncContact:
    jid: str
    exists: bool
    raw: BinaryNode | None = None


@dataclass(frozen=True)
class USyncStatus:
    jid: str
    status: str | None
    set_at: int
    raw: BinaryNode | None = None


@dataclass(frozen=True)
class USyncDisappearingMode:
    jid: str
    duration: int
    set_at: int
    raw: BinaryNode | None = None


@dataclass(frozen=True)
class USyncUsername:
    jid: str
    username: str | None
    raw: BinaryNode | None = None


@dataclass(frozen=True)
class USyncBotProfileCommand:
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class USyncBotProfile:
    jid: str
    name: str | None = None
    attributes: str | None = None
    description: str | None = None
    category: str | None = None
    is_default: bool = False
    prompts: tuple[str, ...] = ()
    persona_id: str | None = None
    commands: tuple[USyncBotProfileCommand, ...] = ()
    commands_description: str | None = None
    raw: BinaryNode | None = None


class TagGenerator:
    def __init__(self) -> None:
        self.prefix = f"{int(time.time() * 1000)}."
        self.epoch = 1

    def next(self) -> str:
        value = f"{self.prefix}{self.epoch}"
        self.epoch += 1
        return value


def jid_decode_full(jid: str) -> JidParts:
    return jid_decode(jid)


def usync_devices_query_node(jids: Iterable[str], tag_id: str) -> BinaryNode:
    return usync_query_node(
        jids,
        [BinaryNode("devices", {"version": "2"}), BinaryNode("lid", {})],
        tag_id,
        context="message",
    )


def usync_query_node(
    jids: Iterable[str],
    protocols: Iterable[str | BinaryNode],
    tag_id: str,
    *,
    context: str = "interactive",
    mode: str = "query",
) -> BinaryNode:
    protocol_nodes = [_protocol_query_node(protocol) for protocol in protocols]
    user_nodes = [BinaryNode("user", {"jid": jid_normalized_user(jid)}, []) for jid in jids]
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "get", "xmlns": "usync"},
        [
            BinaryNode(
                "usync",
                {"context": context, "mode": mode, "sid": tag_id, "last": "true", "index": "0"},
                [
                    BinaryNode("query", {}, protocol_nodes),
                    BinaryNode("list", {}, user_nodes),
                ],
            )
        ],
    )


def parse_usync_result(node: BinaryNode) -> list[dict[str, object]]:
    return _parse_usync_result_section(node, "list")


def parse_usync_side_list(node: BinaryNode) -> list[dict[str, object]]:
    return _parse_usync_result_section(node, "side_list")


def parse_usync_contacts(node: BinaryNode) -> list[USyncContact]:
    contacts: list[USyncContact] = []
    for user_node in _usync_user_nodes(node, "list"):
        child = find_child(user_node, "contact")
        if child is None:
            continue
        contacts.append(USyncContact(jid=_user_node_id(user_node), exists=bool(_parse_usync_child_value(child)), raw=child))
    return contacts


def parse_usync_statuses(node: BinaryNode) -> list[USyncStatus]:
    statuses: list[USyncStatus] = []
    for user_node in _usync_user_nodes(node, "list"):
        child = find_child(user_node, "status")
        if child is None:
            continue
        value = _parse_usync_child_value(child)
        if not isinstance(value, dict):
            continue
        statuses.append(
            USyncStatus(
                jid=_user_node_id(user_node),
                status=value.get("status") if isinstance(value.get("status"), str) or value.get("status") is None else str(value.get("status")),
                set_at=int(value.get("set_at") or 0),
                raw=child,
            )
        )
    return statuses


def parse_usync_disappearing_modes(node: BinaryNode) -> list[USyncDisappearingMode]:
    modes: list[USyncDisappearingMode] = []
    for user_node in _usync_user_nodes(node, "list"):
        child = find_child(user_node, "disappearing_mode")
        if child is None:
            continue
        value = _parse_usync_child_value(child)
        if not isinstance(value, dict):
            continue
        modes.append(
            USyncDisappearingMode(
                jid=_user_node_id(user_node),
                duration=int(value.get("duration") or 0),
                set_at=int(value.get("set_at") or 0),
                raw=child,
            )
        )
    return modes


def parse_usync_usernames(node: BinaryNode) -> list[USyncUsername]:
    usernames: list[USyncUsername] = []
    for user_node in _usync_user_nodes(node, "list"):
        child = find_child(user_node, "username")
        if child is None:
            continue
        value = _parse_usync_child_value(child)
        usernames.append(USyncUsername(jid=_user_node_id(user_node), username=value if isinstance(value, str) or value is None else str(value), raw=child))
    return usernames


def parse_usync_bot_profiles(node: BinaryNode) -> list[USyncBotProfile]:
    profiles: list[USyncBotProfile] = []
    for user_node in _usync_user_nodes(node, "list"):
        child = find_child(user_node, "bot")
        if child is None:
            continue
        profile = _parse_bot_profile(child, _user_node_id(user_node))
        if profile is not None:
            profiles.append(profile)
    return profiles


def _parse_usync_result_section(node: BinaryNode, section: str) -> list[dict[str, object]]:
    if node.tag != "iq" or node.attrs.get("type") != "result":
        return []
    usync = find_child(node, "usync")
    list_node = find_child(usync, section)
    if not isinstance(list_node.content if list_node else None, list):
        return []

    results: list[dict[str, object]] = []
    for user_node in list_node.content:
        if user_node.tag != "user":
            continue
        user_id = user_node.attrs.get("jid") or user_node.attrs.get("id")
        if not user_id:
            continue

        entry: dict[str, object] = {"id": user_id}
        if isinstance(user_node.content, list):
            for child in user_node.content:
                if child.tag == "lid":
                    value = child.attrs.get("val") or child.attrs.get("value")
                    if value:
                        entry["lid"] = value
                elif child.tag == "devices":
                    entry["devices"] = _parse_devices(child)
                elif child.tag == "device":
                    entry["devices"] = _parse_devices(BinaryNode("devices", {}, [child]))
                else:
                    value = _parse_usync_child_value(child)
                    if value is not None:
                        entry[child.tag] = value

        if "devices" not in entry:
            entry["devices"] = {"device_list": [], "key_index": None}

        results.append(entry)
    return results


def extract_device_jids(
    result: list[dict[str, object]],
    my_jid: str,
    my_lid: str | None,
    *,
    exclude_zero_devices: bool = False,
) -> list[DeviceInfo]:
    my = jid_decode_full(my_jid)
    my_lid_user = jid_decode_full(my_lid).user if my_lid else None
    extracted: list[DeviceInfo] = []

    for user_result in result:
        item_id = str(user_result["id"])
        try:
            item_parts = jid_decode_full(item_id)
        except ValueError:
            continue
        device_list = (user_result.get("devices") or {}).get("device_list", [])  # type: ignore[union-attr]
        if not isinstance(device_list, list):
            continue

        for item in device_list:
            device = int(item["id"])
            key_index = item.get("key_index")
            if exclude_zero_devices and device == 0:
                continue
            if (my.user == item_parts.user or my_lid_user == item_parts.user) and my.device == device:
                continue
            if device != 0 and key_index is None:
                continue

            server = _server_for_device(item_parts.server, bool(item.get("is_hosted")))
            extracted.append(
                DeviceInfo(
                    user=item_parts.user,
                    server=server,
                    device=device,
                    jid=jid_encode(item_parts.user, server, device),
                    key_index=key_index,
                    is_hosted=bool(item.get("is_hosted")),
                )
            )
    return extracted


def conversation_identities(creds: dict, chat_jid: str) -> list[str]:
    me_id = creds["me"]["id"]
    me_lid = creds.get("me", {}).get("lid")
    chat = jid_decode_full(chat_jid)
    if chat.server == "lid" and me_lid:
        sender = jid_encode(jid_decode_full(me_lid).user, "lid")
    else:
        sender = jid_encode(jid_decode_full(me_id).user, "s.whatsapp.net")
    return [sender, jid_normalized_user(chat_jid)]


def split_own_and_other_devices(creds: dict, devices: Iterable[DeviceInfo]) -> tuple[list[str], list[str]]:
    me_id = creds["me"]["id"]
    me_lid = creds.get("me", {}).get("lid")
    me_pn_user = jid_decode_full(me_id).user
    me_lid_user = jid_decode_full(me_lid).user if me_lid else None
    me_recipients: list[str] = []
    other_recipients: list[str] = []

    for device in devices:
        if device.jid == me_id or (me_lid and device.jid == me_lid):
            continue
        if device.user == me_pn_user or device.user == me_lid_user:
            me_recipients.append(device.jid)
        else:
            other_recipients.append(device.jid)
    return me_recipients, other_recipients


def _parse_devices(node: BinaryNode) -> dict[str, object]:
    devices: list[dict[str, object]] = []
    key_index_node = find_child(node, "key-index-list")
    key_index: dict[str, object] | None = None

    for device_list_node in _device_list_nodes(node):
        if not isinstance(device_list_node.content if device_list_node else None, list):
            continue
        for device in device_list_node.content:
            if device.tag != "device":
                continue
            device_id = _int_attr(device.attrs.get("id"))
            if device_id is None:
                continue
            devices.append(
                {
                    "id": device_id,
                    "key_index": _int_attr(device.attrs.get("key-index"), device.attrs.get("key_index")),
                    "is_hosted": device.attrs.get("is_hosted") == "true" or device.attrs.get("isHosted") == "true",
                }
            )

    if key_index_node is not None:
        key_index = {
            "timestamp": _int_attr(key_index_node.attrs.get("ts")),
            "expected_timestamp": _int_attr(key_index_node.attrs.get("expected_ts")),
            "signed_key_index": key_index_node.content if isinstance(key_index_node.content, bytes) else None,
        }
    return {"device_list": devices, "key_index": key_index}


def _parse_usync_child_value(node: BinaryNode) -> object | None:
    if node.tag == "contact":
        return (
            node.attrs.get("type") == "in"
            or node.attrs.get("value") == "true"
            or node.attrs.get("value") == "1"
        )
    if node.tag == "status":
        content = node_content_bytes(node)
        value = content.decode("utf-8", errors="replace") if content else None
        if value is None and node.attrs.get("code") == "401":
            value = ""
        elif value == "":
            value = None
        return {"status": value, "set_at": _int_attr(node.attrs.get("t")) or 0, "raw": node}
    if node.tag == "disappearing_mode":
        return {
            "duration": _int_attr(node.attrs.get("duration")) or 0,
            "set_at": _int_attr(node.attrs.get("t")) or 0,
            "raw": node,
        }
    if node.tag == "username":
        content = node_content_bytes(node)
        return content.decode("utf-8", errors="replace") if content else None
    if node.tag == "bot":
        profile = _parse_bot_profile(node, "")
        if profile is not None:
            return profile
    if node.attrs or node.content is not None:
        return {"attrs": dict(node.attrs), "content": node_content_bytes(node), "raw": node}
    return None


def _usync_user_nodes(node: BinaryNode, section: str) -> list[BinaryNode]:
    if node.tag != "iq" or node.attrs.get("type") != "result":
        return []
    usync = find_child(node, "usync")
    list_node = find_child(usync, section)
    if not isinstance(list_node.content if list_node else None, list):
        return []
    return [user_node for user_node in list_node.content if user_node.tag == "user" and _user_node_id(user_node)]


def _user_node_id(node: BinaryNode) -> str:
    return node.attrs.get("jid") or node.attrs.get("id") or ""


def _protocol_query_node(protocol: str | BinaryNode) -> BinaryNode:
    if isinstance(protocol, BinaryNode):
        return protocol
    if protocol == "devices":
        return BinaryNode("devices", {"version": "2"})
    if protocol == "bot":
        return BinaryNode("bot", {}, [BinaryNode("profile", {"v": "1"})])
    return BinaryNode(str(protocol), {})


def _parse_bot_profile(node: BinaryNode, user_id: str) -> USyncBotProfile | None:
    container = find_child(node, "bot") or node
    profile = find_child(container, "profile")
    if profile is None:
        return None

    name = _text_child(profile, "name")
    attributes = _text_child(profile, "attributes")
    description = _text_child(profile, "description")
    category = _text_child(profile, "category")
    default_node = find_child(profile, "default")
    prompts = tuple(_parse_bot_prompts(find_child(profile, "prompts")))
    commands_node = find_child(profile, "commands")
    commands, commands_description = _parse_bot_commands(commands_node)
    return USyncBotProfile(
        jid=user_id or profile.attrs.get("jid") or node.attrs.get("jid") or "",
        name=name,
        attributes=attributes,
        description=description,
        category=category,
        is_default=default_node is not None,
        prompts=prompts,
        persona_id=profile.attrs.get("persona_id") or profile.attrs.get("persona-id") or node.attrs.get("persona_id"),
        commands=tuple(commands),
        commands_description=commands_description,
        raw=node,
    )


def _parse_bot_prompts(node: BinaryNode | None) -> list[str]:
    if node is None or not isinstance(node.content, list):
        return []
    prompts: list[str] = []
    for prompt in node.content:
        if prompt.tag != "prompt":
            continue
        text = _text_child(prompt, "text")
        emoji = _text_child(prompt, "emoji")
        if text and emoji:
            prompts.append(f"{emoji} {text}")
        elif text:
            prompts.append(text)
    return prompts


def _parse_bot_commands(node: BinaryNode | None) -> tuple[list[USyncBotProfileCommand], str | None]:
    if node is None or not isinstance(node.content, list):
        return [], None
    commands: list[USyncBotProfileCommand] = []
    description = _text_child(node, "description")
    for command in node.content:
        if command.tag != "command":
            continue
        commands.append(USyncBotProfileCommand(name=_text_child(command, "name"), description=_text_child(command, "description")))
    return commands, description


def _text_child(node: BinaryNode, tag: str) -> str | None:
    child = find_child(node, tag)
    if child is None:
        return None
    content = node_content_bytes(child)
    return content.decode("utf-8", errors="replace") if content else None


def _device_list_nodes(node: BinaryNode) -> Iterable[BinaryNode]:
    if node.tag == "device-list":
        return [node]
    if node.tag == "device":
        return [BinaryNode("device-list", {}, [node])]

    if isinstance(node.content, list):
        child_list_nodes: list[BinaryNode] = [child for child in node.content if child.tag == "device-list"]
        if child_list_nodes:
            return child_list_nodes
        if any(child.tag == "device" for child in node.content):
            return [node]

    device_list_node = find_child(node, "device-list")
    return [device_list_node] if device_list_node is not None else []


def _int_attr(*values: str | None) -> int | None:
    for value in values:
        if value is None:
            continue
        try:
            return int(value)
        except ValueError:
            continue
    return None


def _server_for_device(initial_server: str, is_hosted: bool) -> str:
    if not is_hosted:
        return initial_server
    if initial_server == "lid":
        return "hosted.lid"
    return "hosted"
