from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
import time
from dataclasses import dataclass
from typing import Any, Iterable

import aiohttp

from baileys.crypto import aes_decrypt_cbc, aes_decrypt_gcm, aes_encrypt_cbc, aes_encrypt_gcm, hkdf, hmac_sign, random_bytes, sha256
from baileys.defaults import DEFAULT_ORIGIN, MEDIA_PATH_MAP, S_WHATSAPP_NET
from baileys.generated import WAProto_pb2 as proto
from baileys.jid import jid_normalized_user
from baileys.socket_nodes import find_child
from baileys.wabinary import BinaryNode
from baileys.whatsapp_keys import derive_media_keys


@dataclass(frozen=True)
class MediaHost:
    hostname: str
    max_content_length_bytes: int | None = None


@dataclass(frozen=True)
class MediaConn:
    auth: str
    ttl: int
    hosts: list[MediaHost]


@dataclass(frozen=True)
class EncryptedMedia:
    media_key: bytes
    encrypted: bytes
    mac: bytes
    file_sha256: bytes
    file_enc_sha256: bytes
    file_length: int


@dataclass(frozen=True)
class MediaUploadResult:
    host: str
    media_url: str = ""
    direct_path: str = ""
    fbid: str | None = None
    meta_hmac: str | None = None
    timestamp: str | None = None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class MediaPayload:
    data: bytes
    media_type: str
    mimetype: str
    filename: str | None = None
    caption: str = ""
    width: int = 0
    height: int = 0
    seconds: int = 0
    ptt: bool = False


@dataclass(frozen=True)
class MediaRetryEvent:
    key: dict[str, Any]
    media: dict[str, bytes] | None = None
    error: Exception | None = None


def media_conn_node(tag_id: str) -> BinaryNode:
    return BinaryNode(
        "iq",
        {"id": tag_id, "type": "set", "xmlns": "w:m", "to": S_WHATSAPP_NET},
        [BinaryNode("media_conn", {})],
    )


def parse_media_conn(node: BinaryNode) -> MediaConn:
    media_conn = find_child(node, "media_conn")
    if media_conn is None:
        raise ValueError(f"media_conn response missing child: {node!r}")
    hosts: list[MediaHost] = []
    if isinstance(media_conn.content, list):
        for child in media_conn.content:
            if child.tag != "host":
                continue
            hosts.append(
                MediaHost(
                    hostname=child.attrs["hostname"],
                    max_content_length_bytes=int(child.attrs["maxContentLengthBytes"])
                    if child.attrs.get("maxContentLengthBytes")
                    else None,
                )
            )
    if not hosts:
        raise ValueError(f"media_conn response has no hosts: {node!r}")
    return MediaConn(auth=media_conn.attrs["auth"], ttl=int(media_conn.attrs["ttl"]), hosts=hosts)


def encrypt_media(data: bytes, media_type: str, *, media_key: bytes | None = None) -> EncryptedMedia:
    media_key = media_key or __import__("os").urandom(32)
    keys = derive_media_keys(media_key, media_type)
    ciphertext = aes_encrypt_cbc(data, keys.cipher_key, keys.iv)
    mac = hmac_sign(keys.iv + ciphertext, keys.mac_key)[:10]
    encrypted = ciphertext + mac
    return EncryptedMedia(
        media_key=media_key,
        encrypted=encrypted,
        mac=mac,
        file_sha256=sha256(data),
        file_enc_sha256=sha256(encrypted),
        file_length=len(data),
    )


def decrypt_media(encrypted: bytes, media_key: bytes, media_type: str) -> bytes:
    if len(encrypted) < 11:
        raise ValueError("encrypted media too short")
    keys = derive_media_keys(media_key, media_type)
    ciphertext = encrypted[:-10]
    mac = encrypted[-10:]
    expected = hmac_sign(keys.iv + ciphertext, keys.mac_key)[:10]
    if mac != expected:
        raise ValueError("invalid media mac")
    return aes_decrypt_cbc(ciphertext, keys.cipher_key, keys.iv)


