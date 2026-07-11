from __future__ import annotations

import asyncio
import base64
import copy
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import websockets

from .auth_state import AuthState, JsonCredentialStore, MultiFileAuthState
from .app_state import (
    AppliedAppStateSync,
    AppStateSnapshotInfo,
    MissingAppStateKey,
    WA_PATCH_NAMES,
    apply_app_state_sync,
    app_state_patch_node,
    app_state_sync_request_node,
    app_state_sync_key_request_message,
    extract_app_state_sync_data,
    extract_app_state_snapshot_info,
    inject_app_state_sync_key_share,
)
from .client import WhatsAppWebClient
from .crypto import sha256
from .disconnect import (
    DisconnectError,
    DisconnectReason,
    disconnect_update,
    failure_to_disconnect,
    logged_out_disconnect,
    stream_error_to_disconnect,
)
from .generated import WAProto_pb2 as proto
from .history import download_and_process_history_sync_notification, get_history_sync_notification
from .noise import NoiseHandshake
from .registration import build_registration_payload
from .defaults import DEFAULT_ORIGIN, DEFAULT_USER_AGENT, INITIAL_PREKEY_COUNT, MIN_PREKEY_COUNT, S_WHATSAPP_NET, WA_WEBSOCKET_URL
from .events import EventEmitter
from .chat_groups import (
    GroupMetadata,
    ParticipantUpdateResult,
    available_presence_node,
    block_status_node,
    blocklist_fetch_node,
    chatstate_presence_node,
    default_disappearing_mode_node,
    dirty_clean_node,
    group_accept_invite_node,
    group_create_node,
    group_get_invite_info_node,
    group_invite_code_node,
    group_join_approval_mode_node,
    group_leave_node,
    group_member_add_mode_node,
    group_metadata_node,
    group_participants_update_node,
    group_revoke_invite_node,
    group_setting_update_node,
    group_toggle_ephemeral_node,
    group_update_description_node,
    group_update_subject_node,
    on_whatsapp_node,
    parse_accept_invite,
    parse_blocklist,
    parse_usync_disappearing_mode,
    parse_group_metadata,
    parse_invite_code,
    parse_on_whatsapp,
    parse_participant_update,
    parse_privacy_settings,
    parse_profile_picture_url,
    parse_usync_status,
    presence_subscribe_node,
    privacy_fetch_node,
    privacy_update_node,
    profile_picture_remove_node,
    profile_picture_update_node,
    profile_picture_url_node,
    profile_status_update_node,
    usync_disappearing_mode_node,
    usync_status_node,
)
from .business import (
    BusinessProfile,
    CatalogResult,
    business_profile_node,
    catalog_node,
    collections_node,
    cover_photo_remove_node,
    cover_photo_update_node,
    order_details_node,
    parse_catalog,
    parse_business_profile,
    parse_product_mutation,
    parse_product_delete,
    product_create_node,
    product_delete_node,
    product_update_node,
    update_business_profile_node,
)
from .communities import (
    community_accept_invite_node,
    community_accept_invite_v4_node,
    community_create_group_node,
    community_create_node,
    community_ephemeral_node,
    community_invite_code_node,
    community_invite_info_node,
    community_join_approval_mode_node,
    community_leave_node,
    community_link_group_node,
    community_linked_groups_node,
    community_member_add_mode_node,
    community_membership_requests_node,
    community_membership_requests_update_node,
    community_metadata_node,
    community_participants_update_node,
    community_revoke_invite_node,
    community_revoke_invite_v4_node,
    community_setting_update_node,
    community_unlink_group_node,
    community_update_description_node,
    community_update_subject_node,
    parse_community_accept_invite,
    parse_community_invite_code,
    parse_community_linked_groups,
    parse_community_metadata,
    parse_community_participant_update,
    parse_membership_request_update,
    parse_membership_requests,
)
from .media import (
    MediaConn,
    MediaPayload,
    MediaRetryEvent,
    MediaUploadResult,
    decode_media_retry_node,
    decrypt_media,
    decrypt_media_retry_data,
    download_external_blob,
    download_media,
    encrypt_media,
    encrypt_media_retry_request,
    media_conn_node,
    media_message,
    media_retry_status_code,
    media_url_from_direct_path,
    parse_media_conn,
    read_media_payload,
    upload_raw_media,
    upload_media,
)
from .message_send import OutboundMessage, build_message_content_node, build_proto_message_node
from .mex import QUERY_IDS, XWA_PATHS, parse_wmex_result, wmex_query_node
from .newsletter import (
    NewsletterMetadata,
    newsletter_create_query,
    newsletter_fetch_messages_node,
    newsletter_live_updates_node,
    newsletter_metadata_query,
    newsletter_owner_query,
    newsletter_reaction_node,
    newsletter_simple_query,
    newsletter_update_query,
    parse_newsletter_notification_events,
    parse_live_update_duration,
    parse_newsletter_metadata,
)
from .jid import is_jid_group, is_lid, is_newsletter, is_pn, jid_decode_tuple, jid_encode, jid_normalized_user, phone_number_to_jid
from .noise import generate_noise_key_pair
from .pairing_code import (
    PairSuccess,
    PairingCodeRequest,
    QRPairingRequest,
    build_pairing_qr_data,
    configure_successful_pairing,
    extract_pair_device_refs,
    pair_device_ack_node,
    pairing_code_request_node,
)
from .prekeys import (
    PreKeyMaintenanceResult,
    PreKeyNodeResult,
    SignedPreKeyRotation,
    build_prekey_upload_node,
    digest_key_bundle_node,
    parse_prekey_count,
    prekey_count_node,
    rotate_signed_pre_key_node,
)
from .privacy_tokens import store_tc_tokens_from_iq_result
from .query import QueryManager
from .receipts import (
    RetryOutcome,
    RetryRequest,
    aggregate_message_keys,
    build_ack_node,
    build_receipt_node,
    can_ack_node,
    parse_receipt_info,
    parse_retry_request,
)
from .retry import RetrySessionBundle, inject_retry_session_from_receipt
from .session_assert import encrypt_session_query_node, inject_sessions_from_encrypt_result
from .socket_nodes import (
    SocketNodeKind,
    IQError,
    classify_node,
    client_ping_node,
    find_child,
    logout_node,
    offline_batch_node,
    passive_active_node,
    raise_for_iq_error,
    server_ping_reply,
    unified_session_node,
)
from .store import InMemoryStore
from .usync import DeviceInfo, conversation_identities, extract_device_jids, parse_usync_result, split_own_and_other_devices, usync_devices_query_node
from .wam import WAMBinaryInfo, encode_wam
from .wabinary import BinaryNode
from .messages import MessageKey, WAMessage, build_message_upsert
from .notifications import (
    CallInfo,
    DirtyInfo,
    NotificationInfo,
    OfflineInfo,
    parse_call_info,
    parse_dirty_info,
    parse_notification_info,
    parse_offline_info,
)


@dataclass(frozen=True)
class ReconnectPolicy:
    enabled: bool = True
    max_attempts: int = 5
    initial_delay: float = 1
    max_delay: float = 30
    multiplier: float = 2
    retry_status_codes: tuple[int, ...] = (
        int(DisconnectReason.connectionClosed),
        int(DisconnectReason.connectionLost),
        int(DisconnectReason.restartRequired),
        int(DisconnectReason.unavailableService),
    )

    def delay_for_attempt(self, attempt: int) -> float:
        if attempt <= 1:
            return self.initial_delay
        return min(self.initial_delay * (self.multiplier ** (attempt - 1)), self.max_delay)

    def should_reconnect(self, error: Exception | None) -> bool:
        if not self.enabled or self.max_attempts <= 0:
            return False
        if error is None:
            return False
        if isinstance(error, DisconnectError):
            return int(error.status_code) in self.retry_status_codes
        return True


@dataclass(frozen=True)
class SocketConfig:
    websocket_url: str = WA_WEBSOCKET_URL
    origin: str = DEFAULT_ORIGIN
    user_agent: str = DEFAULT_USER_AGENT
    use_routing_info: bool = True
    auto_ack: bool = True
    auto_prekey_maintenance: bool = True
    reconnect_policy: ReconnectPolicy = field(default_factory=ReconnectPolicy)
    max_msg_retry_count: int = 5


@dataclass(frozen=True)
class SendMessageResult:
    message_id: str
    remote_jid: str
    message_type: str
    participant_jids: list[str]
    signal_types: dict[str, str]
    acked: bool = False
    node: BinaryNode | None = None


@dataclass(frozen=True)
class MediaSendResult:
    send: SendMessageResult
    payload: MediaPayload
    media_key: bytes
    direct_path: str
    media_url: str


def _normalize_session_jid(raw_jid: str) -> str:
    value = str(raw_jid).strip()
    if "@" not in value and value.count(":") == 1:
        user, suffix = value.split(":", 1)
        if suffix and not suffix.isdigit():
            return f"{user}@{suffix}"
    return value


def _session_key_for_jid(raw_jid: str) -> str:
    value = _normalize_session_jid(raw_jid)
    left = value.split("@", 1)[0]
    if not left:
        return ""
    user, sep, device = left.partition(":")
    if not user:
        return ""
    if sep and device.isdigit():
        return f"{user}:{int(device)}"
    return f"{user}:0"


def _coerce_chat_jid(raw_jid: str) -> str:
    value = _normalize_session_jid(raw_jid)
    return phone_number_to_jid(value) if "@" not in value else value


