from __future__ import annotations

from dataclasses import dataclass
import os

from .crypto import aes_decrypt_gcm, aes_encrypt_gcm, hkdf, sha256
from .generated import WAProto_pb2 as proto
from .signal_crypto import SignalKeyPair, public_from_private, shared_key, sign, verify


NOISE_MODE = b"Noise_XX_25519_AESGCM_SHA256\x00\x00\x00\x00"
NOISE_WA_HEADER = bytes([87, 65, 6, 3])
WA_CERT_SERIAL = 0
WA_CERT_PUBLIC_KEY = bytes.fromhex("142375574d0a587166aae71ebe516437c4a28b73e3695c6ce1f7f9545da8ee6b")


@dataclass(frozen=True)
class NoiseCertificateInfo:
    issuer_serial: int
    intermediate_key: bytes
    leaf_key: bytes
    encrypted_static_key: bytes


class TransportState:
    def __init__(self, enc_key: bytes, dec_key: bytes):
        self.enc_key = enc_key
        self.dec_key = dec_key
        self.read_counter = 0
        self.write_counter = 0

    def encrypt(self, plaintext: bytes) -> bytes:
        encrypted = aes_encrypt_gcm(plaintext, self.enc_key, _iv(self.write_counter), b"")
        self.write_counter += 1
        return encrypted

    def decrypt(self, ciphertext: bytes) -> bytes:
        decrypted = aes_decrypt_gcm(ciphertext, self.dec_key, _iv(self.read_counter), b"")
        self.read_counter += 1
        return decrypted


def generate_noise_key_pair() -> SignalKeyPair:
    private = os.urandom(32)
    return SignalKeyPair(private=private, public=public_from_private(private))


def _iv(counter: int) -> bytes:
    return b"\x00" * 8 + counter.to_bytes(4, "big")


def noise_intro_header(routing_info: bytes | None = None) -> bytes:
    if not routing_info:
        return NOISE_WA_HEADER
    if len(routing_info) >= 1 << 24:
        raise ValueError("routing_info is too large")
    return (
        b"ED"
        + b"\x00\x01"
        + bytes([len(routing_info) >> 16])
        + (len(routing_info) & 0xFFFF).to_bytes(2, "big")
        + routing_info
        + NOISE_WA_HEADER
    )