def media_retry_key(media_key: bytes) -> bytes:
    return hkdf(media_key, 32, info=b"WhatsApp Media Retry Notification")


def encrypt_media_retry_request(key: Any, media_key: bytes, me_id: str) -> BinaryNode:
    message_id = _message_key_value(key, "id")
    remote_jid = _message_key_value(key, "remote_jid", "remoteJid")
    if not message_id:
        raise ValueError("media retry request requires message key id")
    if not remote_jid:
        raise ValueError("media retry request requires remote jid")

    receipt = proto.ServerErrorReceipt()
    receipt.stanzaId = message_id
    iv = random_bytes(12)
    ciphertext = aes_encrypt_gcm(receipt.SerializeToString(), media_retry_key(media_key), iv, message_id.encode())
    rmr_attrs = {
        "jid": remote_jid,
        "from_me": str(bool(_message_key_value(key, "from_me", "fromMe"))).lower(),
    }
    participant = _message_key_value(key, "participant")
    if participant:
        rmr_attrs["participant"] = participant
    return BinaryNode(
        "receipt",
        {"id": message_id, "to": jid_normalized_user(me_id), "type": "server-error"},
        [
            BinaryNode("encrypt", {}, [BinaryNode("enc_p", {}, ciphertext), BinaryNode("enc_iv", {}, iv)]),
            BinaryNode("rmr", rmr_attrs),
        ],
    )


def decode_media_retry_node(node: BinaryNode) -> MediaRetryEvent | None:
    rmr = find_child(node, "rmr")
    if rmr is None:
        return None
    key = {
        "id": node.attrs.get("id"),
        "remote_jid": rmr.attrs.get("jid"),
        "from_me": rmr.attrs.get("from_me") == "true",
        "participant": rmr.attrs.get("participant"),
    }
    error = find_child(node, "error")
    if error is not None:
        code = error.attrs.get("code", "")
        return MediaRetryEvent(key=key, error=ValueError(f"failed to re-upload media ({code})"))
    encrypted = find_child(node, "encrypt")
    ciphertext = _child_bytes(encrypted, "enc_p") if encrypted is not None else None
    iv = _child_bytes(encrypted, "enc_iv") if encrypted is not None else None
    if ciphertext is None or iv is None:
        return MediaRetryEvent(key=key, error=ValueError("failed to re-upload media (missing ciphertext)"))
    return MediaRetryEvent(key=key, media={"ciphertext": ciphertext, "iv": iv})


def decrypt_media_retry_data(media: dict[str, bytes], media_key: bytes, message_id: str) -> proto.MediaRetryNotification:
    plaintext = aes_decrypt_gcm(media["ciphertext"], media_retry_key(media_key), media["iv"], message_id.encode())
    return proto.MediaRetryNotification.FromString(plaintext)


def encrypt_media_retry_response(
    media_key: bytes,
    message_id: str,
    direct_path: str,
    *,
    result: int | None = None,
    message_secret: bytes | None = None,
    iv: bytes | None = None,
) -> dict[str, bytes]:
    notification = proto.MediaRetryNotification()
    notification.stanzaId = message_id
    notification.directPath = direct_path
    notification.result = proto.MediaRetryNotification.ResultType.SUCCESS if result is None else result
    if message_secret is not None:
        notification.messageSecret = message_secret
    actual_iv = iv or random_bytes(12)
    ciphertext = aes_encrypt_gcm(notification.SerializeToString(), media_retry_key(media_key), actual_iv, message_id.encode())
    return {"ciphertext": ciphertext, "iv": actual_iv}


def media_retry_status_code(result: int) -> int | None:
    return {
        proto.MediaRetryNotification.ResultType.SUCCESS: 200,
        proto.MediaRetryNotification.ResultType.DECRYPTION_ERROR: 412,
        proto.MediaRetryNotification.ResultType.NOT_FOUND: 404,
        proto.MediaRetryNotification.ResultType.GENERAL_ERROR: 418,
    }.get(result)


def upload_token(file_enc_sha256: bytes) -> str:
    return base64.b64encode(file_enc_sha256).decode("ascii").replace("+", "-").replace("/", "_").rstrip("=")


