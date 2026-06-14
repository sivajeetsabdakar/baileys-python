from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from .token_loader import load_tokens


class Tag(IntEnum):
    LIST_EMPTY = 0
    DICTIONARY_0 = 236
    DICTIONARY_1 = 237
    DICTIONARY_2 = 238
    DICTIONARY_3 = 239
    INTEROP_JID = 245
    FB_JID = 246
    AD_JID = 247
    LIST_8 = 248
    LIST_16 = 249
    JID_PAIR = 250
    HEX_8 = 251
    BINARY_8 = 252
    BINARY_20 = 253
    BINARY_32 = 254
    NIBBLE_8 = 255


PACKED_MAX = 127


@dataclass(slots=True)
class BinaryNode:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    content: str | bytes | list["BinaryNode"] | None = None


def encode_binary_node(node: BinaryNode, *, with_stream_prefix: bool = True) -> bytes:
    out = bytearray(b"\x00" if with_stream_prefix else b"")
    _write_node(out, node)
    return bytes(out)


def decode_binary_node(data: bytes, *, has_stream_prefix: bool = True) -> BinaryNode:
    decoder = _Decoder(data[1:] if has_stream_prefix else data)
    return decoder.read_node()


def _write_node(out: bytearray, node: BinaryNode) -> None:
    if not node.tag:
        raise ValueError("node tag cannot be empty")

    attrs = {k: v for k, v in node.attrs.items() if v is not None}
    list_size = 1 + 2 * len(attrs) + (1 if node.content is not None else 0)
    _write_list_start(out, list_size)
    _write_string(out, node.tag)

    for key, value in attrs.items():
        _write_string(out, key)
        _write_string(out, value)

    if isinstance(node.content, str):
        _write_string(out, node.content)
    elif isinstance(node.content, bytes):
        _write_byte_length(out, len(node.content))
        out.extend(node.content)
    elif isinstance(node.content, list):
        _write_list_start(out, len(node.content))
        for child in node.content:
            _write_node(out, child)
    elif node.content is None:
        return
    else:
        raise TypeError(f"unsupported node content: {type(node.content)!r}")


def _write_list_start(out: bytearray, size: int) -> None:
    if size == 0:
        out.append(Tag.LIST_EMPTY)
    elif size < 256:
        out.extend([Tag.LIST_8, size])
    else:
        out.append(Tag.LIST_16)
        out.extend(size.to_bytes(2, "big"))


def _write_byte_length(out: bytearray, length: int) -> None:
    if length >= 2**32:
        raise ValueError("string too large to encode")
    if length >= 1 << 20:
        out.append(Tag.BINARY_32)
        out.extend(length.to_bytes(4, "big"))
    elif length >= 256:
        out.append(Tag.BINARY_20)
        out.extend(bytes([(length >> 16) & 0x0F, (length >> 8) & 0xFF, length & 0xFF]))
    else:
        out.extend([Tag.BINARY_8, length])


def _write_string(out: bytearray, value: str | None) -> None:
    if value is None:
        out.append(Tag.LIST_EMPTY)
        return

    tokens = load_tokens()
    token = tokens.token_map.get(value)
    if token:
        dict_index, token_index = token
        if dict_index is not None:
            out.append(Tag.DICTIONARY_0 + dict_index)
        out.append(token_index)
        return

    if _is_nibble(value):
        _write_packed_bytes(out, value, Tag.NIBBLE_8)
        return

    if _is_hex(value):
        _write_packed_bytes(out, value, Tag.HEX_8)
        return

    full_jid = _split_full_jid(value)
    if full_jid and full_jid[2] is not None:
        user, server, device, domain_type = full_jid
        out.append(Tag.AD_JID)
        out.append(domain_type)
        out.append(device or 0)
        _write_string(out, user)
        return

    jid = _split_simple_jid(value)
    if jid:
        user, server = jid
        out.append(Tag.JID_PAIR)
        _write_string(out, user)
        _write_string(out, server)
        return

    data = value.encode("utf-8")
    _write_byte_length(out, len(data))
    out.extend(data)