def _dedupe_jids(jids: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for jid in jids:
        normalized = _normalize_session_jid(jid)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


class WhatsAppClient:
    def __init__(
        self,
        auth: AuthState | MultiFileAuthState | str | Path,
        *,
        websocket_url: str = WA_WEBSOCKET_URL,
        origin: str = DEFAULT_ORIGIN,
        user_agent: str = DEFAULT_USER_AGENT,
        use_routing_info: bool = True,
        auto_ack: bool = True,
        auto_prekey_maintenance: bool = True,
        auto_reconnect: bool = True,
        reconnect_max_attempts: int = 5,
        reconnect_initial_delay: float = 1,
        reconnect_max_delay: float = 30,
        reconnect_multiplier: float = 2,
        max_msg_retry_count: int = 5,
    ) -> None:
        self.auth_state = _coerce_auth_state(auth)
        self.config = SocketConfig(
            websocket_url=websocket_url,
            origin=origin,
            user_agent=user_agent,
            use_routing_info=use_routing_info,
            auto_ack=auto_ack,
            auto_prekey_maintenance=auto_prekey_maintenance,
            reconnect_policy=ReconnectPolicy(
                enabled=auto_reconnect,
                max_attempts=reconnect_max_attempts,
                initial_delay=reconnect_initial_delay,
                max_delay=reconnect_max_delay,
                multiplier=reconnect_multiplier,
            ),
            max_msg_retry_count=max_msg_retry_count,
        )
        self.ev = EventEmitter()
        self.events = self.ev
        self.store = InMemoryStore()
        self.store.bind(self.ev)
        self.queries = QueryManager()
        self._web: WhatsAppWebClient | None = None
        self._receive_task: Any = None
        self._closing = False
        self._qr_static_noise: Any = None
        self._qr_meta: dict[str, Any] | None = None
        self._keepalive_task: Any = None
        self._reconnect_task: Any = None
        self._last_disconnect_error: DisconnectError | None = None
        self._server_time_offset_ms = 0
        self._message_retry_counts: dict[tuple[str, str | None], int] = {}
        self._recent_outbound: dict[str, BinaryNode] = {}
        self._media_conn: MediaConn | None = None
        self._media_conn_expires_at = 0.0

    @property
    def creds(self) -> dict[str, Any]:
        return self.auth_state.credentials

    @property
    def websocket_url(self) -> str:
        return self.config.websocket_url

    @property
    def origin(self) -> str:
        return self.config.origin

    async def __aenter__(self) -> "WhatsAppClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self, *, open_timeout: float = 20, close_timeout: float = 5) -> None:
        creds_path = _credential_path(self.auth_state)
        if creds_path is None:
            raise ValueError("connect currently requires AuthState backed by JsonCredentialStore")

        await self.ev.emit("connection.update", {"connection": "connecting"})
        web = WhatsAppWebClient(
            creds_path,
            websocket_url=self.config.websocket_url,
            origin=self.config.origin,
            user_agent=self.config.user_agent,
            use_routing_info=self.config.use_routing_info,
        )
        try:
            await web.connect(open_timeout=open_timeout, close_timeout=close_timeout)
        except Exception as exc:
            await self.ev.emit("connection.update", {"connection": "close", "last_disconnect": exc})
            raise

        self._web = web
        self._closing = False
        self._last_disconnect_error = None
        if web.creds is not None:
            self.auth_state.credentials = web.creds
            await self.ev.emit("creds.update", self.auth_state.credentials)
        await self.ev.emit("connection.update", {"connection": "open"})

    async def connect_for_qr_pairing(
        self,
        *,
        open_timeout: float = 20,
        close_timeout: float = 5,
        qr_timeout: float = 30,
        ref_index: int = 0,
        acknowledge_pair_device: bool = True,
    ) -> QRPairingRequest:
        creds_path = _credential_path(self.auth_state)
        if creds_path is None:
            raise ValueError("QR pairing currently requires AuthState backed by JsonCredentialStore")

        await self.ev.emit("connection.update", {"connection": "connecting", "pairing": "qr"})
        ephemeral = generate_noise_key_pair()
        static_noise = generate_noise_key_pair()
        noise = NoiseHandshake(ephemeral)
        websocket = await websockets.connect(
            self.config.websocket_url,
            origin=self.config.origin,
            open_timeout=open_timeout,
            close_timeout=close_timeout,
            ping_interval=None,
            additional_headers={"User-Agent": self.config.user_agent},
        )
        try:
            await websocket.send(noise.client_hello_frame())
            response = await asyncio.wait_for(websocket.recv(), timeout=open_timeout)
            if isinstance(response, str):
                response = response.encode("latin1")
            server_hello_payload = response[3 : 3 + int.from_bytes(response[:3], "big")]
            info = noise.process_server_hello(server_hello_payload, static_noise)

            registration_payload, meta = build_registration_payload()
            finish = proto.HandshakeMessage()
            finish.clientFinish.static = info.encrypted_static_key
            finish.clientFinish.payload = noise.encrypt(registration_payload)
            await websocket.send(noise.encode_frame(finish.SerializeToString()))
            noise.finish_init()
        except Exception as exc:
            await websocket.close()
            await self.ev.emit("connection.update", {"connection": "close", "last_disconnect": exc})
            raise

        web = WhatsAppWebClient(
            creds_path,
            websocket_url=self.config.websocket_url,
            origin=self.config.origin,
            user_agent=self.config.user_agent,
            use_routing_info=False,
        )
        web.websocket = websocket
        web.noise = noise
        self._web = web
        self._closing = False
        self._last_disconnect_error = None
        self._qr_static_noise = static_noise
        self._qr_meta = meta

        deadline = asyncio.get_running_loop().time() + qr_timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for pair-device refs")
            nodes = await self.receive_nodes(timeout=min(30, remaining))
            for node in nodes:
                refs = extract_pair_device_refs(node)
                if not refs.refs:
                    continue
                if acknowledge_pair_device:
                    await self.send_node(pair_device_ack_node(node))
                ref = refs.refs[ref_index]
                qr = build_pairing_qr_data(
                    ref=ref,
                    noise_key=static_noise.public,
                    identity_key=bytes(meta["identity_public"]),
                    adv_secret_key=str(meta["adv_secret_key"]),
                )
                request = QRPairingRequest(node=node, refs=refs.refs, qr=qr)
                await self.ev.emit("connection.update", {"connection": "qr", "qr": qr, "pairing_refs": refs.refs})
                return request

    async def connect_and_wait(
        self,
        *,
        open_timeout: float = 20,
        close_timeout: float = 5,
        success_timeout: float = 60,
        start_receive_loop: bool = False,
        initialize: bool = True,
    ) -> BinaryNode:
        await self.connect(open_timeout=open_timeout, close_timeout=close_timeout)
        node = await self.wait_for_success(timeout=success_timeout, initialize=initialize)
        if start_receive_loop:
            self.start_receive_loop()
        return node

    async def reconnect(
        self,
        *,
        open_timeout: float = 20,
        close_timeout: float = 5,
        wait_for_success: bool = False,
        success_timeout: float = 60,
        start_receive_loop: bool = False,
    ) -> BinaryNode | None:
        await self.close()
        if wait_for_success:
            return await self.connect_and_wait(
                open_timeout=open_timeout,
                close_timeout=close_timeout,
                success_timeout=success_timeout,
                start_receive_loop=start_receive_loop,
            )
        await self.connect(open_timeout=open_timeout, close_timeout=close_timeout)
        if start_receive_loop:
            self.start_receive_loop()
        return None

    async def close(self, error: DisconnectError | None = None) -> None:
        self._closing = True
        self._last_disconnect_error = error
        current_task = asyncio.current_task()
        if self._reconnect_task is not None and self._reconnect_task is not current_task:
            if not self._reconnect_task.done():
                self._reconnect_task.cancel()
                try:
                    await self._reconnect_task
                except asyncio.CancelledError:
                    pass
            self._reconnect_task = None
        if self._receive_task is not current_task:
            await self.stop_receive_loop()
        else:
            self._receive_task = None
        if self._keepalive_task is not current_task:
            await self.stop_keepalive_loop()
        else:
            self._keepalive_task = None
        self.queries.cancel_all()
        if self._web is not None:
            close = getattr(self._web, "close", None)
            if close is not None:
                await close()
            self._web = None
        await self.ev.emit("connection.update", disconnect_update(error) if error is not None else {"connection": "close"})

    async def logout(self, message: str = "Intentional Logout", *, clear_auth: bool = True) -> None:
        jid = _me_id(self.auth_state.credentials)
        if jid:
            await self.send_node(logout_node(jid, self.queries.next_tag()))
        if clear_auth:
            await self._clear_credentials()
        await self.close(logged_out_disconnect(message))

    async def send_node(self, node: BinaryNode) -> None:
        if self._web is None:
            raise RuntimeError("client is not connected")
        await self._web.send_node(node)

    async def send_wam_buffer(self, wam_buffer: bytes, *, timeout: float = 30) -> BinaryNode:
        return await self._query_checked(
            BinaryNode(
                "iq",
                {"to": S_WHATSAPP_NET, "id": self.queries.next_tag(), "xmlns": "w:stats"},
                [BinaryNode("add", {"t": str(round(time.time()))}, wam_buffer)],
            ),
            timeout=timeout,
        )

    async def send_wam(self, binary_info: WAMBinaryInfo, *, timeout: float = 30) -> BinaryNode:
        return await self.send_wam_buffer(encode_wam(binary_info), timeout=timeout)

    async def query(self, node: BinaryNode, *, timeout: float = 30, drive_receive: bool = False) -> BinaryNode:
        tag_id = node.attrs.get("id")
        if not tag_id:
            tag_id = self.queries.next_tag()
            node.attrs["id"] = tag_id

        waiter = self.queries.create_waiter(tag_id)
        try:
            await self.send_node(node)
            if drive_receive:
                deadline = asyncio.get_running_loop().time() + timeout
                while not waiter.done():
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    await self.receive_nodes(timeout=min(5, remaining))
            return await self.queries.wait_for(tag_id, timeout=timeout)
        except Exception:
            if not waiter.done():
                waiter.cancel()
            self.queries.discard(tag_id)
            raise

    async def _query_checked(self, node: BinaryNode, *, timeout: float = 30, drive_receive: bool = True) -> BinaryNode:
        result = await self.query(node, timeout=timeout, drive_receive=drive_receive)
        raise_for_iq_error(result)
        return result

    async def receive_nodes(self, timeout: float = 30) -> list[BinaryNode]:
        if self._web is None:
            raise RuntimeError("client is not connected")
        nodes = await self._web.receive_nodes(timeout=timeout)
        for node in nodes:
            await self.dispatch_node(node)
        return nodes

    async def dispatch_node(self, node: BinaryNode) -> SocketNodeKind:
        kind = classify_node(node)
        if kind == SocketNodeKind.SERVER_PING:
            await self.send_node(server_ping_reply(node))
        elif kind == SocketNodeKind.OFFLINE_PREVIEW:
            await self.send_node(offline_batch_node())
            await self.dispatch_offline_node(node)
        elif kind == SocketNodeKind.OFFLINE:
            await self.dispatch_offline_node(node)
        elif kind == SocketNodeKind.DIRTY:
            await self.dispatch_dirty_node(node)
        elif kind == SocketNodeKind.STREAM_ERROR:
            await self.close(stream_error_to_disconnect(node))
        elif kind == SocketNodeKind.FAILURE:
            await self.close(failure_to_disconnect(node))
        if self._qr_static_noise is not None and self._qr_meta is not None:
            from .socket_nodes import find_child

            if find_child(node, "pair-success") is not None:
                await self.finalize_pair_success(node, static_noise=self._qr_static_noise, meta=self._qr_meta)
        if kind == SocketNodeKind.MESSAGE:
            await self.dispatch_message_node(node)
        elif kind == SocketNodeKind.RECEIPT:
            await self.dispatch_receipt_node(node)
            await self.send_ack(node)
        elif kind == SocketNodeKind.NOTIFICATION:
            await self.dispatch_notification_node(node)
            await self.send_ack(node)
        elif kind == SocketNodeKind.CALL:
            await self.dispatch_call_node(node)
            await self.send_ack(node)
        if not self.queries.resolve(node):
            await self.ev.emit("node", node)
            await self.ev.emit(f"node.{kind.value}", node)
        return kind

    async def dispatch_message_node(self, node: BinaryNode) -> None:
        creds_path = _credential_path(self.auth_state)
        try:
            upsert = build_message_upsert(node, self.auth_state.credentials, persist_creds_path=creds_path)
        except Exception as exc:
            await self.send_ack(node, error_code=500)
            await self.ev.emit("messages.decrypt_error", {"node": node, "error": exc})
            return
        if upsert is not None:
            key_ids = []
            for message in upsert.messages:
                if message.message is not None:
                    key_ids.extend(inject_app_state_sync_key_share(self.auth_state.credentials, message.message))
                    history_notification = get_history_sync_notification(message.message)
                    if history_notification is not None:
                        try:
                            history = await download_and_process_history_sync_notification(history_notification, timeout=45)
                        except Exception as exc:
                            await self.ev.emit("messaging-history.error", {"message": message, "error": exc})
                        else:
                            await self.ev.emit("messaging-history.set", history)
            if key_ids:
                await self._record_app_state_key_updates(key_ids)
            await self.send_ack(node)
            await self.ev.emit("messages.upsert", upsert)

    async def _record_app_state_key_updates(self, key_ids: list[str]) -> list[str]:
        blocked = self.auth_state.credentials.get("app_state_blocked_collections") or {}
        unblocked = [collection for collection, key_id in list(blocked.items()) if key_id in key_ids]
        for collection in unblocked:
            blocked.pop(collection, None)
        await self._commit_credentials(self.auth_state.credentials)
        await self.ev.emit("app-state.keys.update", {"key_ids": key_ids, "unblocked_collections": unblocked})
        return unblocked

    async def dispatch_notification_node(self, node: BinaryNode) -> NotificationInfo | None:
        info = parse_notification_info(node)
        if info is None:
            await self.ev.emit("notifications.error", {"node": node, "reason": "invalid_notification"})
            return None
        await self.ev.emit("notifications.upsert", info)
        await self.ev.emit(f"notifications.{info.category}", info)
        if info.category == "newsletter" or info.type in {"newsletter", "mex"} or (info.from_jid and is_newsletter(info.from_jid)):
            for event, payload in parse_newsletter_notification_events(node):
                await self.ev.emit(event, payload)
        return info

    async def dispatch_dirty_node(self, node: BinaryNode) -> DirtyInfo | None:
        info = parse_dirty_info(node)
        if info is None:
            await self.ev.emit("app-state.dirty_error", {"node": node, "reason": "missing_dirty_child"})
            return None
        await self.ev.emit("app-state.dirty", info)
        return info

    async def dispatch_offline_node(self, node: BinaryNode) -> OfflineInfo | None:
        info = parse_offline_info(node)
        if info is None:
            await self.ev.emit("offline.error", {"node": node, "reason": "missing_offline_child"})
            return None
        event = "offline.preview" if info.preview else "offline.update"
        await self.ev.emit(event, info)
        if not info.preview:
            await self.ev.emit("connection.update", {"connection": "open", "received_pending_notifications": True})
        return info

    async def dispatch_call_node(self, node: BinaryNode) -> CallInfo | None:
        info = parse_call_info(node)
        if info is None:
            await self.ev.emit("calls.error", {"node": node, "reason": "invalid_call"})
            return None
        await self.ev.emit("calls.update", [info])
        return info

    async def dispatch_receipt_node(self, node: BinaryNode) -> None:
        media_update = decode_media_retry_node(node)
        if media_update is not None:
            await self.ev.emit("messages.media-update", [media_update])
            return

        retry_request = parse_retry_request(node, self.auth_state.credentials)
        if retry_request is not None:
            await self.dispatch_retry_receipt_node(retry_request)
            return

        info = parse_receipt_info(node, self.auth_state.credentials)
        if info is None or info.status is None:
            return

        if info.is_group_or_status and info.user_jid and info.receipt_timestamp_key:
            updates = [
                {
                    "key": {
                        "remote_jid": info.key.remote_jid,
                        "id": message_id,
                        "from_me": info.key.from_me,
                        "participant": info.key.participant,
                    },
                    "receipt": {
                        "user_jid": info.user_jid,
                        info.receipt_timestamp_key: info.timestamp,
                    },
                }
                for message_id in info.ids
            ]
            await self.ev.emit("message-receipt.update", updates)
        else:
            updates = [
                {
                    "key": {
                        "remote_jid": info.key.remote_jid,
                        "id": message_id,
                        "from_me": info.key.from_me,
                        "participant": info.key.participant,
                    },
                    "update": {
                        "status": info.status,
                        "message_timestamp": info.timestamp,
                    },
                }
                for message_id in info.ids
            ]
            await self.ev.emit("messages.update", updates)

    async def send_message(
        self,
        jid: str,
        content: str | proto.Message | dict[str, Any],
        *,
        message_id: str | None = None,
        use_usync: bool | None = None,
        force_sessions: bool = False,
        include_phash: bool = False,
        timeout: float = 30,
        wait_for_ack: float = 0,
        additional_attributes: dict[str, str] | None = None,
        additional_nodes: list[BinaryNode] | None = None,
    ) -> SendMessageResult:
        outbound = await self._build_outbound_message(
            jid,
            content,
            message_id=message_id,
            use_usync=use_usync,
            force_sessions=force_sessions,
            include_phash=include_phash,
            additional_attributes=additional_attributes,
            additional_nodes=additional_nodes or [],
            timeout=timeout,
        )
        return await self.relay_message(jid, outbound, timeout=wait_for_ack)

    async def relay_message(
        self,
        jid: str,
        message: OutboundMessage | proto.Message | BinaryNode,
        *,
        message_id: str | None = None,
        message_type: str = "text",
        timeout: float = 0,
    ) -> SendMessageResult:
        if isinstance(message, OutboundMessage):
            outbound = message
        elif isinstance(message, proto.Message):
            outbound = build_proto_message_node(
                self.auth_state.credentials,
                jid,
                message,
                message_type=message_type,
                message_id=message_id,
            )
        elif isinstance(message, BinaryNode):
            outbound = OutboundMessage(
                node=message,
                message_id=message.attrs.get("id") or message_id or "",
                signal_type="unknown",
                recipient_address=None,  # type: ignore[arg-type]
                participant_jids=[],
                signal_types={},
            )
        else:
            raise TypeError(f"unsupported relay message type: {type(message).__name__}")

        await self.send_node(outbound.node)
        await self._commit_credentials(self.auth_state.credentials)
        self._recent_outbound[outbound.message_id] = outbound.node
        acked = await self._wait_for_message_ack(outbound.message_id, timeout) if timeout > 0 else False
        await self.ev.emit(
            "messages.send",
            {
                "jid": jid,
                "message_id": outbound.message_id,
                "participant_jids": outbound.participant_jids,
                "acked": acked,
            },
        )
        return SendMessageResult(
            message_id=outbound.message_id,
            remote_jid=jid,
            message_type=outbound.node.attrs.get("type", message_type),
            participant_jids=outbound.participant_jids,
            signal_types=outbound.signal_types,
            acked=acked,
            node=outbound.node,
        )

    async def download_media_message(
        self,
        upload_or_url,
        *,
        media_key: bytes | None = None,
        media_type: str | None = None,
        timeout: int = 45,
    ) -> bytes:
        encrypted = await download_media(upload_or_url, timeout=timeout)
        if media_key is None or media_type is None:
            return encrypted
        return decrypt_media(encrypted, media_key, media_type)

    async def update_media_message(
        self,
        message: WAMessage | proto.WebMessageInfo,
        *,
        timeout: float = 30,
    ) -> WAMessage | proto.WebMessageInfo:
        key, proto_message = _media_retry_message_parts(message)
        content = _media_content_from_message(proto_message)
        media_key = bytes(getattr(content, "mediaKey", b""))
        message_id = _message_key_id(key)
        if not media_key:
            raise ValueError("media message is missing mediaKey")
        if not message_id:
            raise ValueError("media message is missing key id")
        me = self.auth_state.credentials.get("me", {}).get("id")
        if not me:
            raise RuntimeError("cannot update media message before login")

        future: asyncio.Future[MediaRetryEvent] = asyncio.get_running_loop().create_future()

        def on_media_update(payload) -> None:
            updates = payload if isinstance(payload, list) else [payload]
            for update in updates:
                event = _coerce_media_retry_event(update)
                if event is None or event.key.get("id") != message_id:
                    continue
                if not future.done():
                    future.set_result(event)
                return

        listener = self.ev.on("messages.media-update", on_media_update)
        try:
            await self.send_node(encrypt_media_retry_request(key, media_key, me))
            deadline = asyncio.get_running_loop().time() + timeout
            while not future.done():
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise asyncio.TimeoutError()
                try:
                    await self.receive_nodes(timeout=min(5, remaining))
                except (TimeoutError, asyncio.TimeoutError):
                    continue
            update = await future
        finally:
            self.ev.off("messages.media-update", listener)

        if update.error is not None:
            raise update.error
        if update.media is None:
            raise ValueError("media retry update missing media payload")
        retry = decrypt_media_retry_data(update.media, media_key, message_id)
        if retry.result != proto.MediaRetryNotification.ResultType.SUCCESS:
            status = media_retry_status_code(retry.result) or 404
            result_name = proto.MediaRetryNotification.ResultType.Name(retry.result)
            raise ValueError(f"media re-upload failed by device ({result_name}, status={status})")
        if not retry.directPath:
            raise ValueError("media retry update missing direct path")

        content.directPath = retry.directPath
        content.url = media_url_from_direct_path(retry.directPath, self.get_media_host())
        await self.ev.emit(
            "messages.update",
            [{"key": _message_key_dict(key), "update": {"message": proto_message}}],
        )
        return message

    async def send_media_message(
        self,
        jid: str,
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
        timeout: float = 30,
        wait_for_ack: float = 0,
    ) -> MediaSendResult:
        payload = read_media_payload(
            source,
            media_type,
            mimetype=mimetype,
            filename=filename,
            caption=caption,
            width=width,
            height=height,
            seconds=seconds,
            ptt=ptt,
        )
        media_conn = await self._get_media_conn(timeout=timeout)
        encrypted = encrypt_media(payload.data, payload.media_type)
        upload = await upload_media(encrypted.encrypted, media_conn, encrypted.file_enc_sha256, payload.media_type, timeout=int(timeout))
        message = media_message(encrypted, upload, payload)
        send = await self.send_message(jid, message, timeout=timeout, wait_for_ack=wait_for_ack)
        return MediaSendResult(
            send=send,
            payload=payload,
            media_key=encrypted.media_key,
            direct_path=upload.direct_path,
            media_url=upload.media_url,
        )

    async def _build_outbound_message(
        self,
        jid: str,
        content: str | proto.Message | dict[str, Any],
        *,
        message_id: str | None,
        use_usync: bool | None,
        force_sessions: bool,
        include_phash: bool,
        additional_attributes: dict[str, str] | None,
        additional_nodes: list[BinaryNode],
        timeout: float,
    ) -> OutboundMessage:
        jid = _coerce_chat_jid(jid)
        use_usync = is_jid_group(jid) if use_usync is None else use_usync
        own_fanout_jids: list[str] = []
        recipient_device_jids: list[str] | None = None
        if not use_usync and not is_jid_group(jid):
            await self._prepare_direct_session(jid, timeout=timeout, force_sessions=force_sessions)
        if use_usync:
            own_fanout_jids, recipient_device_jids = await self._prepare_usync_fanout(
                jid,
                timeout=timeout,
                force_sessions=force_sessions,
            )
        return build_message_content_node(
            self.auth_state.credentials,
            jid,
            content,
            message_id=message_id,
            direct_enc=not use_usync,
            recipient_device_jids=recipient_device_jids,
            own_fanout_jids=own_fanout_jids,
            include_phash=include_phash,
            additional_attributes=additional_attributes,
            additional_nodes=additional_nodes,
        )

    async def _prepare_usync_fanout(
        self,
        jid: str,
        *,
        timeout: float,
        force_sessions: bool,
    ) -> tuple[list[str], list[str]]:
        identities = conversation_identities(self.auth_state.credentials, jid)
        usync_result = await self.query(usync_devices_query_node(identities, self.queries.next_tag()), timeout=timeout, drive_receive=True)
        parsed = parse_usync_result(usync_result)
        devices = extract_device_jids(parsed, self.auth_state.credentials["me"]["id"], self.auth_state.credentials.get("me", {}).get("lid"))
        own_fanout_jids, recipient_device_jids = split_own_and_other_devices(self.auth_state.credentials, devices)
        if not is_jid_group(jid) and not recipient_device_jids:
            target_user, target_server, _ = jid_decode_tuple(jid)
            fallback_jid = jid_encode(target_user, target_server, 0)
            recipient_device_jids = [fallback_jid]
        missing = self._missing_session_jids(own_fanout_jids + recipient_device_jids, force=force_sessions)
        if missing:
            working = copy.deepcopy(self.auth_state.credentials)
            result = await self.query(encrypt_session_query_node(missing, self.queries.next_tag(), force=force_sessions), timeout=timeout, drive_receive=True)
            inject_sessions_from_encrypt_result(working, result, allow_partial=True)
            unresolved = self._missing_session_jids_from_credentials(working, own_fanout_jids + recipient_device_jids, force=force_sessions)
            if unresolved:
                raise ValueError(f"session assertion incomplete for {unresolved}")
            await self._commit_credentials(working)
        return own_fanout_jids, recipient_device_jids

    async def _prepare_direct_session(
        self,
        jid: str,
        *,
        timeout: float,
        force_sessions: bool,
    ) -> None:
        if is_jid_group(jid):
            return
        user, server, _ = jid_decode_tuple(jid)
        recipient_device_jid = jid_encode(user, server, 0)
        missing = self._missing_session_jids([recipient_device_jid], force=force_sessions)
        if not missing:
            return

        working = copy.deepcopy(self.auth_state.credentials)
        result = await self.query(
            encrypt_session_query_node(missing, self.queries.next_tag(), force=force_sessions),
            timeout=timeout,
            drive_receive=True,
        )
        inject_sessions_from_encrypt_result(working, result, allow_partial=True)
        unresolved = self._missing_session_jids_from_credentials(working, missing, force=force_sessions)
        if unresolved:
            raise ValueError(f"session assertion incomplete for {unresolved}")
        await self._commit_credentials(working)

    def _missing_session_jids_from_credentials(
        self,
        credentials: dict[str, Any],
        jids: list[str],
        *,
        force: bool,
    ) -> list[str]:
        sessions = credentials.get("signal_sessions") or {}
        missing: list[str] = []
        for jid in _dedupe_jids(jids):
            key = _session_key_for_jid(jid)
            if not key:
                continue
            if key not in sessions:
                missing.append(jid)
        return missing

    def _missing_session_jids(self, jids: list[str], *, force: bool) -> list[str]:
        normalized = _dedupe_jids(jids)
        if force:
            return normalized
        sessions = self.auth_state.credentials.get("signal_sessions") or {}
        missing = []
        for jid in normalized:
            key = _session_key_for_jid(jid)
            if not key:
                continue
            if key not in sessions:
                missing.append(jid)
        return missing

    async def _wait_for_message_ack(self, message_id: str, timeout: float) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                return False
            try:
                nodes = await self.receive_nodes(timeout=min(5, remaining))
            except (TimeoutError, asyncio.TimeoutError):
                continue
            for node in nodes:
                if node.tag == "ack" and node.attrs.get("id") == message_id:
                    return True

    async def _get_media_conn(self, *, timeout: float) -> MediaConn:
        if self._media_conn is not None and self._media_conn_expires_at > time.time():
            return self._media_conn
        node = await self.query(media_conn_node(self.queries.next_tag()), timeout=timeout, drive_receive=True)
        media_conn = parse_media_conn(node)
        self._media_conn = media_conn
        self._media_conn_expires_at = time.time() + max(0, media_conn.ttl - 60)
        return media_conn

    async def refresh_media_conn(self, force: bool = False, *, timeout: float = 30) -> MediaConn:
        if force:
            self._media_conn = None
            self._media_conn_expires_at = 0.0
        return await self._get_media_conn(timeout=timeout)

    def get_media_host(self) -> str:
        if self._media_conn is not None and self._media_conn.hosts:
            return self._media_conn.hosts[0].hostname
        return "mmg.whatsapp.net"

    async def wa_upload_to_server(
        self,
        data: bytes | bytearray | str | Path,
        media_type: str,
        *,
        raw: bool = False,
        timeout: float = 45,
    ) -> MediaUploadResult:
        payload = read_media_payload(data, media_type)
        media_conn = await self._get_media_conn(timeout=timeout)
        if raw:
            return await upload_raw_media(payload.data, media_conn, sha256(payload.data), payload.media_type, timeout=int(timeout))
        encrypted = encrypt_media(payload.data, payload.media_type)
        return await upload_media(encrypted.encrypted, media_conn, encrypted.file_enc_sha256, payload.media_type, timeout=int(timeout))

    async def get_usync_devices(
        self,
        jids: list[str],
        *,
        use_cache: bool = True,
        ignore_zero_devices: bool = False,
        timeout: float = 30,
    ) -> list[DeviceInfo]:
        result = await self.query(usync_devices_query_node(jids, self.queries.next_tag()), timeout=timeout, drive_receive=True)
        parsed = parse_usync_result(result)
        if not use_cache:
            self._store_lid_pn_mappings(self.auth_state.credentials, parsed)
        return extract_device_jids(
            parsed,
            self.auth_state.credentials["me"]["id"],
            self.auth_state.credentials.get("me", {}).get("lid"),
            exclude_zero_devices=ignore_zero_devices,
        )

    async def group_metadata(self, jid: str, *, timeout: float = 30) -> GroupMetadata:
        result = await self._query_checked(group_metadata_node(jid, self.queries.next_tag()), timeout=timeout)
        metadata = parse_group_metadata(result)
        await self.ev.emit("groups.update", [metadata])
        return metadata

    async def group_create(self, subject: str, participants: list[str], *, timeout: float = 30) -> GroupMetadata:
        result = await self._query_checked(group_create_node(subject, participants, self.queries.next_tag()), timeout=timeout)
        metadata = parse_group_metadata(result)
        await self.ev.emit("groups.update", [metadata])
        return metadata

    async def group_leave(self, jid: str, *, timeout: float = 30) -> None:
        await self._query_checked(group_leave_node(jid, self.queries.next_tag()), timeout=timeout)
        await self.ev.emit("groups.update", [{"id": jid, "left": True}])

    async def group_update_subject(self, jid: str, subject: str, *, timeout: float = 30) -> None:
        await self._query_checked(group_update_subject_node(jid, subject, self.queries.next_tag()), timeout=timeout)
        await self.ev.emit("groups.update", [{"id": jid, "subject": subject}])

    async def group_update_description(self, jid: str, description: str | None, *, timeout: float = 30) -> None:
        metadata = await self.group_metadata(jid, timeout=timeout)
        await self._query_checked(group_update_description_node(jid, description, self.queries.next_tag(), previous_id=metadata.desc_id), timeout=timeout)
        await self.ev.emit("groups.update", [{"id": jid, "desc": description}])

    async def group_participants_update(
        self,
        jid: str,
        participants: list[str],
        action: str,
        *,
        timeout: float = 30,
    ) -> list[ParticipantUpdateResult]:
        result = await self._query_checked(group_participants_update_node(jid, participants, action, self.queries.next_tag()), timeout=timeout)
        updates = parse_participant_update(result, action)
        await self.ev.emit("group-participants.update", {"id": jid, "participants": participants, "action": action, "results": updates})
        return updates

    async def group_participants_update_or_invite(
        self,
        jid: str,
        participants: list[str],
        action: str,
        *,
        timeout: float = 30,
        wait_for_ack: float = 0,
    ) -> dict[str, Any]:
        try:
            updates = await self.group_participants_update(jid, participants, action, timeout=timeout)
            return {"action": action, "results": updates, "invites": []}
        except IQError as exc:
            if action != "add" or "account_reachout_restricted" not in (exc.text or ""):
                raise
            invites = [
                await self.send_group_invite(
                    participant,
                    jid,
                    timeout=timeout,
                    wait_for_ack=wait_for_ack,
                )
                for participant in participants
            ]
            await self.ev.emit(
                "group-participants.invite",
                {"id": jid, "participants": participants, "reason": exc.text, "invites": invites},
            )
            return {"action": action, "results": [], "invites": invites, "fallback": "group_invite"}

    async def group_invite_code(self, jid: str, *, timeout: float = 30) -> str | None:
        result = await self._query_checked(group_invite_code_node(jid, self.queries.next_tag()), timeout=timeout)
        return parse_invite_code(result)

    async def send_group_invite(
        self,
        to_jid: str,
        group_jid: str,
        *,
        text: str | None = None,
        invite_expiration: int = 0,
        timeout: float = 30,
        wait_for_ack: float = 0,
    ) -> SendMessageResult:
        metadata = await self.group_metadata(group_jid, timeout=timeout)
        invite_code = await self.group_invite_code(group_jid, timeout=timeout)
        if not invite_code:
            raise ValueError(f"group invite code unavailable for {group_jid}")
        content = {
            "group_invite": {
                "jid": metadata.id or group_jid,
                "invite_code": invite_code,
                "invite_expiration": invite_expiration,
                "subject": metadata.subject or group_jid,
                "caption": text,
            }
        }
        return await self.send_message(
            to_jid,
            content,
            use_usync=True,
            timeout=timeout,
            wait_for_ack=wait_for_ack,
        )

    async def group_revoke_invite(self, jid: str, *, timeout: float = 30) -> str | None:
        result = await self._query_checked(group_revoke_invite_node(jid, self.queries.next_tag()), timeout=timeout)
        return parse_invite_code(result)

    async def group_accept_invite(self, code: str, *, timeout: float = 30) -> str | None:
        result = await self._query_checked(group_accept_invite_node(code, self.queries.next_tag()), timeout=timeout)
        group_jid = parse_accept_invite(result)
        if group_jid:
            await self.ev.emit("groups.update", [{"id": group_jid, "joined": True}])
        return group_jid

    async def group_get_invite_info(self, code: str, *, timeout: float = 30) -> GroupMetadata:
        result = await self._query_checked(group_get_invite_info_node(code, self.queries.next_tag()), timeout=timeout)
        return parse_group_metadata(result)

    async def group_setting_update(self, jid: str, setting: str, value: str = "", *, timeout: float = 30) -> None:
        await self._query_checked(group_setting_update_node(jid, setting, value, self.queries.next_tag()), timeout=timeout)
        await self.ev.emit("groups.update", [{"id": jid, "setting": setting, "value": value}])

    async def group_toggle_ephemeral(self, jid: str, ephemeral_expiration: int, *, timeout: float = 30) -> None:
        await self._query_checked(group_toggle_ephemeral_node(jid, ephemeral_expiration, self.queries.next_tag()), timeout=timeout)
        await self.ev.emit("groups.update", [{"id": jid, "ephemeral_duration": ephemeral_expiration}])

    async def group_member_add_mode(self, jid: str, mode: str, *, timeout: float = 30) -> None:
        await self._query_checked(group_member_add_mode_node(jid, mode, self.queries.next_tag()), timeout=timeout)
        await self.ev.emit("groups.update", [{"id": jid, "member_add_mode": mode}])

    async def group_join_approval_mode(self, jid: str, mode: str, *, timeout: float = 30) -> None:
        await self._query_checked(group_join_approval_mode_node(jid, mode, self.queries.next_tag()), timeout=timeout)
        await self.ev.emit("groups.update", [{"id": jid, "join_approval_mode": mode}])

    async def fetch_privacy_settings(self, *, timeout: float = 30) -> dict[str, str]:
        result = await self._query_checked(privacy_fetch_node(self.queries.next_tag()), timeout=timeout)
        return parse_privacy_settings(result)

    async def update_privacy_setting(self, name: str, value: str, *, timeout: float = 30) -> None:
        await self._query_checked(privacy_update_node(name, value, self.queries.next_tag()), timeout=timeout)

    async def update_messages_privacy(self, value: str, *, timeout: float = 30) -> None:
        await self.update_privacy_setting("messages", value, timeout=timeout)

    async def update_call_privacy(self, value: str, *, timeout: float = 30) -> None:
        await self.update_privacy_setting("calladd", value, timeout=timeout)

    async def update_last_seen_privacy(self, value: str, *, timeout: float = 30) -> None:
        await self.update_privacy_setting("last", value, timeout=timeout)

    async def update_online_privacy(self, value: str, *, timeout: float = 30) -> None:
        await self.update_privacy_setting("online", value, timeout=timeout)

    async def update_profile_picture_privacy(self, value: str, *, timeout: float = 30) -> None:
        await self.update_privacy_setting("profile", value, timeout=timeout)

    async def update_status_privacy(self, value: str, *, timeout: float = 30) -> None:
        await self.update_privacy_setting("status", value, timeout=timeout)

    async def update_read_receipts_privacy(self, value: str, *, timeout: float = 30) -> None:
        await self.update_privacy_setting("readreceipts", value, timeout=timeout)

    async def update_groups_add_privacy(self, value: str, *, timeout: float = 30) -> None:
        await self.update_privacy_setting("groupadd", value, timeout=timeout)

    async def fetch_blocklist(self, *, timeout: float = 30) -> list[str]:
        result = await self._query_checked(blocklist_fetch_node(self.queries.next_tag()), timeout=timeout)
        return parse_blocklist(result)

    async def update_block_status(self, jid: str, action: str, *, timeout: float = 30) -> None:
        lid_jid, pn_jid = await self._resolve_blocklist_jids(jid, action, timeout=timeout)
        await self._query_checked(block_status_node(lid_jid, action, self.queries.next_tag(), pn_jid=pn_jid), timeout=timeout)

    async def _resolve_blocklist_jids(self, jid: str, action: str, *, timeout: float) -> tuple[str, str | None]:
        if action not in {"block", "unblock"}:
            raise ValueError(f"unsupported block action: {action}")

        normalized = self._normalize_user_jid(jid)
        if is_lid(normalized):
            lid_jid = normalized
            pn_jid = self._pn_for_lid(lid_jid)
            if action == "block" and pn_jid is None:
                raise ValueError(f"unable to resolve PN JID for LID: {jid}")
            return lid_jid, pn_jid if action == "block" else None

        if not is_pn(normalized):
            raise ValueError(f"invalid blocklist jid: {jid}")

        lid_jid = self._lid_for_pn(normalized)
        if lid_jid is None:
            await self._refresh_lid_mapping(normalized, timeout=timeout)
            lid_jid = self._lid_for_pn(normalized)
        if lid_jid is None:
            raise ValueError(f"unable to resolve LID for PN JID: {jid}")
        return lid_jid, normalized if action == "block" else None

    @staticmethod
    def _normalize_user_jid(jid: str) -> str:
        value = str(jid).strip()
        if "@" not in value:
            return phone_number_to_jid(value)
        return jid_normalized_user(value)

    def _lid_for_pn(self, pn_jid: str) -> str | None:
        mappings = self.auth_state.credentials.get("pn_lid_mappings") or {}
        return mappings.get(jid_normalized_user(pn_jid))

    def _pn_for_lid(self, lid_jid: str) -> str | None:
        mappings = self.auth_state.credentials.get("lid_pn_mappings") or {}
        return mappings.get(jid_normalized_user(lid_jid))

    async def _refresh_lid_mapping(self, jid: str, *, timeout: float) -> None:
        result = await self.query(
            usync_devices_query_node([jid_normalized_user(jid)], self.queries.next_tag()),
            timeout=timeout,
            drive_receive=True,
        )
        working = copy.deepcopy(self.auth_state.credentials)
        changed = self._store_lid_pn_mappings(working, parse_usync_result(result))
        if changed:
            await self._commit_credentials(working)

    @staticmethod
    def _store_lid_pn_mappings(credentials: dict[str, Any], entries: list[dict[str, object]]) -> bool:
        pn_lid = dict(credentials.get("pn_lid_mappings") or {})
        lid_pn = dict(credentials.get("lid_pn_mappings") or {})
        changed = False
        for entry in entries:
            raw_pn = entry.get("id")
            raw_lid = entry.get("lid")
            if not isinstance(raw_pn, str) or not isinstance(raw_lid, str):
                continue
            pn = jid_normalized_user(raw_pn)
            lid = jid_normalized_user(raw_lid)
            if not is_pn(pn) or not is_lid(lid):
                continue
            if pn_lid.get(pn) != lid:
                pn_lid[pn] = lid
                changed = True
            if lid_pn.get(lid) != pn:
                lid_pn[lid] = pn
                changed = True
        if changed:
            credentials["pn_lid_mappings"] = pn_lid
            credentials["lid_pn_mappings"] = lid_pn
        return changed

    async def profile_picture_url(self, jid: str, picture_type: str = "preview", *, timeout: float = 30) -> str | None:
        result = await self._query_checked(profile_picture_url_node(jid, self.queries.next_tag(), picture_type), timeout=timeout)
        return parse_profile_picture_url(result)

    async def update_profile_status(self, status: str, *, timeout: float = 30) -> None:
        await self._query_checked(profile_status_update_node(status, self.queries.next_tag()), timeout=timeout)

    async def update_profile_name(self, name: str, *, timeout: float = 30) -> None:
        await self.chat_modify({"pushNameSetting": name}, "", timeout=timeout)

    async def update_profile_picture(self, jid: str, data: bytes, *, timeout: float = 30) -> None:
        await self._query_checked(profile_picture_update_node(jid, data, self.queries.next_tag(), own_jid=_me_id(self.auth_state.credentials)), timeout=timeout)

    async def remove_profile_picture(self, jid: str, *, timeout: float = 30) -> None:
        await self._query_checked(profile_picture_remove_node(jid, self.queries.next_tag(), own_jid=_me_id(self.auth_state.credentials)), timeout=timeout)

    async def update_business_profile(self, updates: dict[str, Any], *, timeout: float = 30) -> BinaryNode:
        return await self._query_checked(update_business_profile_node(updates, self.queries.next_tag()), timeout=timeout)

    async def get_business_profile(self, jid: str, *, timeout: float = 30) -> BusinessProfile | None:
        result = await self._query_checked(business_profile_node(jid, self.queries.next_tag()), timeout=timeout)
        return parse_business_profile(result)

    async def get_catalog(
        self,
        jid: str | None = None,
        *,
        limit: int = 10,
        cursor: str | None = None,
        timeout: float = 30,
    ) -> CatalogResult:
        target = jid or self.auth_state.credentials.get("me", {}).get("id")
        if not target:
            raise RuntimeError("cannot fetch catalog before login")
        result = await self._query_checked(catalog_node(target, self.queries.next_tag(), limit=limit, cursor=cursor), timeout=timeout)
        return parse_catalog(result)

    async def get_collections(self, jid: str | None = None, *, limit: int = 51, timeout: float = 30) -> BinaryNode:
        target = jid or self.auth_state.credentials.get("me", {}).get("id")
        if not target:
            raise RuntimeError("cannot fetch collections before login")
        return await self._query_checked(collections_node(target, self.queries.next_tag(), limit=limit), timeout=timeout)

    async def get_order_details(self, order_id: str, token_base64: str, *, timeout: float = 30) -> BinaryNode:
        return await self._query_checked(order_details_node(order_id, token_base64, self.queries.next_tag()), timeout=timeout)

    async def update_cover_photo(self, source: bytes | bytearray | str | Path, *, timeout: float = 30) -> str:
        payload = read_media_payload(source, "biz-cover-photo", mimetype="image/jpeg")
        media_conn = await self._get_media_conn(timeout=timeout)
        encrypted = encrypt_media(payload.data, payload.media_type)
        upload = await upload_media(encrypted.encrypted, media_conn, encrypted.file_enc_sha256, payload.media_type, timeout=int(timeout))
        if not upload.fbid or not upload.meta_hmac:
            raise ValueError(f"cover photo upload response missing fbid/meta_hmac: {upload.raw!r}")
        await self._query_checked(cover_photo_update_node(upload.fbid, upload.meta_hmac, upload.timestamp, self.queries.next_tag()), timeout=timeout)
        return upload.fbid

    async def remove_cover_photo(self, fbid: str, *, timeout: float = 30) -> BinaryNode:
        return await self._query_checked(cover_photo_remove_node(fbid, self.queries.next_tag()), timeout=timeout)

    async def product_create(self, product: dict[str, Any], *, timeout: float = 30) -> Any:
        product = await self._prepare_product_images(product, timeout=timeout)
        result = await self._query_checked(product_create_node(product, self.queries.next_tag()), timeout=timeout)
        return parse_product_mutation(result, "product_catalog_add")

    async def product_update(self, product_id: str, product: dict[str, Any], *, timeout: float = 30) -> Any:
        product = await self._prepare_product_images(product, timeout=timeout)
        result = await self._query_checked(product_update_node(product_id, product, self.queries.next_tag()), timeout=timeout)
        return parse_product_mutation(result, "product_catalog_edit")

    async def _prepare_product_images(self, product: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        images = product.get("images")
        if not images:
            return product
        prepared: list[dict[str, str]] = []
        media_conn: MediaConn | None = None
        for image in images:
            if isinstance(image, str) and "whatsapp.net" in image:
                prepared.append({"url": image})
                continue
            if isinstance(image, dict) and isinstance(image.get("url"), str) and "whatsapp.net" in image["url"]:
                prepared.append({"url": image["url"]})
                continue

            source = image.get("source") if isinstance(image, dict) and "source" in image else image
            payload = read_media_payload(source, "product-catalog-image", mimetype="image/jpeg")
            media_conn = media_conn or await self._get_media_conn(timeout=timeout)
            upload = await upload_raw_media(payload.data, media_conn, sha256(payload.data), payload.media_type, timeout=int(timeout))
            direct_or_url = upload.media_url or media_url_from_direct_path(upload.direct_path, upload.host)
            prepared.append({"url": direct_or_url})
        return {**product, "images": prepared}

    async def product_delete(self, product_ids: list[str], *, timeout: float = 30) -> dict[str, int]:
        result = await self._query_checked(product_delete_node(product_ids, self.queries.next_tag()), timeout=timeout)
        return {"deleted": parse_product_delete(result)}

    async def execute_wmex_query(
        self,
        variables: dict[str, Any],
        query_id: str,
        data_path: str | None = None,
        *,
        timeout: float = 30,
    ) -> Any:
        result = await self._query_checked(wmex_query_node(variables, query_id, self.queries.next_tag()), timeout=timeout)
        return parse_wmex_result(result, data_path)

    async def newsletter_create(self, name: str, description: str | None = None, *, timeout: float = 30) -> NewsletterMetadata | None:
        node, path = newsletter_create_query(name, description, self.queries.next_tag())
        return parse_newsletter_metadata(parse_wmex_result(await self._query_checked(node, timeout=timeout), path))

    async def newsletter_update(self, jid: str, updates: dict[str, Any], *, timeout: float = 30) -> Any:
        node, path = newsletter_update_query(jid, updates, self.queries.next_tag())
        return parse_wmex_result(await self._query_checked(node, timeout=timeout), path)

    async def newsletter_update_name(self, jid: str, name: str, *, timeout: float = 30) -> Any:
        return await self.newsletter_update(jid, {"name": name}, timeout=timeout)

    async def newsletter_update_description(self, jid: str, description: str, *, timeout: float = 30) -> Any:
        return await self.newsletter_update(jid, {"description": description}, timeout=timeout)

    async def newsletter_update_picture(self, jid: str, source: bytes | bytearray | str | Path, *, timeout: float = 30) -> Any:
        payload = read_media_payload(source, "image", mimetype="image/jpeg")
        return await self.newsletter_update(jid, {"picture": base64.b64encode(payload.data).decode("ascii")}, timeout=timeout)

    async def newsletter_remove_picture(self, jid: str, *, timeout: float = 30) -> Any:
        return await self.newsletter_update(jid, {"picture": ""}, timeout=timeout)

    async def newsletter_metadata(self, kind: str, key: str, *, timeout: float = 30) -> NewsletterMetadata | None:
        node, path = newsletter_metadata_query(kind, key, self.queries.next_tag())
        return parse_newsletter_metadata(parse_wmex_result(await self._query_checked(node, timeout=timeout), path))

    async def newsletter_follow(self, jid: str, *, timeout: float = 30) -> Any:
        return await self._newsletter_simple(jid, "FOLLOW", timeout=timeout)

    async def newsletter_unfollow(self, jid: str, *, timeout: float = 30) -> Any:
        return await self._newsletter_simple(jid, "UNFOLLOW", timeout=timeout)

    async def newsletter_mute(self, jid: str, *, timeout: float = 30) -> Any:
        return await self._newsletter_simple(jid, "MUTE", timeout=timeout)

    async def newsletter_unmute(self, jid: str, *, timeout: float = 30) -> Any:
        return await self._newsletter_simple(jid, "UNMUTE", timeout=timeout)

    async def newsletter_subscribers(self, jid: str, *, timeout: float = 30) -> Any:
        return await self._newsletter_simple(jid, "SUBSCRIBERS", timeout=timeout)

    async def newsletter_admin_count(self, jid: str, *, timeout: float = 30) -> int | None:
        response = await self._newsletter_simple(jid, "ADMIN_COUNT", timeout=timeout)
        return int(response["admin_count"]) if isinstance(response, dict) and response.get("admin_count") is not None else None

    async def newsletter_change_owner(self, jid: str, new_owner_jid: str, *, timeout: float = 30) -> Any:
        node, path = newsletter_owner_query(jid, new_owner_jid, "CHANGE_OWNER", self.queries.next_tag())
        return parse_wmex_result(await self._query_checked(node, timeout=timeout), path)

    async def newsletter_demote(self, jid: str, user_jid: str, *, timeout: float = 30) -> Any:
        node, path = newsletter_owner_query(jid, user_jid, "DEMOTE", self.queries.next_tag())
        return parse_wmex_result(await self._query_checked(node, timeout=timeout), path)

    async def newsletter_delete(self, jid: str, *, timeout: float = 30) -> Any:
        return await self._newsletter_simple(jid, "DELETE", timeout=timeout)

    async def newsletter_react_message(self, jid: str, server_id: str, reaction: str | None = None) -> None:
        await self.send_node(newsletter_reaction_node(jid, server_id, self.queries.next_tag(), reaction))

    async def newsletter_fetch_messages(
        self,
        jid: str,
        count: int,
        since: int | None = None,
        after: int | None = None,
        *,
        timeout: float = 30,
    ) -> BinaryNode:
        return await self._query_checked(newsletter_fetch_messages_node(jid, count, since, after, self.queries.next_tag()), timeout=timeout)

    async def subscribe_newsletter_updates(self, jid: str, *, timeout: float = 30) -> dict[str, str] | None:
        result = await self._query_checked(newsletter_live_updates_node(jid, self.queries.next_tag()), timeout=timeout)
        duration = parse_live_update_duration(result)
        return {"duration": duration} if duration else None

    async def _newsletter_simple(self, jid: str, operation: str, *, timeout: float = 30) -> Any:
        node, path = newsletter_simple_query(jid, operation, self.queries.next_tag())
        return parse_wmex_result(await self._query_checked(node, timeout=timeout), path)

    async def fetch_account_reachout_timelock(self, *, timeout: float = 30) -> Any:
        return await self.execute_wmex_query({}, QUERY_IDS["REACHOUT_TIMELOCK"], XWA_PATHS["REACHOUT_TIMELOCK"], timeout=timeout)

    async def fetch_message_capping_info(self, *, timeout: float = 30) -> Any:
        return await self.execute_wmex_query({}, QUERY_IDS["MESSAGE_CAPPING_INFO"], XWA_PATHS["MESSAGE_CAPPING_INFO"], timeout=timeout)

    async def assert_sessions(
        self,
        jids: list[str] | tuple[str, ...],
        *,
        force: bool = False,
        timeout: float = 30,
    ) -> bool:
        normalized = _dedupe_jids([jid_normalized_user(jid) for jid in jids if jid])
        missing = self._missing_session_jids(normalized, force=force)
        if not missing:
            return False

        working = copy.deepcopy(self.auth_state.credentials)
        result = await self.query(
            encrypt_session_query_node(missing, self.queries.next_tag(), force=force),
            timeout=timeout,
            drive_receive=True,
        )
        inject_sessions_from_encrypt_result(working, result, allow_partial=True)
        unresolved = self._missing_session_jids_from_credentials(working, missing, force=force)
        if unresolved:
            raise ValueError(f"session assertion incomplete for {unresolved}")
        await self._commit_credentials(working)
        return True

    async def execute_usync_query(
        self,
        users: list[str] | tuple[str, ...] | BinaryNode,
        protocols: list[str | BinaryNode] | tuple[str | BinaryNode, ...] | None = None,
        *,
        context: str = "interactive",
        mode: str = "query",
        timeout: float = 30,
    ) -> dict[str, Any]:
        if isinstance(users, BinaryNode):
            result = await self._query_checked(users, timeout=timeout)
            return {"raw": result, "list": parse_usync_result(result)}
        if protocols is None:
            raise ValueError("execute_usync_query requires protocols when users are passed")

        tag_id = self.queries.next_tag()
        protocol_nodes = [protocol if isinstance(protocol, BinaryNode) else BinaryNode(str(protocol), {}) for protocol in protocols]
        user_nodes = [BinaryNode("user", {"jid": jid_normalized_user(jid)}, []) for jid in _dedupe_jids(list(users))]
        node = BinaryNode(
            "iq",
            {"id": tag_id, "to": S_WHATSAPP_NET, "type": "get", "xmlns": "usync"},
            [
                BinaryNode(
                    "usync",
                    {"context": context, "mode": mode, "sid": tag_id, "last": "true", "index": "0"},
                    [BinaryNode("query", {}, protocol_nodes), BinaryNode("list", {}, user_nodes)],
                )
            ],
        )
        result = await self._query_checked(node, timeout=timeout)
        return {"raw": result, "list": parse_usync_result(result)}

    async def get_bot_list_v2(self, *, timeout: float = 30) -> list[dict[str, str]]:
        tag_id = self.queries.next_tag()
        result = await self._query_checked(
            BinaryNode("iq", {"id": tag_id, "xmlns": "bot", "to": S_WHATSAPP_NET, "type": "get"}, [BinaryNode("bot", {"v": "2"})]),
            timeout=timeout,
        )
        return _parse_bot_list_v2(result)

    async def issue_privacy_tokens(
        self,
        jids: list[str] | tuple[str, ...],
        *,
        timestamp: int | None = None,
        timeout: float = 30,
    ) -> BinaryNode:
        normalized = _dedupe_jids([jid_normalized_user(jid) for jid in jids if jid])
        if not normalized:
            raise ValueError("issue_privacy_tokens requires at least one jid")
        token_timestamp = str(timestamp if timestamp is not None else int(time.time()))
        node = BinaryNode(
            "iq",
            {"id": self.queries.next_tag(), "to": S_WHATSAPP_NET, "type": "set", "xmlns": "privacy"},
            [
                BinaryNode(
                    "tokens",
                    {},
                    [BinaryNode("token", {"jid": jid, "t": token_timestamp, "type": "trusted_contact"}) for jid in normalized],
                )
            ],
        )
        result = await self._query_checked(node, timeout=timeout)
        if self.auth_state.signal_store is not None:
            for jid in normalized:
                store_tc_tokens_from_iq_result(self.auth_state.signal_store, result, jid, get_lid_for_pn=self._lid_for_pn)
        return result

    async def update_member_label(
        self,
        jid: str,
        member_label: str | None,
        *,
        timeout: float = 30,
        wait_for_ack: float = 0,
    ) -> SendMessageResult:
        message = proto.Message()
        message.protocolMessage.type = proto.Message.ProtocolMessage.Type.GROUP_MEMBER_LABEL_CHANGE
        message.protocolMessage.memberLabel.label = (member_label or "")[:30]
        message.protocolMessage.memberLabel.labelTimestamp = int(time.time())
        return await self.send_message(
            jid,
            message,
            timeout=timeout,
            wait_for_ack=wait_for_ack,
            additional_nodes=[BinaryNode("meta", {"tag_reason": "user_update", "appdata": "member_tag"})],
        )

    async def send_peer_data_operation_message(
        self,
        operation: proto.Message.PeerDataOperationRequestMessage | None = None,
        *,
        timeout: float = 30,
        wait_for_ack: float = 0,
    ) -> SendMessageResult:
        me = self.auth_state.credentials.get("me", {}).get("id")
        if not me:
            raise RuntimeError("cannot send peer data operation before login")
        message = proto.Message()
        message.protocolMessage.type = proto.Message.ProtocolMessage.Type.PEER_DATA_OPERATION_REQUEST_MESSAGE
        if operation is not None:
            message.protocolMessage.peerDataOperationRequestMessage.CopyFrom(operation)
        return await self.send_message(
            jid_normalized_user(me),
            message,
            use_usync=False,
            force_sessions=True,
            timeout=timeout,
            wait_for_ack=wait_for_ack,
            additional_attributes={"category": "peer", "push_priority": "high_force"},
            additional_nodes=[BinaryNode("meta", {"appdata": "default"})],
        )

    async def community_metadata(self, jid: str, *, timeout: float = 30) -> GroupMetadata:
        result = await self._query_checked(community_metadata_node(jid, self.queries.next_tag()), timeout=timeout)
        metadata = parse_community_metadata(result)
        await self.ev.emit("groups.update", [metadata])
        return metadata

    async def community_create(self, subject: str, description: str = "", *, timeout: float = 30) -> GroupMetadata:
        result = await self._query_checked(community_create_node(subject, description, self.queries.next_tag()), timeout=timeout)
        metadata = parse_community_metadata(result)
        await self.ev.emit("groups.update", [metadata])
        return metadata

    async def community_create_group(
        self,
        subject: str,
        participants: list[str],
        parent_community_jid: str,
        *,
        timeout: float = 30,
    ) -> GroupMetadata:
        result = await self._query_checked(
            community_create_group_node(subject, participants, parent_community_jid, self.queries.next_tag()),
            timeout=timeout,
        )
        metadata = parse_community_metadata(result)
        await self.ev.emit("groups.update", [metadata])
        return metadata

    async def community_leave(self, jid: str, *, timeout: float = 30) -> None:
        await self._query_checked(community_leave_node(jid, self.queries.next_tag()), timeout=timeout)
        await self.ev.emit("groups.update", [{"id": jid, "left": True}])

    async def community_update_subject(self, jid: str, subject: str, *, timeout: float = 30) -> None:
        await self._query_checked(community_update_subject_node(jid, subject, self.queries.next_tag()), timeout=timeout)
        await self.ev.emit("groups.update", [{"id": jid, "subject": subject}])

    async def community_link_group(self, group_jid: str, parent_community_jid: str, *, timeout: float = 30) -> None:
        await self._query_checked(community_link_group_node(group_jid, parent_community_jid, self.queries.next_tag()), timeout=timeout)

    async def community_unlink_group(self, group_jid: str, parent_community_jid: str, *, timeout: float = 30) -> None:
        await self._query_checked(community_unlink_group_node(group_jid, parent_community_jid, self.queries.next_tag()), timeout=timeout)

    async def community_fetch_linked_groups(self, jid: str, *, timeout: float = 30) -> dict[str, Any]:
        metadata = await self.group_metadata(jid, timeout=timeout)
        community_jid = metadata.linked_parent or jid
        result = await self._query_checked(community_linked_groups_node(community_jid, self.queries.next_tag()), timeout=timeout)
        return {
            "community_jid": community_jid,
            "is_community": metadata.linked_parent is None,
            "linked_groups": parse_community_linked_groups(result),
        }

    async def community_request_participants_list(self, jid: str, *, timeout: float = 30) -> list[dict[str, str]]:
        result = await self._query_checked(community_membership_requests_node(jid, self.queries.next_tag()), timeout=timeout)
        return parse_membership_requests(result)

    async def community_request_participants_update(
        self,
        jid: str,
        participants: list[str],
        action: str,
        *,
        timeout: float = 30,
    ) -> list[ParticipantUpdateResult]:
        result = await self._query_checked(community_membership_requests_update_node(jid, participants, action, self.queries.next_tag()), timeout=timeout)
        return parse_membership_request_update(result, action)

    async def community_update_description(self, jid: str, description: str | None, *, timeout: float = 30) -> None:
        metadata = await self.community_metadata(jid, timeout=timeout)
        await self._query_checked(community_update_description_node(jid, description, self.queries.next_tag(), previous_id=metadata.desc_id), timeout=timeout)
        await self.ev.emit("groups.update", [{"id": jid, "desc": description}])

    async def community_participants_update(
        self,
        jid: str,
        participants: list[str],
        action: str,
        *,
        timeout: float = 30,
    ) -> list[ParticipantUpdateResult]:
        result = await self._query_checked(community_participants_update_node(jid, participants, action, self.queries.next_tag()), timeout=timeout)
        updates = parse_community_participant_update(result, action)
        await self.ev.emit("group-participants.update", {"id": jid, "participants": participants, "action": action, "results": updates})
        return updates

    async def community_invite_code(self, jid: str, *, timeout: float = 30) -> str | None:
        result = await self._query_checked(community_invite_code_node(jid, self.queries.next_tag()), timeout=timeout)
        return parse_community_invite_code(result)

    async def community_revoke_invite(self, jid: str, *, timeout: float = 30) -> str | None:
        result = await self._query_checked(community_revoke_invite_node(jid, self.queries.next_tag()), timeout=timeout)
        return parse_community_invite_code(result)

    async def community_accept_invite(self, code: str, *, timeout: float = 30) -> str | None:
        result = await self._query_checked(community_accept_invite_node(code, self.queries.next_tag()), timeout=timeout)
        return parse_community_accept_invite(result)

    async def community_invite_info(self, code: str, *, timeout: float = 30) -> GroupMetadata:
        result = await self._query_checked(community_invite_info_node(code, self.queries.next_tag()), timeout=timeout)
        return parse_community_metadata(result)

    async def community_revoke_invite_v4(self, jid: str, invited_jid: str, *, timeout: float = 30) -> bool:
        await self._query_checked(community_revoke_invite_v4_node(jid, invited_jid, self.queries.next_tag()), timeout=timeout)
        return True

    async def community_accept_invite_v4(
        self,
        jid: str,
        code: str,
        expiration: int | str,
        admin_jid: str,
        *,
        timeout: float = 30,
    ) -> str | None:
        result = await self._query_checked(community_accept_invite_v4_node(jid, code, expiration, admin_jid, self.queries.next_tag()), timeout=timeout)
        return result.attrs.get("from")

    async def community_toggle_ephemeral(self, jid: str, ephemeral_expiration: int, *, timeout: float = 30) -> None:
        await self._query_checked(community_ephemeral_node(jid, ephemeral_expiration, self.queries.next_tag()), timeout=timeout)

    async def community_setting_update(self, jid: str, setting: str, *, timeout: float = 30) -> None:
        await self._query_checked(community_setting_update_node(jid, setting, self.queries.next_tag()), timeout=timeout)

    async def community_member_add_mode(self, jid: str, mode: str, *, timeout: float = 30) -> None:
        await self._query_checked(community_member_add_mode_node(jid, mode, self.queries.next_tag()), timeout=timeout)

    async def community_join_approval_mode(self, jid: str, mode: str, *, timeout: float = 30) -> None:
        await self._query_checked(community_join_approval_mode_node(jid, mode, self.queries.next_tag()), timeout=timeout)

    async def reject_call(self, call_id: str, call_from: str) -> None:
        me = self.auth_state.credentials.get("me", {}).get("id")
        if not me:
            raise RuntimeError("cannot reject call before login")
        await self.send_node(
            BinaryNode(
                "call",
                {"from": me, "to": call_from},
                [BinaryNode("reject", {"call-id": call_id, "call-creator": call_from, "count": "0"})],
            )
        )

    async def create_call_link(self, call_type: str, *, start_time: int | None = None, timeout: float = 30) -> str | None:
        content = [BinaryNode("event", {"start_time": str(start_time)})] if start_time is not None else None
        result = await self.query(
            BinaryNode("call", {"id": self.queries.next_tag(), "to": "@call"}, [BinaryNode("link_create", {"media": call_type}, content)]),
            timeout=timeout,
            drive_receive=True,
        )
        child = find_child(result, "link_create")
        return child.attrs.get("token") if child is not None else None

    async def add_or_edit_contact(self, jid: str, contact: dict[str, Any], *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"contact": contact}, jid, timeout=timeout)

    async def remove_contact(self, jid: str, *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"contact": None}, jid, timeout=timeout)

    async def add_or_edit_quick_reply(self, quick_reply: dict[str, Any], *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"quickReply": quick_reply}, "", timeout=timeout)

    async def remove_quick_reply(self, timestamp: str, *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"quickReply": {"timestamp": timestamp, "deleted": True}}, "", timeout=timeout)

    async def add_label(self, jid: str, label: dict[str, Any], *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"addLabel": label}, jid, timeout=timeout)

    async def add_chat_label(self, jid: str, label_id: str, *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"addChatLabel": {"labelId": label_id}}, jid, timeout=timeout)

    async def remove_chat_label(self, jid: str, label_id: str, *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"removeChatLabel": {"labelId": label_id}}, jid, timeout=timeout)

    async def add_message_label(self, jid: str, message_id: str, label_id: str, *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"addMessageLabel": {"messageId": message_id, "labelId": label_id}}, jid, timeout=timeout)

    async def remove_message_label(self, jid: str, message_id: str, label_id: str, *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"removeMessageLabel": {"messageId": message_id, "labelId": label_id}}, jid, timeout=timeout)

    async def on_whatsapp(self, *jids: str, timeout: float = 30) -> list[dict[str, Any]]:
        if not jids:
            return []
        normalized = []
        for raw_jid in jids:
            jid = str(raw_jid).strip()
            if not jid:
                continue
            if "@lid" in jid:
                continue
            normalized.append(jid)
        if not normalized:
            return []

        all_results: list[dict[str, Any]] = []
        seen: set[str] = set()
        deadline = asyncio.get_running_loop().time() + timeout
        chunk_size = 12
        last_error: TimeoutError | asyncio.TimeoutError | None = None

        async def _query_one(phone_jids: list[str], query_timeout: float) -> list[dict[str, Any]]:
            result = await self._query_checked(
                on_whatsapp_node(phone_jids, self.queries.next_tag()),
                timeout=query_timeout,
            )
            return parse_on_whatsapp(result)

        for start in range(0, len(normalized), chunk_size):
            remaining_time = deadline - asyncio.get_running_loop().time()
            if remaining_time <= 0:
                break
            chunk = normalized[start : start + chunk_size]
            try:
                chunk_results = await _query_one(chunk, min(timeout, remaining_time))
            except (TimeoutError, asyncio.TimeoutError) as exc:
                last_error = exc
                if len(chunk) == 1:
                    continue
                for jid in chunk:
                    remaining_time = deadline - asyncio.get_running_loop().time()
                    if remaining_time <= 0:
                        break
                    try:
                        single_results = await _query_one([jid], min(remaining_time, 10))
                        for item in single_results:
                            jid_id = item.get("jid")
                            if jid_id and jid_id not in seen:
                                seen.add(jid_id)
                                all_results.append(item)
                    except (TimeoutError, asyncio.TimeoutError):
                        last_error = exc
                        continue
                continue

            for item in chunk_results:
                jid_id = item.get("jid")
                if jid_id and jid_id not in seen:
                    seen.add(jid_id)
                    all_results.append(item)

        if not all_results and last_error is not None:
            raise last_error

        return all_results

    async def send_presence_update(self, presence_type: str, to_jid: str | None = None) -> BinaryNode:
        if presence_type in {"available", "unavailable"}:
            me = self.auth_state.credentials.get("me") or {}
            node = available_presence_node(me.get("name") or "~", presence_type)
        else:
            if not to_jid:
                raise ValueError("chatstate presence requires to_jid")
            me = self.auth_state.credentials.get("me") or {}
            node = chatstate_presence_node(me.get("id") or "", to_jid, presence_type)
        await self.send_node(node)
        if presence_type in {"available", "unavailable"}:
            await self.ev.emit("connection.update", {"isOnline": presence_type == "available"})
        return node

    async def presence_subscribe(self, jid: str) -> BinaryNode:
        node = presence_subscribe_node(jid, self.queries.next_tag())
        await self.send_node(node)
        return node

    async def fetch_status(self, *jids: str, timeout: float = 30) -> list[dict[str, Any]]:
        result = await self._query_checked(usync_status_node(jids, self.queries.next_tag()), timeout=timeout)
        return parse_usync_status(result)

    async def fetch_disappearing_duration(self, *jids: str, timeout: float = 30) -> list[dict[str, Any]]:
        result = await self._query_checked(usync_disappearing_mode_node(jids, self.queries.next_tag()), timeout=timeout)
        return parse_usync_disappearing_mode(result)

    async def update_default_disappearing_mode(self, duration: int, *, timeout: float = 30) -> BinaryNode:
        return await self._query_checked(default_disappearing_mode_node(duration, self.queries.next_tag()), timeout=timeout)

    async def clean_dirty_bits(self, kind: str, *, from_timestamp: int | None = None) -> BinaryNode:
        node = dirty_clean_node(kind, self.queries.next_tag(), from_timestamp=from_timestamp)
        await self.send_node(node)
        return node

    async def update_disable_link_previews_privacy(
        self,
        is_previews_disabled: bool,
        *,
        timeout: float = 30,
    ) -> BinaryNode:
        return await self.chat_modify(
            {"disableLinkPreviews": {"isPreviewsDisabled": is_previews_disabled}},
            "",
            timeout=timeout,
        )

    async def chat_modify(self, modification: dict[str, Any], jid: str, *, timeout: float = 30) -> BinaryNode:
        working = copy.deepcopy(self.auth_state.credentials)
        try:
            encoded = app_state_patch_node(working, modification, jid, self.queries.next_tag())
        except MissingAppStateKey as exc:
            await self.ev.emit("app-state.patch_error", {"jid": jid, "modification": modification, "error": exc})
            raise
        result = await self._query_checked(encoded.node, timeout=timeout)
        await self._commit_credentials(working)
        await self.ev.emit("chats.update", [{"id": jid, **modification}])
        return result

    async def request_app_state_sync_key(
        self,
        key_ids: list[str] | tuple[str, ...] | str,
        *,
        timeout: float = 30,
        wait_for_ack: float = 0,
    ) -> SendMessageResult:
        me = self.auth_state.credentials.get("me", {}).get("id")
        if not me:
            raise RuntimeError("cannot request app-state sync key before login")
        message = app_state_sync_key_request_message(key_ids)
        return await self.send_message(
            jid_normalized_user(me),
            message,
            use_usync=False,
            force_sessions=True,
            timeout=timeout,
            wait_for_ack=wait_for_ack,
            additional_attributes={"category": "peer", "push_priority": "high_force"},
            additional_nodes=[BinaryNode("meta", {"appdata": "default"})],
        )

    async def fetch_app_state_snapshots(
        self,
        collections: list[str] | tuple[str, ...] = WA_PATCH_NAMES,
        *,
        timeout: float = 30,
        force_snapshot: bool = True,
    ) -> list[AppStateSnapshotInfo]:
        node = app_state_sync_request_node(
            list(collections),
            self.queries.next_tag(),
            versions=self.auth_state.credentials.get("app_state_sync_versions") or {},
            force_snapshot=force_snapshot,
        )
        result = await self.query(node, timeout=timeout, drive_receive=True)
        snapshots = await extract_app_state_snapshot_info(
            result,
            self.auth_state.credentials,
            lambda blob: download_external_blob(blob, timeout=int(timeout)),
        )
        blocked = self.auth_state.credentials.setdefault("app_state_blocked_collections", {})
        changed = False
        for snapshot in snapshots:
            if snapshot.missing_key and snapshot.key_id:
                if blocked.get(snapshot.collection) != snapshot.key_id:
                    blocked[snapshot.collection] = snapshot.key_id
                    changed = True
            elif snapshot.collection in blocked:
                blocked.pop(snapshot.collection, None)
                changed = True
        if changed:
            await self._commit_credentials(self.auth_state.credentials)
        await self.ev.emit("app-state.snapshots", snapshots)
        return snapshots

    async def sync_app_state(
        self,
        collections: list[str] | tuple[str, ...] = WA_PATCH_NAMES,
        *,
        timeout: float = 30,
        force_snapshot: bool = False,
        validate_macs: bool = True,
    ) -> list[AppliedAppStateSync]:
        node = app_state_sync_request_node(
            list(collections),
            self.queries.next_tag(),
            versions=self.auth_state.credentials.get("app_state_sync_versions") or {},
            force_snapshot=force_snapshot,
        )
        result = await self.query(node, timeout=timeout, drive_receive=True)
        download = lambda blob: download_external_blob(blob, timeout=int(timeout))
        syncs = await extract_app_state_sync_data(result, download)
        applied: list[AppliedAppStateSync] = []
        blocked = self.auth_state.credentials.setdefault("app_state_blocked_collections", {})
        changed = False
        for sync in syncs.values():
            try:
                item = await apply_app_state_sync(
                    sync,
                    self.auth_state.credentials,
                    download_blob=download,
                    validate_macs=validate_macs,
                )
            except MissingAppStateKey as exc:
                key_id = _missing_app_state_key_id(exc)
                if key_id and blocked.get(sync.collection) != key_id:
                    blocked[sync.collection] = key_id
                    changed = True
                await self.ev.emit("app-state.sync_blocked", {"collection": sync.collection, "error": exc, "key_id": key_id})
                continue
            applied.append(item)
            if sync.collection in blocked:
                blocked.pop(sync.collection, None)
            changed = True

        if changed:
            await self._commit_credentials(self.auth_state.credentials)
        if applied:
            await self.ev.emit("app-state.sync", applied)
            for item in applied:
                if item.mutations:
                    await self.ev.emit("app-state.mutations", {"collection": item.collection, "mutations": item.mutations})
        return applied

    async def archive_chat(self, jid: str, archive: bool = True, *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"archive": archive}, jid, timeout=timeout)

    async def mute_chat(self, jid: str, mute_end_time: int | None = None, *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"mute": mute_end_time or 0}, jid, timeout=timeout)

    async def pin_chat(self, jid: str, pin: bool = True, *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"pin": pin}, jid, timeout=timeout)

    async def delete_chat(self, jid: str, *, timeout: float = 30) -> BinaryNode:
        return await self.chat_modify({"delete": True}, jid, timeout=timeout)

    async def star_message(self, key: dict[str, Any] | MessageKey, star: bool = True, *, timeout: float = 30) -> BinaryNode:
        payload = key if isinstance(key, dict) else {"remote_jid": key.remote_jid, "id": key.id, "participant": key.participant}
        return await self.chat_modify({"star": {"star": star, "messages": [payload]}}, payload.get("remote_jid") or "", timeout=timeout)

    async def star(self, jid: str, messages: list[dict[str, Any] | MessageKey], star: bool = True, *, timeout: float = 30) -> BinaryNode:
        payloads = [
            message if isinstance(message, dict) else {"remote_jid": message.remote_jid, "id": message.id, "participant": message.participant}
            for message in messages
        ]
        return await self.chat_modify({"star": {"star": star, "messages": payloads}}, jid, timeout=timeout)

    async def dispatch_retry_receipt_node(self, request: RetryRequest) -> RetryOutcome:
        participant = request.key.participant
        local_retry_count = self._increment_retry_count(request.key.id or "", participant)
        bundle: RetrySessionBundle | None = None
        if participant:
            try:
                bundle = inject_retry_session_from_receipt(self.auth_state.credentials, request.node, participant)
            except Exception as exc:
                await self.ev.emit("messages.retry_error", {"request": request, "error": exc, "stage": "session_bundle"})

        will_retry = bool(request.key.from_me and local_retry_count <= self.config.max_msg_retry_count)
        resent = False
        reason = None
        if not request.key.from_me:
            reason = "not_from_me"
        elif local_retry_count > self.config.max_msg_retry_count:
            reason = "max_retries_exceeded"
        else:
            try:
                resent = await self.resend_message_for_retry(request)
                reason = "resent" if resent else "message_unavailable"
            except Exception as exc:
                reason = "resend_error"
                await self.ev.emit("messages.retry_error", {"request": request, "error": exc, "stage": "resend"})

        outcome = RetryOutcome(
            request=request,
            local_retry_count=local_retry_count,
            will_retry=will_retry,
            resent=resent,
            reason=reason,
            session_bundle=bundle,
        )
        await self.ev.emit("messages.retry", outcome)
        if bundle is not None:
            await self._commit_credentials(self.auth_state.credentials)
        return outcome

    async def resend_message_for_retry(self, request: RetryRequest) -> bool:
        if not request.key.id:
            return False
        node = self._recent_outbound.get(request.key.id)
        if node is None:
            return False
        await self.send_node(node)
        return True

    async def send_ack(self, node: BinaryNode, *, error_code: int | None = None) -> bool:
        if not self.config.auto_ack or not can_ack_node(node):
            return False
        try:
            await self.send_node(build_ack_node(node, error_code=error_code, me_id=_me_id(self.auth_state.credentials)))
        except Exception as exc:
            await self.ev.emit("ack.error", {"node": node, "error": exc})
            return False
        return True

    async def send_receipt(
        self,
        jid: str,
        message_ids: list[str],
        *,
        participant: str | None = None,
        receipt_type: str | None = None,
    ) -> BinaryNode:
        node = build_receipt_node(jid, message_ids, participant=participant, receipt_type=receipt_type)
        await self.send_node(node)
        return node

    async def send_receipts(
        self,
        keys: list[MessageKey | WAMessage],
        receipt_type: str | None = None,
    ) -> list[BinaryNode]:
        message_keys = [key.key if isinstance(key, WAMessage) else key for key in keys]
        sent = []
        for jid, participant, message_ids in aggregate_message_keys(message_keys):
            sent.append(await self.send_receipt(jid, message_ids, participant=participant, receipt_type=receipt_type))
        return sent

    async def read_messages(self, keys: list[MessageKey | WAMessage]) -> list[BinaryNode]:
        privacy = await self.fetch_privacy_settings()
        receipt_type = "read" if privacy.get("readreceipts") == "all" else "read-self"
        return await self.send_receipts(keys, receipt_type)

    def _increment_retry_count(self, message_id: str, participant: str | None) -> int:
        key = (message_id, participant)
        count = self._message_retry_counts.get(key, 0) + 1
        self._message_retry_counts[key] = count
        return count

    def start_receive_loop(
        self,
        *,
        timeout: float = 30,
        keepalive_interval: float = 25,
        initialize_reconnect: bool = True,
    ) -> Any:
        if self._receive_task is not None and not self._receive_task.done():
            return self._receive_task

        self.start_keepalive_loop(interval=keepalive_interval)
        self._receive_task = asyncio.create_task(
            self.receive_forever(
                timeout=timeout,
                keepalive_interval=keepalive_interval,
                initialize_reconnect=initialize_reconnect,
            )
        )
        return self._receive_task

    def start_keepalive_loop(self, *, interval: float = 25) -> Any:
        if self._keepalive_task is not None and not self._keepalive_task.done():
            return self._keepalive_task
        self._keepalive_task = asyncio.create_task(self.keepalive_forever(interval=interval))
        return self._keepalive_task

    async def stop_keepalive_loop(self) -> None:
        task = self._keepalive_task
        if task is None:
            self._keepalive_task = None
            return
        if task.done():
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._keepalive_task = None
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        finally:
            self._keepalive_task = None

    async def keepalive_forever(self, *, interval: float = 25) -> None:
        try:
            while not self._closing:
                await asyncio.sleep(interval)
                await self.send_node(client_ping_node(self.queries.next_tag()))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error = _coerce_disconnect_error(exc)
            await self.close(error)
            self._schedule_reconnect(error, receive_timeout=30, keepalive_interval=interval)

    async def stop_receive_loop(self) -> None:
        task = self._receive_task
        if task is None:
            self._receive_task = None
            return
        if task.done():
            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            self._receive_task = None
            return
        task.cancel()
        try:
            await task
        except BaseException as exc:
            if not isinstance(exc, asyncio.CancelledError):
                raise
        finally:
            self._receive_task = None

    async def receive_forever(
        self,
        *,
        timeout: float = 30,
        keepalive_interval: float = 25,
        initialize_reconnect: bool = True,
    ) -> None:
        await self.ev.emit("connection.update", {"connection": "open", "is_receive_loop_running": True})
        try:
            while not self._closing:
                try:
                    await self.receive_nodes(timeout=timeout)
                    if self._closing:
                        if await self._reconnect_after_disconnect(
                            self._last_disconnect_error,
                            receive_timeout=timeout,
                            keepalive_interval=keepalive_interval,
                            initialize=initialize_reconnect,
                        ):
                            continue
                        break
                except TimeoutError:
                    continue
                except asyncio.TimeoutError:
                    continue
                except Exception as exc:
                    error = _coerce_disconnect_error(exc)
                    await self.close(error)
                    if await self._reconnect_after_disconnect(
                        error,
                        receive_timeout=timeout,
                        keepalive_interval=keepalive_interval,
                        initialize=initialize_reconnect,
                    ):
                        continue
                    break
        except asyncio.CancelledError:
            raise
        finally:
            if self._keepalive_task is not asyncio.current_task():
                await self.stop_keepalive_loop()
            if self._receive_task is asyncio.current_task():
                self._receive_task = None
            await self.ev.emit("connection.update", {"connection": "close", "is_receive_loop_running": False})

    def _schedule_reconnect(
        self,
        error: DisconnectError | None,
        *,
        receive_timeout: float,
        keepalive_interval: float,
        initialize: bool = True,
    ) -> None:
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        if not self.config.reconnect_policy.should_reconnect(error):
            return
        self._reconnect_task = asyncio.create_task(
            self._reconnect_after_disconnect(
                error,
                receive_timeout=receive_timeout,
                keepalive_interval=keepalive_interval,
                initialize=initialize,
                restart_receive_loop=True,
            )
        )

    async def _reconnect_after_disconnect(
        self,
        error: DisconnectError | None,
        *,
        receive_timeout: float,
        keepalive_interval: float,
        initialize: bool = True,
        restart_receive_loop: bool = False,
    ) -> bool:
        policy = self.config.reconnect_policy
        if not policy.should_reconnect(error):
            return False

        for attempt in range(1, policy.max_attempts + 1):
            delay = policy.delay_for_attempt(attempt)
            await self.ev.emit(
                "connection.update",
                {
                    "connection": "connecting",
                    "reconnect": True,
                    "attempt": attempt,
                    "delay": delay,
                    "last_disconnect": error,
                },
            )
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                await self.connect_and_wait(initialize=initialize, start_receive_loop=False)
            except Exception as exc:
                error = _coerce_disconnect_error(exc)
                await self.ev.emit(
                    "connection.update",
                    {
                        "connection": "close",
                        "reconnect": True,
                        "attempt": attempt,
                        "last_disconnect": error,
                    },
                )
                continue

            self._closing = False
            self._last_disconnect_error = None
            await self.ev.emit("connection.update", {"connection": "open", "reconnect": True, "attempt": attempt})
            if restart_receive_loop:
                self.start_receive_loop(timeout=receive_timeout, keepalive_interval=keepalive_interval)
            else:
                self._receive_task = asyncio.current_task()
                self.start_keepalive_loop(interval=keepalive_interval)
            return True

        await self.ev.emit(
            "connection.update",
            {
                "connection": "close",
                "reconnect": False,
                "reconnect_exhausted": True,
                "last_disconnect": error,
            },
        )
        return False

    async def wait_for_success(
        self,
        timeout: float = 60,
        *,
        reply_to_pings: bool = True,
        initialize: bool = True,
    ) -> BinaryNode:
        if self._web is None:
            raise RuntimeError("client is not connected")
        node = await self._web.wait_for_success(timeout=timeout, reply_to_pings=reply_to_pings)
        if self._web.creds is not None:
            self.auth_state.credentials = self._web.creds
            await self.ev.emit("creds.update", self.auth_state.credentials)
        if node.attrs.get("t"):
            self._server_time_offset_ms = int(node.attrs["t"]) * 1000 - int(__import__("time").time() * 1000)
        if initialize:
            await self.initialize_session()
        if initialize and self.config.auto_prekey_maintenance:
            try:
                await self.maintain_pre_keys(drive_receive=True)
            except Exception as exc:
                await self.ev.emit("prekeys.update", {"maintenance": "failed", "error": exc})
        await self.ev.emit("connection.update", {"connection": "open", "received_pending_notifications": True})
        return node

    async def initialize_session(self) -> None:
        await self.send_node(passive_active_node(self.queries.next_tag()))
        await self.send_node(unified_session_node(self._server_time_offset_ms))

    def build_pairing_code_request(
        self,
        phone_number: str,
        *,
        pairing_code: str | None = None,
        custom_pairing_code: str | None = None,
        companion_ephemeral_public: bytes | None = None,
        noise_public: bytes | None = None,
        tag_id: str | None = None,
    ) -> PairingCodeRequest:
        companion_public = companion_ephemeral_public or generate_noise_key_pair().public
        noise = noise_public or generate_noise_key_pair().public
        return pairing_code_request_node(
            phone_number=phone_number,
            tag_id=tag_id or self.queries.next_tag(),
            companion_ephemeral_public=companion_public,
            noise_public=noise,
            pairing_code=pairing_code,
            custom_pairing_code=custom_pairing_code,
        )

    async def request_pairing_code(
        self,
        phone_number: str,
        *,
        pairing_code: str | None = None,
        custom_pairing_code: str | None = None,
        companion_ephemeral_public: bytes | None = None,
        noise_public: bytes | None = None,
        timeout: float = 30,
    ) -> PairingCodeRequest:
        request = self.build_pairing_code_request(
            phone_number,
            pairing_code=pairing_code,
            custom_pairing_code=custom_pairing_code,
            companion_ephemeral_public=companion_ephemeral_public,
            noise_public=noise_public,
        )
        await self.query(request.node, timeout=timeout)
        await self.ev.emit("connection.update", {"pairing_code": request.code, "pairing_jid": request.jid})
        return request

    async def digest_key_bundle(self, *, timeout: float = 30) -> BinaryNode:
        response = await self.query(digest_key_bundle_node(self.queries.next_tag()), timeout=timeout)
        digest = _first_child(response, "digest")
        if digest is None:
            raise ValueError("encrypt/get digest response missing digest child")
        return digest

    async def count_pre_keys(self, *, timeout: float = 30, drive_receive: bool = False) -> int:
        response = await self.query(prekey_count_node(self.queries.next_tag()), timeout=timeout, drive_receive=drive_receive)
        return parse_prekey_count(response)

    async def upload_pre_keys(
        self,
        count: int | None = None,
        *,
        timeout: float = 30,
        retries: int = 0,
        retry_delay: float = 1,
        drive_receive: bool = False,
    ) -> PreKeyNodeResult:
        working_creds = copy.deepcopy(self.auth_state.credentials)
        result = build_prekey_upload_node(working_creds, count=count or MIN_PREKEY_COUNT, tag_id=self.queries.next_tag())
        last_error: Exception | None = None
        for attempt in range(retries + 1):
            try:
                await self.query(result.node, timeout=timeout, drive_receive=drive_receive)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                if attempt >= retries:
                    break
                await asyncio.sleep(min(retry_delay * (2**attempt), 10))
        if last_error is not None:
            raise last_error
        await self._commit_credentials(working_creds)
        await self.ev.emit("prekeys.update", {"uploaded": result.uploaded_ids})
        return result

    async def maintain_pre_keys(
        self,
        *,
        timeout: float = 30,
        retries: int = 3,
        retry_delay: float = 1,
        drive_receive: bool = False,
    ) -> PreKeyMaintenanceResult:
        server_count = await self.count_pre_keys(timeout=timeout, drive_receive=drive_receive)
        upload_count = INITIAL_PREKEY_COUNT if server_count == 0 else MIN_PREKEY_COUNT
        current_prekey_id = int(self.auth_state.credentials.get("next_pre_key_id", 1)) - 1
        has_current_prekey = current_prekey_id <= 0 or str(current_prekey_id) in (
            self.auth_state.credentials.get("pre_keys") or {}
        )
        should_upload = server_count <= upload_count or not has_current_prekey
        if not should_upload:
            result = PreKeyMaintenanceResult(server_count=server_count)
            await self.ev.emit("prekeys.update", {"server_count": server_count, "maintenance": "ok"})
            return result

        reason = "server_count_zero" if server_count == 0 else "server_count_low"
        if not has_current_prekey:
            reason = "current_prekey_missing"
        uploaded = await self.upload_pre_keys(
            upload_count,
            timeout=timeout,
            retries=retries,
            retry_delay=retry_delay,
            drive_receive=drive_receive,
        )
        result = PreKeyMaintenanceResult(server_count=server_count, uploaded=uploaded, reason=reason)
        await self.ev.emit(
            "prekeys.update",
            {"server_count": server_count, "maintenance": "uploaded", "reason": reason, "uploaded": uploaded.uploaded_ids},
        )
        return result

    async def rotate_signed_pre_key(self, *, timeout: float = 30) -> SignedPreKeyRotation:
        working_creds = copy.deepcopy(self.auth_state.credentials)
        rotation = rotate_signed_pre_key_node(working_creds, self.queries.next_tag())
        await self.query(rotation.node, timeout=timeout)
        await self._commit_credentials(working_creds)
        return rotation

    async def _commit_credentials(self, credentials: dict[str, Any]) -> None:
        self.auth_state.credentials = credentials
        self.auth_state.save_credentials()
        await self.ev.emit("creds.update", self.auth_state.credentials)

    async def _clear_credentials(self) -> None:
        self.auth_state.credentials = {}
        if self.auth_state.credential_store is not None:
            self.auth_state.save_credentials()
        await self.ev.emit("creds.update", self.auth_state.credentials)

    async def finalize_pair_success(
        self,
        node: BinaryNode,
        *,
        static_noise: Any,
        meta: dict[str, Any],
    ) -> PairSuccess:
        success = configure_successful_pairing(node, static_noise=static_noise, meta=meta)
        await self.send_node(success.reply)
        self.auth_state.credentials = success.credentials
        self.auth_state.save_credentials()
        self._qr_static_noise = None
        self._qr_meta = None
        await self.ev.emit("creds.update", self.auth_state.credentials)
        await self.ev.emit("connection.update", {"connection": "open", "pairing": "success", **success.update})
        return success

    # Baileys-style aliases for common public surface names.
    sendMessage = send_message
    relayMessage = relay_message
    downloadMediaMessage = download_media_message
    updateMediaMessage = update_media_message
    sendMediaMessage = send_media_message
    refreshMediaConn = refresh_media_conn
    getMediaHost = get_media_host
    waUploadToServer = wa_upload_to_server
    getUSyncDevices = get_usync_devices
    sendNode = send_node
    receiveNodes = receive_nodes
    sendAck = send_ack
    sendReceipt = send_receipt
    sendReceipts = send_receipts
    readMessages = read_messages
    resendMessageForRetry = resend_message_for_retry
    waitForSuccess = wait_for_success
    groupMetadata = group_metadata
    groupCreate = group_create
    groupLeave = group_leave
    groupUpdateSubject = group_update_subject
    groupUpdateDescription = group_update_description
    groupParticipantsUpdate = group_participants_update
    groupParticipantsUpdateOrInvite = group_participants_update_or_invite
    groupInviteCode = group_invite_code
    sendGroupInvite = send_group_invite
    groupRevokeInvite = group_revoke_invite
    groupAcceptInvite = group_accept_invite
    groupGetInviteInfo = group_get_invite_info
    groupSettingUpdate = group_setting_update
    groupToggleEphemeral = group_toggle_ephemeral
    groupMemberAddMode = group_member_add_mode
    groupJoinApprovalMode = group_join_approval_mode
    fetchPrivacySettings = fetch_privacy_settings
    updatePrivacySetting = update_privacy_setting
    updateMessagesPrivacy = update_messages_privacy
    updateCallPrivacy = update_call_privacy
    updateLastSeenPrivacy = update_last_seen_privacy
    updateOnlinePrivacy = update_online_privacy
    updateProfilePicturePrivacy = update_profile_picture_privacy
    updateStatusPrivacy = update_status_privacy
    updateReadReceiptsPrivacy = update_read_receipts_privacy
    updateGroupsAddPrivacy = update_groups_add_privacy
    fetchBlocklist = fetch_blocklist
    updateBlockStatus = update_block_status
    profilePictureUrl = profile_picture_url
    updateProfileStatus = update_profile_status
    updateProfileName = update_profile_name
    updateProfilePicture = update_profile_picture
    removeProfilePicture = remove_profile_picture
    updateBusinessProfile = update_business_profile
    updateBussinesProfile = update_business_profile
    getBusinessProfile = get_business_profile
    updateCoverPhoto = update_cover_photo
    removeCoverPhoto = remove_cover_photo
    getCatalog = get_catalog
    getCollections = get_collections
    getOrderDetails = get_order_details
    productCreate = product_create
    productUpdate = product_update
    productDelete = product_delete
    executeWMexQuery = execute_wmex_query
    newsletterCreate = newsletter_create
    newsletterUpdate = newsletter_update
    newsletterUpdateName = newsletter_update_name
    newsletterUpdateDescription = newsletter_update_description
    newsletterUpdatePicture = newsletter_update_picture
    newsletterRemovePicture = newsletter_remove_picture
    newsletterMetadata = newsletter_metadata
    newsletterFollow = newsletter_follow
    newsletterUnfollow = newsletter_unfollow
    newsletterMute = newsletter_mute
    newsletterUnmute = newsletter_unmute
    newsletterSubscribers = newsletter_subscribers
    newsletterAdminCount = newsletter_admin_count
    newsletterChangeOwner = newsletter_change_owner
    newsletterDemote = newsletter_demote
    newsletterDelete = newsletter_delete
    newsletterReactMessage = newsletter_react_message
    newsletterFetchMessages = newsletter_fetch_messages
    subscribeNewsletterUpdates = subscribe_newsletter_updates
    fetchAccountReachoutTimelock = fetch_account_reachout_timelock
    fetchMessageCappingInfo = fetch_message_capping_info
    fetchNewChatMessageCap = fetch_message_capping_info
    assertSessions = assert_sessions
    executeUSyncQuery = execute_usync_query
    getBotListV2 = get_bot_list_v2
    issuePrivacyTokens = issue_privacy_tokens
    updateMemberLabel = update_member_label
    sendPeerDataOperationMessage = send_peer_data_operation_message
    fetchStatus = fetch_status
    fetchDisappearingDuration = fetch_disappearing_duration
    communityMetadata = community_metadata
    communityCreate = community_create
    communityCreateGroup = community_create_group
    communityLeave = community_leave
    communityUpdateSubject = community_update_subject
    communityLinkGroup = community_link_group
    communityUnlinkGroup = community_unlink_group
    communityFetchLinkedGroups = community_fetch_linked_groups
    communityRequestParticipantsList = community_request_participants_list
    communityRequestParticipantsUpdate = community_request_participants_update
    communityUpdateDescription = community_update_description
    communityParticipantsUpdate = community_participants_update
    communityInviteCode = community_invite_code
    communityRevokeInvite = community_revoke_invite
    communityAcceptInvite = community_accept_invite
    communityInviteInfo = community_invite_info
    communityGetInviteInfo = community_invite_info
    communityRevokeInviteV4 = community_revoke_invite_v4
    communityAcceptInviteV4 = community_accept_invite_v4
    communityToggleEphemeral = community_toggle_ephemeral
    communitySettingUpdate = community_setting_update
    communityMemberAddMode = community_member_add_mode
    communityJoinApprovalMode = community_join_approval_mode
    rejectCall = reject_call
    createCallLink = create_call_link
    addOrEditContact = add_or_edit_contact
    removeContact = remove_contact
    addOrEditQuickReply = add_or_edit_quick_reply
    removeQuickReply = remove_quick_reply
    addLabel = add_label
    addChatLabel = add_chat_label
    removeChatLabel = remove_chat_label
    addMessageLabel = add_message_label
    removeMessageLabel = remove_message_label
    starMessage = star_message
    onWhatsApp = on_whatsapp
    sendPresenceUpdate = send_presence_update
    presenceSubscribe = presence_subscribe
    chatModify = chat_modify
    cleanDirtyBits = clean_dirty_bits
    updateDefaultDisappearingMode = update_default_disappearing_mode
    updateDisableLinkPreviewsPrivacy = update_disable_link_previews_privacy
    requestAppStateSyncKey = request_app_state_sync_key
    fetchAppStateSnapshots = fetch_app_state_snapshots
    syncAppState = sync_app_state
    resyncAppState = sync_app_state
    initializeSession = initialize_session
    requestPairingCode = request_pairing_code
    digestKeyBundle = digest_key_bundle
    countPreKeys = count_pre_keys
    uploadPreKeys = upload_pre_keys
    maintainPreKeys = maintain_pre_keys
    rotateSignedPreKey = rotate_signed_pre_key
    DisconnectReason = DisconnectReason
    ReconnectPolicy = ReconnectPolicy
    connectAndWait = connect_and_wait
    connectForQRPairing = connect_for_qr_pairing
    finalizePairSuccess = finalize_pair_success
    sendWAMBuffer = send_wam_buffer
    sendWAM = send_wam


