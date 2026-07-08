from __future__ import annotations

import base64
import os

from .crypto import md5
from .defaults import KEY_BUNDLE_TYPE, VERSION
from .generated import WAProto_pb2 as proto
from .jid import jid_decode
from .signal_crypto import SignalKeyPair, public_from_private, sign


def encode_big_endian(value: int, length: int = 4) -> bytes:
    return value.to_bytes(length, "big")


def generate_registration_id() -> int:
    return int.from_bytes(os.urandom(2), "big") & 16383


def generate_signal_key_pair() -> SignalKeyPair:
    private = os.urandom(32)
    return SignalKeyPair(private=private, public=public_from_private(private))


def signed_key_pair(identity_key_pair: SignalKeyPair, key_id: int) -> tuple[SignalKeyPair, bytes]:
    pre_key = generate_signal_key_pair()
    signature = sign(identity_key_pair.private, KEY_BUNDLE_TYPE + pre_key.public)
    return pre_key, signature


def build_registration_payload() -> tuple[bytes, dict[str, bytes | int]]:
    identity_key = generate_signal_key_pair()
    signed_pre_key, signed_pre_key_signature = signed_key_pair(identity_key, 1)
    registration_id = generate_registration_id()
    adv_secret_key = base64.b64encode(os.urandom(32)).decode("ascii")

    device_props = proto.DeviceProps()
    device_props.os = "Mac OS"
    device_props.platformType = proto.DeviceProps.PlatformType.CHROME
    device_props.requireFullSync = True
    device_props.version.primary = 10
    device_props.version.secondary = 15
    device_props.version.tertiary = 7
    device_props.historySyncConfig.storageQuotaMb = 10240
    device_props.historySyncConfig.inlineInitialPayloadInE2EeMsg = True
    device_props.historySyncConfig.supportCallLogHistory = False
    device_props.historySyncConfig.supportBotUserAgentChatHistory = True
    device_props.historySyncConfig.supportCagReactionsAndPolls = True
    device_props.historySyncConfig.supportBizHostedMsg = True
    device_props.historySyncConfig.supportRecentSyncChunkMessageCountTuning = True
    device_props.historySyncConfig.supportHostedGroupMsg = True
    device_props.historySyncConfig.supportFbidBotChatHistory = True
    device_props.historySyncConfig.supportMessageAssociation = True
    device_props.historySyncConfig.supportGroupHistory = False

    payload = proto.ClientPayload()
    payload.connectType = proto.ClientPayload.ConnectType.WIFI_UNKNOWN
    payload.connectReason = proto.ClientPayload.ConnectReason.USER_ACTIVATED
    payload.passive = False
    payload.pull = False
    payload.userAgent.appVersion.primary = VERSION[0]
    payload.userAgent.appVersion.secondary = VERSION[1]
    payload.userAgent.appVersion.tertiary = VERSION[2]
    payload.userAgent.platform = proto.ClientPayload.UserAgent.Platform.WEB
    payload.userAgent.releaseChannel = proto.ClientPayload.UserAgent.ReleaseChannel.RELEASE
    payload.userAgent.osVersion = "0.1"
    payload.userAgent.device = "Desktop"
    payload.userAgent.osBuildNumber = "0.1"
    payload.userAgent.localeLanguageIso6391 = "en"
    payload.userAgent.mnc = "000"
    payload.userAgent.mcc = "000"
    payload.userAgent.localeCountryIso31661Alpha2 = "US"
    payload.webInfo.webSubPlatform = proto.ClientPayload.WebInfo.WebSubPlatform.WEB_BROWSER

    pairing = payload.devicePairingData
    pairing.buildHash = md5(".".join(str(part) for part in VERSION).encode("utf-8"))
    pairing.deviceProps = device_props.SerializeToString()
    pairing.eRegid = encode_big_endian(registration_id)
    pairing.eKeytype = KEY_BUNDLE_TYPE
    pairing.eIdent = identity_key.public
    pairing.eSkeyId = encode_big_endian(1, 3)
    pairing.eSkeyVal = signed_pre_key.public
    pairing.eSkeySig = signed_pre_key_signature

    return payload.SerializeToString(), {
        "registration_id": registration_id,
        "identity_private": identity_key.private,
        "identity_public": identity_key.public,
        "signed_pre_key_private": signed_pre_key.private,
        "signed_pre_key_public": signed_pre_key.public,
        "signed_pre_key_signature": signed_pre_key_signature,
        "signed_pre_key_id": 1,
        "adv_secret_key": adv_secret_key,
    }


def parse_jid_device(jid: str) -> tuple[int, int | None]:
    parts = jid_decode(jid)
    return int(parts.user), parts.device or None


def build_login_payload(user_jid: str) -> bytes:
    username, device = parse_jid_device(user_jid)

    payload = proto.ClientPayload()
    payload.connectType = proto.ClientPayload.ConnectType.WIFI_UNKNOWN
    payload.connectReason = proto.ClientPayload.ConnectReason.USER_ACTIVATED
    payload.passive = True
    payload.pull = True
    payload.username = username
    if device is not None:
        payload.device = device
    payload.lidDbMigrated = False

    app_version = payload.userAgent.appVersion
    app_version.primary, app_version.secondary, app_version.tertiary = VERSION
    payload.userAgent.platform = proto.ClientPayload.UserAgent.Platform.WEB
    payload.userAgent.releaseChannel = proto.ClientPayload.UserAgent.ReleaseChannel.RELEASE
    payload.userAgent.osVersion = "0.1"
    payload.userAgent.device = "Desktop"
    payload.userAgent.osBuildNumber = "0.1"
    payload.userAgent.localeLanguageIso6391 = "en"
    payload.userAgent.mnc = "000"
    payload.userAgent.mcc = "000"
    payload.userAgent.localeCountryIso31661Alpha2 = "US"
    payload.webInfo.webSubPlatform = proto.ClientPayload.WebInfo.WebSubPlatform.WEB_BROWSER
    return payload.SerializeToString()
