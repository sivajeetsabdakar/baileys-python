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
