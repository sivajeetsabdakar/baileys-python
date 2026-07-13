from __future__ import annotations

from dataclasses import dataclass

import xeddsa
from signal_protocol import curve


SIGNAL_PUBLIC_KEY_PREFIX = b"\x05"


@dataclass(frozen=True)
class SignalKeyPair:
    private: bytes
    public: bytes

    @property
    def public_with_prefix(self) -> bytes:
        return SIGNAL_PUBLIC_KEY_PREFIX + self.public


def _strip_signal_prefix(public_key: bytes) -> bytes:
    if len(public_key) == 33 and public_key[0] == SIGNAL_PUBLIC_KEY_PREFIX[0]:
        return public_key[1:]
    return public_key


def public_from_private(private_key: bytes) -> bytes:
    return bytes(xeddsa.priv_to_curve25519_pub(private_key))


def signal_public_from_private(private_key: bytes) -> bytes:
    return SIGNAL_PUBLIC_KEY_PREFIX + public_from_private(private_key)


def shared_key(private_key: bytes, public_key: bytes) -> bytes:
    return bytes(xeddsa.x25519(private_key, _strip_signal_prefix(public_key)))


def sign(private_key: bytes, message: bytes) -> bytes:
    return bytes(curve.PrivateKey.deserialize(private_key).calculate_signature(message))


def verify(public_key: bytes, message: bytes, signature: bytes) -> bool:
    curve_public = _strip_signal_prefix(public_key)
    try:
        if curve.PublicKey.deserialize(SIGNAL_PUBLIC_KEY_PREFIX + curve_public).verify_signature(message, signature):
            return True
    except Exception:
        pass
    for sign_bit in (False, True):
        ed_public = xeddsa.curve25519_pub_to_ed25519_pub(curve_public, sign_bit)
        if xeddsa.ed25519_verify(signature, ed_public, message):
            return True
    return False