async def upload_media(
    encrypted: bytes,
    media_conn: MediaConn,
    file_enc_sha256: bytes,
    media_type: str,
    *,
    timeout: int = 45,
) -> MediaUploadResult:
    token = upload_token(file_enc_sha256)
    path = MEDIA_PATH_MAP[media_type]
    headers = {"Content-Type": "application/octet-stream", "Origin": DEFAULT_ORIGIN}
    last_error: Exception | None = None
    for host in media_conn.hosts:
        auth = __import__("urllib.parse").parse.quote(media_conn.auth, safe="")
        url = f"https://{host.hostname}{path}/{token}?auth={auth}&token={token}"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.post(url, data=encrypted, headers=headers) as response:
                    text = await response.text()
                    if response.status >= 400:
                        raise ValueError(f"upload failed status={response.status} body={text[:200]}")
                    payload = await response.json(content_type=None)
            media_url = payload.get("url") or ""
            direct_path = payload.get("direct_path") or ""
            if media_url and direct_path:
                return MediaUploadResult(media_url=media_url, direct_path=direct_path, host=host.hostname, raw=payload)
            if payload.get("fbid") and (payload.get("meta_hmac") or payload.get("hmac")):
                return MediaUploadResult(
                    host=host.hostname,
                    fbid=str(payload["fbid"]),
                    meta_hmac=str(payload.get("meta_hmac") or payload.get("hmac")),
                    timestamp=str(payload.get("ts") or payload.get("timestamp") or ""),
                    raw=payload,
                )
            raise ValueError(f"upload response missing media identifiers: {payload!r}")
        except Exception as exc:
            last_error = exc
    raise ValueError(f"media upload failed on all hosts: {last_error}") from last_error


async def upload_raw_media(
    data: bytes,
    media_conn: MediaConn,
    file_sha256: bytes,
    media_type: str,
    *,
    timeout: int = 45,
) -> MediaUploadResult:
    token = upload_token(file_sha256)
    path = MEDIA_PATH_MAP[media_type]
    headers = {"Content-Type": "application/octet-stream", "Origin": DEFAULT_ORIGIN}
    last_error: Exception | None = None
    for host in media_conn.hosts:
        auth = __import__("urllib.parse").parse.quote(media_conn.auth, safe="")
        url = f"https://{host.hostname}{path}/{token}?auth={auth}&token={token}"
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.post(url, data=data, headers=headers) as response:
                    text = await response.text()
                    if response.status >= 400:
                        raise ValueError(f"upload failed status={response.status} body={text[:200]}")
                    payload = await response.json(content_type=None)
            media_url = payload.get("url") or ""
            direct_path = payload.get("direct_path") or ""
            if media_url or direct_path:
                return MediaUploadResult(media_url=media_url, direct_path=direct_path, host=host.hostname, raw=payload)
            raise ValueError(f"upload response missing media identifiers: {payload!r}")
        except Exception as exc:
            last_error = exc
    raise ValueError(f"raw media upload failed on all hosts: {last_error}") from last_error


def media_url_from_direct_path(direct_path: str, host: str = "mmg.whatsapp.net") -> str:
    return direct_path if direct_path.startswith(("http://", "https://")) else f"https://{host}{direct_path}"


async def download_media(upload: MediaUploadResult, *, timeout: int = 45) -> bytes:
    url = upload.media_url or f"https://{upload.host}{upload.direct_path}"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.get(url, headers={"Origin": DEFAULT_ORIGIN}) as response:
            data = await response.read()
            if response.status >= 400:
                raise ValueError(f"download failed status={response.status} body={data[:200]!r}")
            return data


async def download_external_blob(blob: proto.ExternalBlobReference, media_type: str = "md-app-state", *, timeout: int = 45) -> bytes:
    if not blob.mediaKey:
        raise ValueError("external blob missing media key")
    if not blob.directPath:
        raise ValueError("external blob missing direct path")
    encrypted = await download_direct_path(blob.directPath, timeout=timeout)
    if blob.fileEncSha256 and sha256(encrypted) != blob.fileEncSha256:
        raise ValueError("external blob encrypted hash mismatch")
    return decrypt_media(encrypted, blob.mediaKey, media_type)