def _is_nibble(value: str) -> bool:
    return bool(value) and len(value) <= PACKED_MAX and all(char.isdigit() or char in "-." for char in value)


def _is_hex(value: str) -> bool:
    return bool(value) and len(value) <= PACKED_MAX and all(char.isdigit() or "A" <= char <= "F" for char in value)


def _pack_nibble(char: str) -> int:
    if char == "-":
        return 10
    if char == ".":
        return 11
    if char == "\0":
        return 15
    if char.isdigit():
        return ord(char) - ord("0")
    raise ValueError(f"invalid nibble character: {char!r}")


def _pack_hex(char: str) -> int:
    if char.isdigit():
        return ord(char) - ord("0")
    if "A" <= char <= "F":
        return 10 + ord(char) - ord("A")
    if "a" <= char <= "f":
        return 10 + ord(char) - ord("a")
    if char == "\0":
        return 15
    raise ValueError(f"invalid hex character: {char!r}")


def _write_packed_bytes(out: bytearray, value: str, tag: Tag) -> None:
    out.append(tag)
    rounded_length = (len(value) + 1) // 2
    if len(value) % 2:
        rounded_length |= 0x80
    out.append(rounded_length)

    pack = _pack_nibble if tag == Tag.NIBBLE_8 else _pack_hex
    for i in range(0, len(value) - 1, 2):
        out.append((pack(value[i]) << 4) | pack(value[i + 1]))
    if len(value) % 2:
        out.append((pack(value[-1]) << 4) | pack("\0"))


def _split_full_jid(value: str) -> tuple[str, str, int | None, int] | None:
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        return None
    user_combined, server = value.split("@", 1)
    if ":" in user_combined:
        user_agent, device_raw = user_combined.split(":", 1)
        device = int(device_raw)
    else:
        user_agent = user_combined
        device = None
    user, _, agent_raw = user_agent.partition("_")
    if server == "lid":
        domain_type = 1
    elif server == "hosted":
        domain_type = 128
    elif server == "hosted.lid":
        domain_type = 129
    elif agent_raw:
        domain_type = int(agent_raw)
    else:
        domain_type = 0
    return user, server, device, domain_type


def _split_simple_jid(value: str) -> tuple[str, str] | None:
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        return None
    user, server = value.split("@", 1)
    if ":" in user:
        return None
    return user, server


