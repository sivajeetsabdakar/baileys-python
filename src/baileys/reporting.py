from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .crypto import hkdf, hmac_sign
from .generated import WAProto_pb2 as proto
from .wabinary import BinaryNode


ENC_SECRET_REPORT_TOKEN = b"Report Token"
WIRE_VARINT = 0
WIRE_FIXED64 = 1
WIRE_BYTES = 2
WIRE_FIXED32 = 5


@dataclass(frozen=True)
class ReportingField:
    field: int
    message: bool = False
    children: tuple["ReportingField", ...] = ()


REPORTING_FIELDS: tuple[ReportingField, ...] = (
    ReportingField(1),
    ReportingField(3, children=(ReportingField(2), ReportingField(3), ReportingField(8), ReportingField(11), ReportingField(17, children=(ReportingField(21), ReportingField(22))), ReportingField(25))),
    ReportingField(4, children=(ReportingField(1), ReportingField(16), ReportingField(17, children=(ReportingField(21), ReportingField(22))))),
    ReportingField(5, children=(ReportingField(3), ReportingField(4), ReportingField(5), ReportingField(16), ReportingField(17, children=(ReportingField(21), ReportingField(22))))),
    ReportingField(6, children=(ReportingField(1), ReportingField(17, children=(ReportingField(21), ReportingField(22))), ReportingField(30))),
    ReportingField(7, children=(ReportingField(2), ReportingField(7), ReportingField(10), ReportingField(17, children=(ReportingField(21), ReportingField(22))), ReportingField(20))),
    ReportingField(8, children=(ReportingField(2), ReportingField(7), ReportingField(9), ReportingField(17, children=(ReportingField(21), ReportingField(22))), ReportingField(21))),
    ReportingField(9, children=(ReportingField(2), ReportingField(6), ReportingField(7), ReportingField(13), ReportingField(17, children=(ReportingField(21), ReportingField(22))), ReportingField(20))),
    ReportingField(12, children=(ReportingField(1), ReportingField(2), ReportingField(14, message=True), ReportingField(15))),
    ReportingField(18, children=(ReportingField(6), ReportingField(16), ReportingField(17, children=(ReportingField(21), ReportingField(22))))),
    ReportingField(26, children=(ReportingField(4), ReportingField(5), ReportingField(8), ReportingField(13), ReportingField(17, children=(ReportingField(21), ReportingField(22))))),
    ReportingField(28, children=(ReportingField(1), ReportingField(2), ReportingField(4), ReportingField(5), ReportingField(6), ReportingField(7, children=(ReportingField(21), ReportingField(22))))),
    ReportingField(37, children=(ReportingField(1, message=True),)),
    ReportingField(49, children=(ReportingField(2), ReportingField(3, children=(ReportingField(1), ReportingField(2))), ReportingField(5, children=(ReportingField(21), ReportingField(22))), ReportingField(8, children=(ReportingField(1), ReportingField(2))))),
    ReportingField(53, children=(ReportingField(1, message=True),)),
    ReportingField(55, children=(ReportingField(1, message=True),)),
    ReportingField(58, children=(ReportingField(1, message=True),)),
    ReportingField(59, children=(ReportingField(1, message=True),)),
    ReportingField(60, children=(ReportingField(2), ReportingField(3, children=(ReportingField(1), ReportingField(2))), ReportingField(5, children=(ReportingField(21), ReportingField(22))), ReportingField(8, children=(ReportingField(1), ReportingField(2))))),
    ReportingField(64, children=(ReportingField(2), ReportingField(3, children=(ReportingField(1), ReportingField(2))), ReportingField(5, children=(ReportingField(21), ReportingField(22))), ReportingField(8, children=(ReportingField(1), ReportingField(2))))),
    ReportingField(66, children=(ReportingField(2), ReportingField(6), ReportingField(7), ReportingField(13), ReportingField(17, children=(ReportingField(21), ReportingField(22))), ReportingField(20))),
    ReportingField(74, children=(ReportingField(1, message=True),)),
    ReportingField(87, children=(ReportingField(1, message=True),)),
    ReportingField(88, children=(ReportingField(1), ReportingField(2, children=(ReportingField(1),)), ReportingField(3, children=(ReportingField(21), ReportingField(22))))),
    ReportingField(92, children=(ReportingField(1, message=True),)),
    ReportingField(93, children=(ReportingField(1, message=True),)),
    ReportingField(94, children=(ReportingField(1, message=True),)),
)


