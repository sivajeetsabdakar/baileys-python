from __future__ import annotations

from enum import Enum

from baileys.wabinary import BinaryNode


S_WHATSAPP_NET = "s.whatsapp.net"


class SocketNodeKind(str, Enum):
    LOGIN_SUCCESS = "login_success"
    SERVER_PING = "server_ping"
    EDGE_ROUTING = "edge_routing"
    OFFLINE_PREVIEW = "offline_preview"
    OFFLINE = "offline"
    ENCRYPT_COUNT = "encrypt_count"
    DIRTY = "dirty"
    MESSAGE = "message"
    RECEIPT = "receipt"
    ACK = "ack"
    NOTIFICATION = "notification"
    IQ_RESULT = "iq_result"
    IQ_ERROR = "iq_error"
    FAILURE = "failure"
    STREAM_ERROR = "stream_error"
    UNKNOWN = "unknown"


def summarize_node(node: BinaryNode) -> str:
    child_tags: list[str] = []
    if isinstance(node.content, list):
        child_tags = [child.tag for child in node.content]
    return f"tag={node.tag!r} attrs={node.attrs!r} children={child_tags!r}"


def find_child(node: BinaryNode | None, tag: str) -> BinaryNode | None:
    if node is None or not isinstance(node.content, list):
        return None
    for child in node.content:
        if child.tag == tag:
            return child
    return None


def node_content_bytes(node: BinaryNode | None) -> bytes | None:
    if node is None:
        return None
    if isinstance(node.content, bytes):
        return node.content
    if isinstance(node.content, str):
        return node.content.encode("utf-8")
    return None


def classify_node(node: BinaryNode) -> SocketNodeKind:
    if node.tag == "success":
        return SocketNodeKind.LOGIN_SUCCESS
    if node.tag == "failure":
        return SocketNodeKind.FAILURE
    if node.tag == "stream:error":
        return SocketNodeKind.STREAM_ERROR
    if node.tag == "message":
        return SocketNodeKind.MESSAGE
    if node.tag == "receipt":
        return SocketNodeKind.RECEIPT
    if node.tag == "ack":
        if node.attrs.get("error"):
            return SocketNodeKind.IQ_ERROR
        return SocketNodeKind.ACK
    if node.tag == "notification":
        if node.attrs.get("type") == "encrypt" and find_child(node, "count") is not None:
            return SocketNodeKind.ENCRYPT_COUNT
        return SocketNodeKind.NOTIFICATION
    if node.tag == "iq":
        if node.attrs.get("type") == "get" and node.attrs.get("xmlns") == "urn:xmpp:ping":
            return SocketNodeKind.SERVER_PING
        if node.attrs.get("type") == "error" or find_child(node, "error") is not None:
            return SocketNodeKind.IQ_ERROR
        if node.attrs.get("type") == "result":
            return SocketNodeKind.IQ_RESULT
    if node.tag == "ib":
        if find_child(node, "edge_routing") is not None:
            return SocketNodeKind.EDGE_ROUTING
        if find_child(node, "offline_preview") is not None:
            return SocketNodeKind.OFFLINE_PREVIEW
        if find_child(node, "offline") is not None:
            return SocketNodeKind.OFFLINE
        if find_child(node, "dirty") is not None:
            return SocketNodeKind.DIRTY
    return SocketNodeKind.UNKNOWN


def encrypt_count(node: BinaryNode) -> int:
    count = find_child(node, "count")
    if count is None:
        raise ValueError("missing count child")
    return int(count.attrs["value"])


def server_ping_reply(node: BinaryNode) -> BinaryNode:
    attrs = {"to": S_WHATSAPP_NET, "type": "result"}
    if node.attrs.get("id"):
        attrs["id"] = node.attrs["id"]
    if node.attrs.get("t"):
        attrs["t"] = node.attrs["t"]
    return BinaryNode("iq", attrs)


def offline_batch_node() -> BinaryNode:
    return BinaryNode("ib", {}, [BinaryNode("offline_batch", {"count": "100"})])