def make_socket(
    auth: AuthState | MultiFileAuthState | str | Path,
    **kwargs: Any,
) -> WhatsAppClient:
    return WhatsAppClient(auth, **kwargs)


makeWASocket = make_socket


def _coerce_auth_state(auth: AuthState | MultiFileAuthState | str | Path) -> AuthState:
    if isinstance(auth, AuthState):
        return auth
    if isinstance(auth, MultiFileAuthState):
        return auth.load()
    return AuthState.from_store(JsonCredentialStore(auth), allow_missing=True)


def _credential_path(auth_state: AuthState) -> Path | None:
    store = auth_state.credential_store
    if isinstance(store, JsonCredentialStore):
        return store.path
    return None


def _me_id(creds: dict[str, Any]) -> str | None:
    me = creds.get("me") or {}
    return me.get("id")


def _optional_int(value: str | None) -> int | None:
    return int(value) if value is not None else None


def _first_child(node: BinaryNode, tag: str) -> BinaryNode | None:
    if not isinstance(node.content, list):
        return None
    for child in node.content:
        if child.tag == tag:
            return child
    return None


def _missing_app_state_key_id(exc: MissingAppStateKey) -> str | None:
    text = str(exc)
    marker = "app-state key '"
    if marker in text:
        return text.split(marker, 1)[1].split("'", 1)[0]
    marker = 'key "'
    if marker in text:
        return text.split(marker, 1)[1].split('"', 1)[0]
    return None