async def download_direct_path(direct_path: str, *, timeout: int = 45) -> bytes:
    url = direct_path if direct_path.startswith(("http://", "https://")) else f"https://mmg.whatsapp.net{direct_path}"
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
        async with session.get(url, headers={"Origin": DEFAULT_ORIGIN}) as response:
            data = await response.read()
            if response.status >= 400:
                raise ValueError(f"download failed status={response.status} body={data[:200]!r}")
            return data


def image_message(
    encrypted: EncryptedMedia,
    upload: MediaUploadResult,
    *,
    mimetype: str,
    width: int,
    height: int,
    caption: str = "",
) -> proto.Message:
    message = proto.Message()
    image = message.imageMessage
    image.url = upload.media_url
    image.mimetype = mimetype
    image.caption = caption
    image.fileSha256 = encrypted.file_sha256
    image.fileEncSha256 = encrypted.file_enc_sha256
    image.fileLength = encrypted.file_length
    image.height = height
    image.width = width
    image.mediaKey = encrypted.media_key
    image.directPath = upload.direct_path
    image.mediaKeyTimestamp = int(time.time())
    return message


def read_media_payload(
    source: bytes | bytearray | str | Path,
    media_type: str,
    *,
    mimetype: str | None = None,
    filename: str | None = None,
    caption: str = "",
    width: int = 0,
    height: int = 0,
    seconds: int = 0,
    ptt: bool = False,
) -> MediaPayload:
    if media_type not in MEDIA_PATH_MAP:
        raise ValueError(f"unsupported media type: {media_type}")
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        guessed_name = filename
    else:
        path = Path(source)
        data = path.read_bytes()
        guessed_name = filename or path.name
    guessed_type = mimetype or (mimetypes.guess_type(guessed_name or "")[0] if guessed_name else None)
    return MediaPayload(
        data=data,
        media_type=media_type,
        mimetype=guessed_type or _default_mimetype(media_type),
        filename=guessed_name,
        caption=caption,
        width=width,
        height=height,
        seconds=seconds,
        ptt=ptt,
    )


def media_message(
    encrypted: EncryptedMedia,
    upload: MediaUploadResult,
    payload: MediaPayload,
) -> proto.Message:
    message = proto.Message()
    target = getattr(message, f"{payload.media_type}Message")
    target.url = upload.media_url
    target.mimetype = payload.mimetype
    target.fileSha256 = encrypted.file_sha256
    target.fileEncSha256 = encrypted.file_enc_sha256
    target.fileLength = encrypted.file_length
    target.mediaKey = encrypted.media_key
    target.directPath = upload.direct_path
    target.mediaKeyTimestamp = int(time.time())
    if payload.caption and hasattr(target, "caption"):
        target.caption = payload.caption
    if payload.filename and hasattr(target, "fileName"):
        target.fileName = payload.filename
    if payload.filename and hasattr(target, "title"):
        target.title = payload.filename
    if payload.width and hasattr(target, "width"):
        target.width = payload.width
    if payload.height and hasattr(target, "height"):
        target.height = payload.height
    if payload.seconds and hasattr(target, "seconds"):
        target.seconds = payload.seconds
    if payload.ptt and hasattr(target, "ptt"):
        target.ptt = True
    return message


def _default_mimetype(media_type: str) -> str:
    return {
        "image": "image/jpeg",
        "video": "video/mp4",
        "audio": "audio/ogg",
        "biz-cover-photo": "image/jpeg",
        "document": "application/octet-stream",
        "sticker": "image/webp",
    }[media_type]


def _message_key_value(key: Any, *names: str) -> Any:
    if isinstance(key, dict):
        for name in names:
            if name in key:
                return key[name]
        return None
    for name in names:
        if hasattr(key, name):
            return getattr(key, name)
    return None


def _child_bytes(node: BinaryNode, tag: str) -> bytes | None:
    child = find_child(node, tag)
    return child.content if child is not None and isinstance(child.content, bytes) else None
