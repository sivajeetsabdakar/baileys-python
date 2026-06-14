from __future__ import annotations

import hashlib
import hmac
import os
import zlib
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, padding, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


GCM_TAG_LENGTH = 16


def random_bytes(length: int) -> bytes:
    return os.urandom(length)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def md5(data: bytes) -> bytes:
    return hashlib.md5(data, usedforsecurity=False).digest()


def hmac_sign(data: bytes, key: bytes, variant: str = "sha256") -> bytes:
    return hmac.new(key, data, variant).digest()


def hkdf(data: bytes, length: int, *, salt: bytes | None = None, info: bytes = b"") -> bytes:
    return HKDF(
        algorithm=hashes.SHA256(),
        length=length,
        salt=salt,
        info=info,
    ).derive(data)


def derive_pairing_code_key(pairing_code: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", pairing_code.encode("utf-8"), salt, 2 << 16, 32)


def decompress_if_required(frame: bytes) -> bytes:
    if not frame:
        raise ValueError("empty frame")
    if frame[0] & 2:
        return zlib.decompress(frame[1:])
    return frame[1:]


def aes_encrypt_gcm(plaintext: bytes, key: bytes, iv: bytes, additional_data: bytes = b"") -> bytes:
    encryptor = Cipher(algorithms.AES(key), modes.GCM(iv)).encryptor()
    encryptor.authenticate_additional_data(additional_data)
    ciphertext = encryptor.update(plaintext) + encryptor.finalize()
    return ciphertext + encryptor.tag


def aes_decrypt_gcm(ciphertext_with_tag: bytes, key: bytes, iv: bytes, additional_data: bytes = b"") -> bytes:
    ciphertext = ciphertext_with_tag[:-GCM_TAG_LENGTH]
    tag = ciphertext_with_tag[-GCM_TAG_LENGTH:]
    decryptor = Cipher(algorithms.AES(key), modes.GCM(iv, tag)).decryptor()
    decryptor.authenticate_additional_data(additional_data)
    return decryptor.update(ciphertext) + decryptor.finalize()


def aes_encrypt_ctr(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    encryptor = Cipher(algorithms.AES(key), modes.CTR(iv)).encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()


def aes_decrypt_ctr(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.CTR(iv)).decryptor()
    return decryptor.update(ciphertext) + decryptor.finalize()


def aes_encrypt_cbc(plaintext: bytes, key: bytes, iv: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def aes_decrypt_cbc(ciphertext: bytes, key: bytes, iv: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


@dataclass(frozen=True)
class X25519KeyPair:
    private: bytes
    public: bytes


def generate_x25519_key_pair() -> X25519KeyPair:
    private_key = x25519.X25519PrivateKey.generate()
    public_key = private_key.public_key()
    private = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return X25519KeyPair(private=private, public=public)


def x25519_shared_key(private: bytes, public: bytes) -> bytes:
    private_key = x25519.X25519PrivateKey.from_private_bytes(private)
    public_key = x25519.X25519PublicKey.from_public_bytes(public[-32:])
    return private_key.exchange(public_key)
