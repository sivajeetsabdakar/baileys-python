from __future__ import annotations

from dataclasses import dataclass, field
import json
from importlib import resources
from struct import pack
from typing import Any

from .errors import BaileysValueError


FLAG_GLOBAL = 0
FLAG_EVENT = 1
FLAG_FIELD = 2
FLAG_EXTENDED = 4
FLAG_BYTE = 8

WAMValue = int | float | str | bool | None


@dataclass(frozen=True)
class WAMEventSpec:
    id: int
    weight: int = 1
    props: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class WAMEvent:
    name: str
    props: dict[str, WAMValue] = field(default_factory=dict)
    globals: dict[str, WAMValue] = field(default_factory=dict)


@dataclass
class WAMBinaryInfo:
    protocol_version: int = 5
    sequence: int = 0
    events: list[WAMEvent] = field(default_factory=list)


class WAMEncodeError(BaileysValueError):
    pass


def encode_wam(
    binary_info: WAMBinaryInfo,
    event_specs: dict[str, WAMEventSpec] | None = None,
    global_specs: dict[str, int] | None = None,
) -> bytes:
    parts = [_encode_wam_header(binary_info)]
    if event_specs is None or global_specs is None:
        loaded_events, loaded_globals = load_wam_specs()
        event_specs = event_specs or loaded_events
        global_specs = global_specs or loaded_globals
    globals_by_name = global_specs

    for event in binary_info.events:
        for key, value in event.globals.items():
            if key not in globals_by_name:
                raise WAMEncodeError(f"unknown WAM global: {key}")
            parts.append(_serialize_data(globals_by_name[key], _normalize_value(value), FLAG_GLOBAL))

        if event.name not in event_specs:
            raise WAMEncodeError(f"unknown WAM event: {event.name}")
        spec = event_specs[event.name]
        extended = any(value is not None for value in event.props.values())
        event_flag = FLAG_EVENT if extended else FLAG_EVENT | FLAG_EXTENDED
        parts.append(_serialize_data(spec.id, -spec.weight, event_flag))

        items = list(event.props.items())
        for index, (key, value) in enumerate(items):
            if key not in spec.props:
                raise WAMEncodeError(f"unknown WAM property for {event.name}: {key}")
            field_flag = FLAG_EVENT if index < len(items) - 1 else FLAG_FIELD | FLAG_EXTENDED
            parts.append(_serialize_data(spec.props[key], _normalize_value(value), field_flag))

    return b"".join(parts)


encodeWAM = encode_wam


def load_wam_specs() -> tuple[dict[str, WAMEventSpec], dict[str, int]]:
    with resources.files("baileys.generated").joinpath("wam_constants.json").open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    events = {
        name: WAMEventSpec(id=int(spec["id"]), weight=int(spec.get("weight") or 1), props={key: int(value) for key, value in spec.get("props", {}).items()})
        for name, spec in data["events"].items()
    }
    globals_ = {name: int(value) for name, value in data["globals"].items()}
    return events, globals_


def _encode_wam_header(binary_info: WAMBinaryInfo) -> bytes:
    return b"WAM" + bytes([binary_info.protocol_version, 1]) + int(binary_info.sequence).to_bytes(2, "big") + b"\x00"


def _serialize_data(key: int, value: WAMValue, flag: int) -> bytes:
    if value is None:
        if flag == FLAG_GLOBAL:
            return _serialize_header(key, flag)
        raise WAMEncodeError("null WAM values are only valid for globals")

    if isinstance(value, bool):
        value = 1 if value else 0

    if isinstance(value, int):
        if value in {0, 1}:
            return _serialize_header(key, flag | ((value + 1) << 4))
        if -128 <= value < 128:
            return _serialize_header(key, flag | (3 << 4)) + pack("<b", value)
        if -32768 <= value < 32768:
            return _serialize_header(key, flag | (4 << 4)) + pack("<h", value)
        if -2147483648 <= value < 2147483648:
            return _serialize_header(key, flag | (5 << 4)) + pack("<i", value)
        return _serialize_header(key, flag | (7 << 4)) + pack("<d", float(value))

    if isinstance(value, float):
        return _serialize_header(key, flag | (7 << 4)) + pack("<d", value)

    if isinstance(value, str):
        payload = value.encode("utf-8")
        if len(payload) < 256:
            return _serialize_header(key, flag | (8 << 4)) + bytes([len(payload)]) + payload
        if len(payload) < 65536:
            return _serialize_header(key, flag | (9 << 4)) + len(payload).to_bytes(2, "little") + payload
        return _serialize_header(key, flag | (10 << 4)) + len(payload).to_bytes(4, "little") + payload

    raise WAMEncodeError(f"unsupported WAM value type: {type(value).__name__}")


def _serialize_header(key: int, flag: int) -> bytes:
    if key < 0:
        raise WAMEncodeError("WAM ids must be non-negative")
    if key < 256:
        return bytes([flag, key])
    return bytes([flag | FLAG_BYTE]) + int(key).to_bytes(2, "little")


def _normalize_value(value: Any) -> WAMValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise WAMEncodeError(f"unsupported WAM value type: {type(value).__name__}")
