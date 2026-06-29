from __future__ import annotations

from dataclasses import dataclass

from .crypto import hkdf
from .defaults import MEDIA_HKDF_KEY_MAPPING


APP_STATE_INFO = b"WhatsApp Mutation Keys"

@dataclass(frozen=True)
class AppStateKeys:
    index_key: bytes
    value_encryption_key: bytes
    value_mac_key: bytes
    snapshot_mac_key: bytes
    patch_mac_key: bytes


@dataclass(frozen=True)
class MediaKeys:
    iv: bytes
    cipher_key: bytes
    mac_key: bytes


def expand_app_state_keys(key_data: bytes) -> AppStateKeys:
    expanded = hkdf(key_data, 160, info=APP_STATE_INFO)
    return AppStateKeys(
        index_key=expanded[0:32],
        value_encryption_key=expanded[32:64],
        value_mac_key=expanded[64:96],
        snapshot_mac_key=expanded[96:128],
        patch_mac_key=expanded[128:160],
    )


def media_hkdf_info_key(media_type: str) -> bytes:
    try:
        mapped = MEDIA_HKDF_KEY_MAPPING[media_type]
    except KeyError as exc:
        raise ValueError(f"unknown media type: {media_type}") from exc
    return f"WhatsApp {mapped} Keys".encode("utf-8")


def derive_media_keys(media_key: bytes, media_type: str) -> MediaKeys:
    expanded = hkdf(media_key, 112, info=media_hkdf_info_key(media_type))
    return MediaKeys(
        iv=expanded[0:16],
        cipher_key=expanded[16:48],
        mac_key=expanded[48:80],
    )
