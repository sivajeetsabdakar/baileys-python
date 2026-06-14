from __future__ import annotations

import base64
import os
import re
from dataclasses import dataclass

from baileys.crypto import aes_decrypt_ctr, aes_encrypt_ctr, aes_encrypt_gcm, derive_pairing_code_key, hkdf
from baileys.signal_crypto import SignalKeyPair, shared_key
from baileys.wabinary import BinaryNode


CROCKFORD_CHARACTERS = "123456789ABCDEFGHJKLMNPQRSTVWXYZ"
S_WHATSAPP_NET = "s.whatsapp.net"
LINK_CODE_KEY_BUNDLE_INFO = b"link_code_pairing_key_bundle_encryption_key"


@dataclass(frozen=True)
class PairingFinish:
    node: BinaryNode
    adv_secret_key: str
    companion_shared_key: bytes
    identity_shared_key: bytes
    random: bytes


def bytes_to_crockford(data: bytes) -> str:
    value = 0
    bit_count = 0
    out: list[str] = []
    for item in data:
        value = (value << 8) | (item & 0xFF)
        bit_count += 8
        while bit_count >= 5:
            out.append(CROCKFORD_CHARACTERS[(value >> (bit_count - 5)) & 31])
            bit_count -= 5
    if bit_count > 0:
        out.append(CROCKFORD_CHARACTERS[(value << (5 - bit_count)) & 31])
    return "".join(out)


def generate_pairing_code(custom_pairing_code: str | None = None) -> str:
    if custom_pairing_code is not None:
        if len(custom_pairing_code) != 8:
            raise ValueError("custom pairing code must be exactly 8 chars")
        return custom_pairing_code
    return bytes_to_crockford(os.urandom(5))


def normalize_phone_number(phone_number: str) -> str:
    digits = re.sub(r"\D", "", phone_number.split("@", 1)[0].split(":", 1)[0])
    if not digits:
        raise ValueError("phone number must contain digits")
    return digits


def phone_jid(phone_number: str) -> str:
    return f"{normalize_phone_number(phone_number)}@s.whatsapp.net"


def generate_pairing_key(
    pairing_code: str,
    companion_ephemeral_public: bytes,
    *,
    salt: bytes | None = None,
    iv: bytes | None = None,
) -> bytes:
    salt = salt or os.urandom(32)
    iv = iv or os.urandom(16)
    if len(salt) != 32:
        raise ValueError("pairing-code salt must be 32 bytes")
    if len(iv) != 16:
        raise ValueError("pairing-code IV must be 16 bytes")
    key = derive_pairing_code_key(pairing_code, salt)
    return salt + iv + aes_encrypt_ctr(companion_ephemeral_public, key, iv)


def decrypt_link_public_key(pairing_code: str, wrapped_public_key: bytes) -> bytes:
    if len(wrapped_public_key) < 80:
        raise ValueError("wrapped public key must contain salt, IV, and 32-byte payload")
    salt = wrapped_public_key[:32]
    iv = wrapped_public_key[32:48]
    payload = wrapped_public_key[48:80]
    return aes_decrypt_ctr(payload, derive_pairing_code_key(pairing_code, salt), iv)


def pairing_code_hello_node(
    *,
    phone_number: str,
    tag_id: str,
    pairing_code: str,
    companion_ephemeral_public: bytes,
    noise_public: bytes,
    platform_id: str = "1",
    platform_display: str = "Chrome (Windows)",
    should_show_push_notification: bool = True,
) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"to": S_WHATSAPP_NET, "type": "set", "id": tag_id, "xmlns": "md"},
        [
            BinaryNode(
                "link_code_companion_reg",
                {
                    "jid": phone_jid(phone_number),
                    "stage": "companion_hello",
                    "should_show_push_notification": "true" if should_show_push_notification else "false",
                },
                [
                    BinaryNode(
                        "link_code_pairing_wrapped_companion_ephemeral_pub",
                        {},
                        generate_pairing_key(pairing_code, companion_ephemeral_public),
                    ),
                    BinaryNode("companion_server_auth_key_pub", {}, noise_public),
                    BinaryNode("companion_platform_id", {}, platform_id),
                    BinaryNode("companion_platform_display", {}, platform_display),
                    BinaryNode("link_code_pairing_nonce", {}, "0"),
                ],
            )
        ],
    )


def pairing_code_finish_node(
    *,
    phone_number: str,
    tag_id: str,
    pairing_code: str,
    pairing_ephemeral: SignalKeyPair,
    identity: SignalKeyPair,
    ref: bytes,
    primary_identity_public: bytes,
    wrapped_primary_ephemeral_public: bytes,
    link_code_salt: bytes | None = None,
    encrypt_iv: bytes | None = None,
    random: bytes | None = None,
) -> PairingFinish:
    primary_ephemeral_public = decrypt_link_public_key(pairing_code, wrapped_primary_ephemeral_public)
    companion_shared_key = shared_key(pairing_ephemeral.private, primary_ephemeral_public)
    identity_shared_key = shared_key(identity.private, primary_identity_public)

    link_code_salt = link_code_salt or os.urandom(32)
    encrypt_iv = encrypt_iv or os.urandom(12)
    random = random or os.urandom(32)
    if len(link_code_salt) != 32:
        raise ValueError("link code salt must be 32 bytes")
    if len(encrypt_iv) != 12:
        raise ValueError("AES-GCM IV must be 12 bytes")
    if len(random) != 32:
        raise ValueError("identity random must be 32 bytes")

    expanded_key = hkdf(companion_shared_key, 32, salt=link_code_salt, info=LINK_CODE_KEY_BUNDLE_INFO)
    encrypted_payload = aes_encrypt_gcm(
        identity.public + primary_identity_public + random,
        expanded_key,
        encrypt_iv,
        b"",
    )
    wrapped_key_bundle = link_code_salt + encrypt_iv + encrypted_payload
    adv_secret_key = base64.b64encode(
        hkdf(companion_shared_key + identity_shared_key + random, 32, info=b"adv_secret")
    ).decode("ascii")

    node = BinaryNode(
        "iq",
        {"to": S_WHATSAPP_NET, "type": "set", "id": tag_id, "xmlns": "md"},
        [
            BinaryNode(
                "link_code_companion_reg",
                {"jid": phone_jid(phone_number), "stage": "companion_finish"},
                [
                    BinaryNode("link_code_pairing_wrapped_key_bundle", {}, wrapped_key_bundle),
                    BinaryNode("companion_identity_public", {}, identity.public),
                    BinaryNode("link_code_pairing_ref", {}, ref),
                ],
            )
        ],
    )
    return PairingFinish(
        node=node,
        adv_secret_key=adv_secret_key,
        companion_shared_key=companion_shared_key,
        identity_shared_key=identity_shared_key,
        random=random,
    )
