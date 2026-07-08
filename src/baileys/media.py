from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
import time
from dataclasses import dataclass
from typing import Any, Iterable

import aiohttp

from baileys.crypto import aes_decrypt_cbc, aes_encrypt_cbc, hmac_sign, sha256
from baileys.defaults import DEFAULT_ORIGIN, MEDIA_PATH_MAP, S_WHATSAPP_NET
from baileys.generated import WAProto_pb2 as proto
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
    media_url: str
    direct_path: str
    host: str


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
            media_url = payload.get("url")
            direct_path = payload.get("direct_path")
            if media_url and direct_path:
                return MediaUploadResult(media_url=media_url, direct_path=direct_path, host=host.hostname)
            raise ValueError(f"upload response missing url/direct_path: {payload!r}")
        except Exception as exc:
            last_error = exc
    raise ValueError(f"media upload failed on all hosts: {last_error}") from last_error


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
        "document": "application/octet-stream",
        "sticker": "image/webp",
    }[media_type]
