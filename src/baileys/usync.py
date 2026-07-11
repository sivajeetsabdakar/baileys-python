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
    user_nodes = [BinaryNode("user", {"jid": jid_normalized_user(jid)}, []) for jid in jids]
    return BinaryNode(
        "iq",
        {"id": tag_id, "to": S_WHATSAPP_NET, "type": "get", "xmlns": "usync"},
        [
            BinaryNode(
                "usync",
                {"context": "message", "mode": "query", "sid": tag_id, "last": "true", "index": "0"},
                [
                    BinaryNode("query", {}, [BinaryNode("devices", {"version": "2"}), BinaryNode("lid", {})]),
                    BinaryNode("list", {}, user_nodes),
                ],
            )
        ],
    )


def parse_usync_result(node: BinaryNode) -> list[dict[str, object]]:
    if node.tag != "iq" or node.attrs.get("type") != "result":
        return []
    usync = find_child(node, "usync")
    list_node = find_child(usync, "list")
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
    if node.attrs or node.content is not None:
        return {"attrs": dict(node.attrs), "content": node_content_bytes(node), "raw": node}
    return None


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
