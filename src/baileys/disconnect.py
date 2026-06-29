from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from .wabinary import BinaryNode


class DisconnectReason(IntEnum):
    connectionClosed = 428
    connectionLost = 408
    connectionReplaced = 440
    timedOut = 408
    loggedOut = 401
    badSession = 500
    restartRequired = 515
    multideviceMismatch = 411
    forbidden = 403
    unavailableService = 503


@dataclass
class DisconnectError(Exception):
    message: str
    status_code: int
    reason: str | None = None
    data: Any = None

    def __post_init__(self) -> None:
        self.status_code = int(self.status_code)
        Exception.__init__(self, self.message)


_STREAM_CODE_MAP = {
    "conflict": DisconnectReason.connectionReplaced,
}


def stream_error_to_disconnect(node: BinaryNode) -> DisconnectError:
    reason_node = _first_child(node)
    reason = reason_node.tag if reason_node is not None else "unknown"
    status_code = int(node.attrs.get("code") or _STREAM_CODE_MAP.get(reason, DisconnectReason.badSession))
    if status_code == DisconnectReason.restartRequired:
        reason = "restart required"
    return DisconnectError(
        f"Stream Errored ({reason})",
        status_code=status_code,
        reason=reason,
        data=reason_node or node,
    )


def failure_to_disconnect(node: BinaryNode) -> DisconnectError:
    status_code = int(node.attrs.get("reason") or DisconnectReason.badSession)
    return DisconnectError(
        "Connection Failure",
        status_code=status_code,
        reason=str(status_code),
        data=dict(node.attrs),
    )


def disconnect_update(error: DisconnectError) -> dict[str, Any]:
    return {
        "connection": "close",
        "last_disconnect": error,
        "disconnect_reason": int(error.status_code),
        "disconnect_reason_name": _reason_name(error.status_code),
    }


def logged_out_disconnect(message: str = "Intentional Logout") -> DisconnectError:
    return DisconnectError(
        message,
        status_code=DisconnectReason.loggedOut,
        reason="loggedOut",
    )


def _first_child(node: BinaryNode) -> BinaryNode | None:
    if not isinstance(node.content, list):
        return None
    return node.content[0] if node.content else None


def _reason_name(status_code: int) -> str | None:
    try:
        return DisconnectReason(status_code).name
    except ValueError:
        return None
