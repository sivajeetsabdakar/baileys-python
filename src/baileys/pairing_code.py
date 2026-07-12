from __future__ import annotations

import base64
import hmac
import os
import re
from dataclasses import dataclass
from typing import Any

from baileys.auth_store import b64
from baileys.crypto import aes_decrypt_ctr, aes_encrypt_ctr, aes_encrypt_gcm, derive_pairing_code_key, hkdf, hmac_sign
from baileys.defaults import (
    S_WHATSAPP_NET,
    WA_ADV_ACCOUNT_SIG_PREFIX,
    WA_ADV_DEVICE_SIG_PREFIX,
    WA_ADV_HOSTED_ACCOUNT_SIG_PREFIX,
)
from baileys.errors import PairingError
from baileys.generated import WAProto_pb2 as proto
from baileys.signal_crypto import SignalKeyPair, shared_key, sign, verify
from baileys.socket_nodes import find_child, node_content_bytes
from baileys.wabinary import BinaryNode


CROCKFORD_CHARACTERS = "123456789ABCDEFGHJKLMNPQRSTVWXYZ"
LINK_CODE_KEY_BUNDLE_INFO = b"link_code_pairing_key_bundle_encryption_key"
COMPANION_PLATFORM_CHROME = "1"


@dataclass(frozen=True)
class PairingFinish:
    node: BinaryNode
    adv_secret_key: str
    companion_shared_key: bytes
    identity_shared_key: bytes
    random: bytes


@dataclass(frozen=True)
class PairingCodeRequest:
    node: BinaryNode
    code: str
    jid: str


@dataclass(frozen=True)
class PairDeviceRefs:
    node: BinaryNode
    refs: list[str]


@dataclass(frozen=True)
class QRPairingRequest:
    node: BinaryNode
    refs: list[str]
    qr: str


@dataclass(frozen=True)
class PairSuccess:
    reply: BinaryNode
    credentials: dict[str, Any]
    update: dict[str, str | None]
    account: bytes


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
            raise PairingError("custom pairing code must be exactly 8 chars")
        return custom_pairing_code
    return bytes_to_crockford(os.urandom(5))


def normalize_phone_number(phone_number: str) -> str:
    digits = re.sub(r"\D", "", phone_number.split("@", 1)[0].split(":", 1)[0])
    if not digits:
        raise PairingError("phone number must contain digits")
    return digits


def phone_jid(phone_number: str) -> str:
    return f"{normalize_phone_number(phone_number)}@s.whatsapp.net"


def build_pairing_qr_data(
    *,
    ref: str,
    noise_key: bytes,
    identity_key: bytes,
    adv_secret_key: str,
    platform_id: str = COMPANION_PLATFORM_CHROME,
) -> str:
    return "https://wa.me/settings/linked_devices#" + ",".join(
        [
            ref,
            base64.b64encode(noise_key).decode("ascii"),
            base64.b64encode(identity_key).decode("ascii"),
            adv_secret_key,
            platform_id,
        ]
    )


def extract_pair_device_refs(node: BinaryNode) -> PairDeviceRefs:
    pair_device = find_child(node, "pair-device")
    if pair_device is None or not isinstance(pair_device.content, list):
        return PairDeviceRefs(node=node, refs=[])
    refs: list[str] = []
    for child in pair_device.content:
        if child.tag != "ref":
            continue
        content = node_content_bytes(child)
        if content is not None:
            refs.append(content.decode("utf-8"))
    return PairDeviceRefs(node=node, refs=refs)


def pair_device_ack_node(node: BinaryNode) -> BinaryNode:
    attrs = {"to": S_WHATSAPP_NET, "type": "result"}
    if node.attrs.get("id"):
        attrs["id"] = node.attrs["id"]
    return BinaryNode("iq", attrs)


def encode_signed_device_identity(account: proto.ADVSignedDeviceIdentity) -> bytes:
    reply_account = proto.ADVSignedDeviceIdentity()
    reply_account.CopyFrom(account)
    reply_account.ClearField("accountSignatureKey")
    return reply_account.SerializeToString()