def _parse_bot_list_v2(node: BinaryNode) -> list[dict[str, str]]:
    bot = find_child(node, "bot")
    if bot is None or not isinstance(bot.content, list):
        return []
    parsed: list[dict[str, str]] = []
    for section in bot.content:
        if section.tag != "section" or section.attrs.get("type") != "all" or not isinstance(section.content, list):
            continue
        for child in section.content:
            if child.tag != "bot":
                continue
            jid = child.attrs.get("jid")
            if not jid:
                continue
            parsed.append({"jid": jid, "persona_id": child.attrs.get("persona_id") or child.attrs.get("personaId") or ""})
    return parsed


def _media_retry_message_parts(message: WAMessage | proto.WebMessageInfo) -> tuple[Any, proto.Message]:
    if isinstance(message, WAMessage):
        if message.message is None:
            raise ValueError("media retry requires message content")
        return message.key, message.message
    if isinstance(message, proto.WebMessageInfo):
        if not message.HasField("message"):
            raise ValueError("media retry requires message content")
        return message.key, message.message
    raise TypeError(f"unsupported media retry message type: {type(message).__name__}")


def _media_content_from_message(message: proto.Message) -> Any:
    for field_name in ("imageMessage", "videoMessage", "audioMessage", "documentMessage", "stickerMessage"):
        if message.HasField(field_name):
            return getattr(message, field_name)
    raise ValueError("message does not contain supported media content")


