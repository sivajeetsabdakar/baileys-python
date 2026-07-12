from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class BaileysError(Exception):
    """Base class for package-raised errors."""


class BaileysRuntimeError(RuntimeError, BaileysError):
    """Runtime failure raised by socket, protocol, or server operations."""


class BaileysValueError(ValueError, BaileysError):
    """Validation failure raised before a wire operation is attempted."""


class BaileysTimeoutError(TimeoutError, BaileysError):
    """Timeout raised by a protocol operation."""


@dataclass
class QueryTimeoutError(BaileysTimeoutError):
    message: str
    operation: str
    timeout: float | None = None
    tag_id: str | None = None

    def __post_init__(self) -> None:
        BaileysTimeoutError.__init__(self, self.message)


@dataclass
class AccountCapabilityError(BaileysRuntimeError):
    message: str
    capability: str
    data: Any = None

    def __post_init__(self) -> None:
        BaileysRuntimeError.__init__(self, self.message)


class PairingError(BaileysValueError):
    """Pairing payload or credential validation failed."""


class MediaError(BaileysValueError):
    """Media encryption, upload, download, or retry validation failed."""


class AuthStateError(BaileysValueError):
    """Auth state is missing required storage or credential data."""


class SocketNotConnectedError(BaileysRuntimeError):
    """An operation requires an open socket."""


class ProtocolError(BaileysRuntimeError):
    """Unexpected protocol response or malformed server data."""


class SessionAssertionError(BaileysValueError):
    """Signal session assertion did not produce the required sessions."""


class ContactResolutionError(BaileysValueError):
    """A contact, PN JID, or LID JID could not be resolved."""


class GroupInviteError(BaileysValueError):
    """A group invite operation could not produce a usable invite."""