def should_include_reporting_token(message: proto.Message) -> bool:
    return not (
        message.HasField("reactionMessage")
        or message.HasField("encReactionMessage")
        or message.HasField("encEventResponseMessage")
        or message.HasField("pollUpdateMessage")
    )


def get_message_reporting_token(msg_protobuf: bytes, message: proto.Message, key: dict[str, Any]) -> BinaryNode | None:
    if not message.HasField("messageContextInfo") or not message.messageContextInfo.messageSecret:
        return None
    message_id = key.get("id")
    if not message_id:
        return None
    from_jid = key.get("remoteJid") if key.get("fromMe") else key.get("participant") or key.get("remoteJid")
    to_jid = key.get("participant") or key.get("remoteJid") if key.get("fromMe") else key.get("remoteJid")
    if not from_jid or not to_jid:
        return None
    reporting_secret = _message_secret_key(ENC_SECRET_REPORT_TOKEN, str(message_id), str(from_jid), str(to_jid), message.messageContextInfo.messageSecret)
    content = extract_reporting_token_content(msg_protobuf, REPORTING_FIELDS)
    if not content:
        return None
    token = hmac_sign(content, reporting_secret)[:16]
    return BinaryNode("reporting", {}, [BinaryNode("reporting_token", {"v": "2"}, token)])


getMessageReportingToken = get_message_reporting_token
shouldIncludeReportingToken = should_include_reporting_token


def extract_reporting_token_content(data: bytes, fields: tuple[ReportingField, ...] = REPORTING_FIELDS) -> bytes | None:
    compiled = {field.field: field for field in fields}
    return _extract_reporting_token_content(data, compiled)


def _message_secret_key(modification_type: bytes, original_message_id: str, original_sender: str, modification_sender: str, message_secret: bytes) -> bytes:
    info = original_message_id.encode() + original_sender.encode() + modification_sender.encode() + modification_type
    return hkdf(message_secret, 32, info=info)


def _extract_reporting_token_content(data: bytes, fields: dict[int, ReportingField]) -> bytes | None:
    output: list[tuple[int, bytes]] = []
    i = 0
    while i < len(data):
        tag = _decode_varint(data, i)
        if tag is None:
            return None
        tag_value, tag_bytes = tag
        field_num = tag_value >> 3
        wire_type = tag_value & 0x7
        field_start = i
        i += tag_bytes
        field = fields.get(field_num)

        if wire_type == WIRE_VARINT:
            value = _decode_varint(data, i)
            if value is None:
                return None
            end = i + value[1]
        elif wire_type == WIRE_FIXED64:
            end = i + 8
        elif wire_type == WIRE_FIXED32:
            end = i + 4
        elif wire_type == WIRE_BYTES:
            length = _decode_varint(data, i)
            if length is None:
                return None
            value_start = i + length[1]
            value_end = value_start + length[0]
            if value_end > len(data):
                return None
            if field is None:
                i = value_end
                continue
            if field.message or field.children:
                child_fields = {child.field: child for child in field.children}
                sub = _extract_reporting_token_content(data[value_start:value_end], child_fields)
                if sub is None:
                    return None
                if sub:
                    output.append((field_num, _encode_varint(tag_value) + _encode_varint(len(sub)) + sub))
                i = value_end
                continue
            end = value_end
        else:
            return None

        if end > len(data):
            return None
        if field is not None:
            output.append((field_num, data[field_start:end]))
        i = end
    output.sort(key=lambda item: item[0])
    return b"".join(item[1] for item in output)


def _decode_varint(data: bytes, offset: int) -> tuple[int, int] | None:
    value = 0
    shift = 0
    index = 0
    while offset + index < len(data):
        current = data[offset + index]
        value |= (current & 0x7F) << shift
        index += 1
        if current & 0x80 == 0:
            return value, index
        shift += 7
        if shift > 35:
            return None
    return None


def _encode_varint(value: int) -> bytes:
    output = bytearray()
    remaining = value & 0xFFFFFFFF
    while remaining > 0x7F:
        output.append((remaining & 0x7F) | 0x80)
        remaining >>= 7
    output.append(remaining)
    return bytes(output)