def _message_key_id(key: Any) -> str | None:
    if isinstance(key, dict):
        return key.get("id")
    return getattr(key, "id", None)


def _message_key_dict(key: Any) -> dict[str, Any]:
    if isinstance(key, MessageKey):
        return {
            "remote_jid": key.remote_jid,
            "id": key.id,
            "from_me": key.from_me,
            "participant": key.participant,
        }
    if isinstance(key, proto.MessageKey):
        return {
            "remote_jid": key.remoteJid or None,
            "id": key.id or None,
            "from_me": bool(key.fromMe),
            "participant": key.participant or None,
        }
    return dict(key) if isinstance(key, dict) else {"id": getattr(key, "id", None)}


def _coerce_media_retry_event(update: Any) -> MediaRetryEvent | None:
    if isinstance(update, MediaRetryEvent):
        return update
    if isinstance(update, dict) and isinstance(update.get("key"), dict):
        return MediaRetryEvent(key=update["key"], media=update.get("media"), error=update.get("error"))
    return None


def _coerce_disconnect_error(exc: Exception) -> DisconnectError:
    if isinstance(exc, DisconnectError):
        return exc
    return DisconnectError(
        "Connection Lost",
        status_code=DisconnectReason.connectionLost,
        reason="connection_lost",
        data=exc,
    )