class NoiseHandshake:
    def __init__(self, ephemeral_key_pair: SignalKeyPair, routing_info: bytes | None = None):
        self.ephemeral_key_pair = ephemeral_key_pair
        self.intro_header = noise_intro_header(routing_info)
        self.hash = NOISE_MODE if len(NOISE_MODE) == 32 else sha256(NOISE_MODE)
        self.salt = self.hash
        self.enc_key = self.hash
        self.dec_key = self.hash
        self.counter = 0
        self.sent_intro = False
        self.transport: TransportState | None = None
        self.in_bytes = b""
        self.authenticate(NOISE_WA_HEADER)
        self.authenticate(ephemeral_key_pair.public)

    def authenticate(self, data: bytes) -> None:
        self.hash = sha256(self.hash + data)

    def local_hkdf(self, data: bytes) -> tuple[bytes, bytes]:
        expanded = hkdf(data, 64, salt=self.salt, info=b"")
        return expanded[:32], expanded[32:]

    def mix_into_key(self, data: bytes) -> None:
        write, read = self.local_hkdf(data)
        self.salt = write
        self.enc_key = read
        self.dec_key = read
        self.counter = 0

    def encrypt(self, plaintext: bytes) -> bytes:
        if self.transport:
            return self.transport.encrypt(plaintext)
        encrypted = aes_encrypt_gcm(plaintext, self.enc_key, _iv(self.counter), self.hash)
        self.counter += 1
        self.authenticate(encrypted)
        return encrypted

    def decrypt(self, ciphertext: bytes) -> bytes:
        if self.transport:
            return self.transport.decrypt(ciphertext)
        decrypted = aes_decrypt_gcm(ciphertext, self.dec_key, _iv(self.counter), self.hash)
        self.counter += 1
        self.authenticate(ciphertext)
        return decrypted

    def client_hello_frame(self) -> bytes:
        hello = proto.HandshakeMessage()
        hello.clientHello.ephemeral = self.ephemeral_key_pair.public
        return self.encode_frame(hello.SerializeToString())

    def encode_frame(self, payload: bytes) -> bytes:
        if self.transport:
            payload = self.transport.encrypt(payload)
        intro = b"" if self.sent_intro else self.intro_header
        self.sent_intro = True
        return intro + len(payload).to_bytes(3, "big") + payload

    def finish_init(self) -> None:
        write, read = self.local_hkdf(b"")
        self.transport = TransportState(write, read)

    def decode_transport_frames(self, data: bytes) -> list[bytes]:
        frames: list[bytes] = []
        self.in_bytes += data
        index = 0
        while index + 3 <= len(self.in_bytes):
            size = int.from_bytes(self.in_bytes[index : index + 3], "big")
            index += 3
            if index + size > len(self.in_bytes):
                index -= 3
                break
            ciphertext = self.in_bytes[index : index + size]
            index += size
            frames.append(self.decrypt(ciphertext))
        self.in_bytes = self.in_bytes[index:]
        return frames

    def process_server_hello(self, server_hello_payload: bytes, static_noise_key: SignalKeyPair) -> NoiseCertificateInfo:
        handshake = proto.HandshakeMessage()
        handshake.ParseFromString(server_hello_payload)
        if not handshake.HasField("serverHello"):
            raise ValueError("server did not return serverHello")

        server_hello = handshake.serverHello
        self.authenticate(server_hello.ephemeral)
        self.mix_into_key(shared_key(self.ephemeral_key_pair.private, server_hello.ephemeral))

        decrypted_static = self.decrypt(server_hello.static)
        self.mix_into_key(shared_key(self.ephemeral_key_pair.private, decrypted_static))

        cert_payload = self.decrypt(server_hello.payload)
        cert_chain = proto.CertChain()
        cert_chain.ParseFromString(cert_payload)
        if not cert_chain.HasField("leaf") or not cert_chain.HasField("intermediate"):
            raise ValueError("invalid certificate chain")

        details = proto.CertChain.NoiseCertificate.Details()
        details.ParseFromString(cert_chain.intermediate.details)

        if not verify(details.key, cert_chain.leaf.details, cert_chain.leaf.signature):
            raise ValueError("leaf certificate signature invalid")

        if not verify(WA_CERT_PUBLIC_KEY, cert_chain.intermediate.details, cert_chain.intermediate.signature):
            raise ValueError("intermediate certificate signature invalid")

        if details.issuerSerial != WA_CERT_SERIAL:
            raise ValueError(f"unexpected issuer serial: {details.issuerSerial}")

        encrypted_static_key = self.encrypt(static_noise_key.public)
        self.mix_into_key(shared_key(static_noise_key.private, server_hello.ephemeral))

        return NoiseCertificateInfo(
            issuer_serial=details.issuerSerial,
            intermediate_key=details.key,
            leaf_key=decrypted_static,
            encrypted_static_key=encrypted_static_key,
        )

    def debug_server_hello_state(self, server_hello_payload: bytes) -> dict[str, str | int]:
        handshake = proto.HandshakeMessage()
        handshake.ParseFromString(server_hello_payload)
        if not handshake.HasField("serverHello"):
            raise ValueError("server did not return serverHello")

        server_hello = handshake.serverHello
        self.authenticate(server_hello.ephemeral)
        shared = shared_key(self.ephemeral_key_pair.private, server_hello.ephemeral)
        self.mix_into_key(shared)
        return {
            "server_ephemeral_len": len(server_hello.ephemeral),
            "server_static_len": len(server_hello.static),
            "server_payload_len": len(server_hello.payload),
            "server_ephemeral_hex": server_hello.ephemeral.hex(),
            "server_static_hex": server_hello.static.hex(),
            "server_payload_hex": server_hello.payload.hex(),
            "shared_hex": shared.hex(),
            "hash_hex": self.hash.hex(),
            "salt_hex": self.salt.hex(),
            "dec_key_hex": self.dec_key.hex(),
            "counter": self.counter,
        }