def configure_successful_pairing(
    stanza: BinaryNode,
    *,
    static_noise: SignalKeyPair,
    meta: dict[str, Any],
) -> PairSuccess:
    pair_success_node = find_child(stanza, "pair-success")
    device_identity_node = find_child(pair_success_node, "device-identity")
    platform_node = find_child(pair_success_node, "platform")
    device_node = find_child(pair_success_node, "device")
    business_node = find_child(pair_success_node, "biz")
    if pair_success_node is None or device_identity_node is None or device_node is None:
        raise PairingError(f"missing pair-success/device-identity/device in {stanza!r}")

    signed_hmac = proto.ADVSignedDeviceIdentityHMAC()
    signed_hmac.ParseFromString(_required_node_bytes(device_identity_node))
    hmac_prefix = b""
    if signed_hmac.HasField("accountType") and signed_hmac.accountType == proto.ADVEncryptionType.HOSTED:
        hmac_prefix = WA_ADV_HOSTED_ACCOUNT_SIG_PREFIX

    expected_hmac = hmac_sign(hmac_prefix + signed_hmac.details, base64.b64decode(str(meta["adv_secret_key"])))
    if not hmac.compare_digest(signed_hmac.hmac, expected_hmac):
        raise PairingError("invalid pair-success ADV HMAC")

    account = proto.ADVSignedDeviceIdentity()
    account.ParseFromString(signed_hmac.details)

    device_identity = proto.ADVDeviceIdentity()
    device_identity.ParseFromString(account.details)

    account_prefix = (
        WA_ADV_HOSTED_ACCOUNT_SIG_PREFIX
        if device_identity.HasField("deviceType") and device_identity.deviceType == proto.ADVEncryptionType.HOSTED
        else WA_ADV_ACCOUNT_SIG_PREFIX
    )
    identity_public = bytes(meta["identity_public"])
    account_message = account_prefix + account.details + identity_public
    if not verify(account.accountSignatureKey, account_message, account.accountSignature):
        raise PairingError("invalid pair-success account signature")

    identity_private = bytes(meta["identity_private"])
    device_message = WA_ADV_DEVICE_SIG_PREFIX + account.details + identity_public + account.accountSignatureKey
    account.deviceSignature = sign(identity_private, device_message)
    account_enc = encode_signed_device_identity(account)

    reply = BinaryNode(
        "iq",
        {"to": S_WHATSAPP_NET, "type": "result", "id": stanza.attrs["id"]},
        [
            BinaryNode(
                "pair-device-sign",
                {},
                [
                    BinaryNode(
                        "device-identity",
                        {"key-index": str(device_identity.keyIndex)},
                        account_enc,
                    )
                ],
            )
        ],
    )
    update = {
        "jid": device_node.attrs.get("jid"),
        "lid": device_node.attrs.get("lid"),
        "platform": platform_node.attrs.get("name") if platform_node else None,
        "business_name": business_node.attrs.get("name") if business_node else None,
    }
    return PairSuccess(
        reply=reply,
        credentials=credentials_from_pair_success(static_noise=static_noise, meta=meta, account=account, update=update),
        update=update,
        account=account.SerializeToString(),
    )


def credentials_from_pair_success(
    *,
    static_noise: SignalKeyPair,
    meta: dict[str, Any],
    account: proto.ADVSignedDeviceIdentity,
    update: dict[str, str | None],
) -> dict[str, Any]:
    return {
        "noise_private": b64(static_noise.private),
        "noise_public": b64(static_noise.public),
        "identity_private": b64(bytes(meta["identity_private"])),
        "identity_public": b64(bytes(meta["identity_public"])),
        "signed_pre_key_private": b64(bytes(meta["signed_pre_key_private"])),
        "signed_pre_key_public": b64(bytes(meta["signed_pre_key_public"])),
        "signed_pre_key_signature": b64(bytes(meta["signed_pre_key_signature"])),
        "signed_pre_key_id": int(meta["signed_pre_key_id"]),
        "registration_id": int(meta["registration_id"]),
        "adv_secret_key": str(meta["adv_secret_key"]),
        "account": b64(account.SerializeToString()),
        "me": {
            "id": update["jid"],
            "lid": update["lid"],
            "name": update["business_name"],
        },
        "platform": update["platform"],
    }


def _required_node_bytes(node: BinaryNode | None) -> bytes:
    content = node_content_bytes(node)
    if content is None:
        raise PairingError("missing node bytes")
    return content


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
        raise PairingError("pairing-code salt must be 32 bytes")
    if len(iv) != 16:
        raise PairingError("pairing-code IV must be 16 bytes")
    key = derive_pairing_code_key(pairing_code, salt)
    return salt + iv + aes_encrypt_ctr(companion_ephemeral_public, key, iv)


def decrypt_link_public_key(pairing_code: str, wrapped_public_key: bytes) -> bytes:
    if len(wrapped_public_key) < 80:
        raise PairingError("wrapped public key must contain salt, IV, and 32-byte payload")
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


def pairing_code_request_node(
    *,
    phone_number: str,
    tag_id: str,
    companion_ephemeral_public: bytes,
    noise_public: bytes,
    pairing_code: str | None = None,
    custom_pairing_code: str | None = None,
    platform_id: str = "1",
    platform_display: str = "Chrome (Windows)",
    should_show_push_notification: bool = True,
) -> PairingCodeRequest:
    code = pairing_code or generate_pairing_code(custom_pairing_code)
    jid = phone_jid(phone_number)
    return PairingCodeRequest(
        node=pairing_code_hello_node(
            phone_number=phone_number,
            tag_id=tag_id,
            pairing_code=code,
            companion_ephemeral_public=companion_ephemeral_public,
            noise_public=noise_public,
            platform_id=platform_id,
            platform_display=platform_display,
            should_show_push_notification=should_show_push_notification,
        ),
        code=code,
        jid=jid,
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
        raise PairingError("link code salt must be 32 bytes")
    if len(encrypt_iv) != 12:
        raise PairingError("AES-GCM IV must be 12 bytes")
    if len(random) != 32:
        raise PairingError("identity random must be 32 bytes")

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
