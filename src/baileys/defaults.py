from __future__ import annotations

VERSION = (2, 3000, 1035194821)
DICT_VERSION = 3

WA_WEBSOCKET_URL = "wss://web.whatsapp.com/ws/chat"
DEFAULT_ORIGIN = "https://web.whatsapp.com"
DEFAULT_USER_AGENT = "Mozilla/5.0 baileys-python"

S_WHATSAPP_NET = "s.whatsapp.net"
LID_SERVER = "lid"
GROUP_SERVER = "g.us"
BROADCAST_SERVER = "broadcast"
HOSTED_SERVER = "hosted"
HOSTED_LID_SERVER = "hosted.lid"
INTEROP_SERVER = "interop"
NEWSLETTER_SERVER = "newsletter"
STATUS_BROADCAST_JID = "status@broadcast"

NOISE_MODE = b"Noise_XX_25519_AESGCM_SHA256\x00\x00\x00\x00"
NOISE_WA_HEADER = bytes([87, 65, 6, 3])

KEY_BUNDLE_TYPE = b"\x05"
SIGNAL_PUBLIC_PREFIX = b"\x05"
MIN_PREKEY_COUNT = 5
INITIAL_PREKEY_COUNT = 812

WA_DEFAULT_EPHEMERAL = 7 * 24 * 60 * 60

WA_ADV_ACCOUNT_SIG_PREFIX = bytes([6, 0])
WA_ADV_DEVICE_SIG_PREFIX = bytes([6, 1])
WA_ADV_HOSTED_ACCOUNT_SIG_PREFIX = bytes([6, 5])
WA_ADV_HOSTED_DEVICE_SIG_PREFIX = bytes([6, 6])

MEDIA_HKDF_KEY_MAPPING = {
    "audio": "Audio",
    "document": "Document",
    "gif": "Video",
    "image": "Image",
    "ppic": "",
    "product": "Image",
    "ptt": "Audio",
    "sticker": "Image",
    "video": "Video",
}

MEDIA_PATH_MAP = {
    "audio": "/mms/audio",
    "document": "/mms/document",
    "gif": "/mms/video",
    "image": "/mms/image",
    "ptt": "/mms/audio",
    "sticker": "/mms/image",
    "video": "/mms/video",
}