class _Decoder:
    def __init__(self, data: bytes):
        self.data = data
        self.index = 0

    def read_node(self) -> BinaryNode:
        list_size = self._read_list_size(self._read_byte())
        if list_size < 1:
            raise ValueError("invalid node")

        tag = self._read_string(self._read_byte())
        attrs: dict[str, str] = {}
        attr_count = (list_size - 1) >> 1
        for _ in range(attr_count):
            key = self._read_string(self._read_byte())
            value = self._read_string(self._read_byte())
            attrs[key] = value

        content: Any = None
        if list_size % 2 == 0:
            content_tag = self._read_byte()
            if self._is_list_tag(content_tag):
                content = [self.read_node() for _ in range(self._read_list_size(content_tag))]
            elif content_tag in (Tag.BINARY_8, Tag.BINARY_20, Tag.BINARY_32):
                content = self._read_bytes_by_binary_tag(content_tag)
            else:
                content = self._read_string(content_tag)

        return BinaryNode(tag=tag, attrs=attrs, content=content)

    def _read_byte(self) -> int:
        self._check(1)
        value = self.data[self.index]
        self.index += 1
        return value

    def _read_bytes(self, length: int) -> bytes:
        self._check(length)
        value = self.data[self.index : self.index + length]
        self.index += length
        return value

    def _check(self, length: int) -> None:
        if self.index + length > len(self.data):
            raise ValueError("end of stream")

    def _read_list_size(self, tag: int) -> int:
        if tag == Tag.LIST_EMPTY:
            return 0
        if tag == Tag.LIST_8:
            return self._read_byte()
        if tag == Tag.LIST_16:
            return int.from_bytes(self._read_bytes(2), "big")
        raise ValueError(f"invalid list tag: {tag}")

    def _is_list_tag(self, tag: int) -> bool:
        return tag in (Tag.LIST_EMPTY, Tag.LIST_8, Tag.LIST_16)

    def _read_string(self, tag: int) -> str:
        tokens = load_tokens()
        if 1 <= tag < len(tokens.single_byte_tokens):
            return tokens.single_byte_tokens[tag] or ""
        if Tag.DICTIONARY_0 <= tag <= Tag.DICTIONARY_3:
            dict_index = tag - Tag.DICTIONARY_0
            token_index = self._read_byte()
            try:
                return tokens.double_byte_tokens[dict_index][token_index]
            except IndexError as exc:
                raise ValueError(f"invalid double-byte token: {dict_index}:{token_index}") from exc
        if tag == Tag.LIST_EMPTY:
            return ""
        if tag == Tag.BINARY_8:
            return self._read_bytes(self._read_byte()).decode("utf-8")
        if tag == Tag.BINARY_20:
            length = ((self._read_byte() & 0x0F) << 16) + (self._read_byte() << 8) + self._read_byte()
            return self._read_bytes(length).decode("utf-8")
        if tag == Tag.BINARY_32:
            return self._read_bytes(int.from_bytes(self._read_bytes(4), "big")).decode("utf-8")
        if tag == Tag.JID_PAIR:
            user = self._read_string(self._read_byte())
            server = self._read_string(self._read_byte())
            return f"{user}@{server}"
        if tag == Tag.AD_JID:
            domain_type = self._read_byte()
            device = self._read_byte()
            user = self._read_string(self._read_byte())
            server = {
                1: "lid",
                128: "hosted",
                129: "hosted.lid",
            }.get(domain_type, "s.whatsapp.net")
            return f"{user}{f':{device}' if device else ''}@{server}"
        if tag == Tag.FB_JID:
            user = self._read_string(self._read_byte())
            device = int.from_bytes(self._read_bytes(2), "big")
            server = self._read_string(self._read_byte())
            return f"{user}:{device}@{server}"
        if tag == Tag.INTEROP_JID:
            user = self._read_string(self._read_byte())
            device = int.from_bytes(self._read_bytes(2), "big")
            integrator = int.from_bytes(self._read_bytes(2), "big")
            before_server = self.index
            try:
                server = self._read_string(self._read_byte())
            except ValueError:
                self.index = before_server
                server = "interop"
            return f"{integrator}-{user}:{device}@{server}"
        if tag in (Tag.NIBBLE_8, Tag.HEX_8):
            return self._read_packed8(tag)
        raise ValueError(f"unsupported string tag in spike decoder: {tag}")

    def _read_packed8(self, tag: int) -> str:
        start_byte = self._read_byte()
        value = []
        for _ in range(start_byte & 0x7F):
            current = self._read_byte()
            value.append(chr(self._unpack_byte(tag, (current & 0xF0) >> 4)))
            value.append(chr(self._unpack_byte(tag, current & 0x0F)))
        if start_byte >> 7:
            value = value[:-1]
        return "".join(value)

    def _unpack_byte(self, tag: int, value: int) -> int:
        if tag == Tag.NIBBLE_8:
            if 0 <= value <= 9:
                return ord("0") + value
            if value == 10:
                return ord("-")
            if value == 11:
                return ord(".")
            if value == 15:
                return ord("\0")
            raise ValueError(f"invalid nibble: {value}")
        if tag == Tag.HEX_8:
            if 0 <= value < 16:
                return ord("0") + value if value < 10 else ord("A") + value - 10
            raise ValueError(f"invalid hex: {value}")
        raise ValueError(f"unknown packed tag: {tag}")

    def _read_bytes_by_binary_tag(self, tag: int) -> bytes:
        if tag == Tag.BINARY_8:
            length = self._read_byte()
        elif tag == Tag.BINARY_20:
            length = ((self._read_byte() & 0x0F) << 16) + (self._read_byte() << 8) + self._read_byte()
        elif tag == Tag.BINARY_32:
            length = int.from_bytes(self._read_bytes(4), "big")
        else:
            raise ValueError(f"invalid binary tag: {tag}")
        return self._read_bytes(length)
