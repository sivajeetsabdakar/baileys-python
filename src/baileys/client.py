from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import websockets

from baileys.auth_store import load_creds, save_creds, unb64
from baileys.crypto import decompress_if_required
from baileys.defaults import DEFAULT_ORIGIN, DEFAULT_USER_AGENT, WA_WEBSOCKET_URL
from baileys.errors import AuthStateError, ProtocolError, QueryTimeoutError, SocketNotConnectedError
from baileys.generated import WAProto_pb2 as proto
from baileys.noise import NoiseHandshake, generate_noise_key_pair
from baileys.registration import build_login_payload
from baileys.routing import websocket_url_with_routing
from baileys.signal_crypto import SignalKeyPair
from baileys.socket_nodes import SocketNodeKind, classify_node, find_child, node_content_bytes, server_ping_reply
from baileys.wabinary import BinaryNode, decode_binary_node, encode_binary_node


class WhatsAppWebClient:
    def __init__(
        self,
        creds_path: str | Path,
        *,
        websocket_url: str = WA_WEBSOCKET_URL,
        origin: str = DEFAULT_ORIGIN,
        user_agent: str = DEFAULT_USER_AGENT,
        use_routing_info: bool = True,
    ) -> None:
        self.creds_path = Path(creds_path)
        self.websocket_url = websocket_url
        self.origin = origin
        self.user_agent = user_agent
        self.use_routing_info = use_routing_info
        self.creds: dict[str, Any] | None = None
        self.noise: NoiseHandshake | None = None
        self.websocket: Any = None

    async def __aenter__(self) -> "WhatsAppWebClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def connect(self, *, open_timeout: float = 20, close_timeout: float = 5) -> None:
        creds = load_creds(self.creds_path)
        me = (creds.get("me") or {}).get("id")
        if not me:
            raise AuthStateError("creds file has no me.id")

        routing_info = unb64(creds["routing_info"]) if self.use_routing_info and creds.get("routing_info") else None
        ephemeral = generate_noise_key_pair()
        static_noise = SignalKeyPair(private=unb64(creds["noise_private"]), public=unb64(creds["noise_public"]))
        noise = NoiseHandshake(ephemeral, routing_info=routing_info)
        websocket = await websockets.connect(
            websocket_url_with_routing(self.websocket_url, routing_info),
            origin=self.origin,
            open_timeout=open_timeout,
            close_timeout=close_timeout,
            ping_interval=None,
            additional_headers={"User-Agent": self.user_agent},
        )
        try:
            await websocket.send(noise.client_hello_frame())
            response = await asyncio.wait_for(websocket.recv(), timeout=open_timeout)
            if isinstance(response, str):
                response = response.encode("latin1")
            server_hello_payload = response[3 : 3 + int.from_bytes(response[:3], "big")]
            info = noise.process_server_hello(server_hello_payload, static_noise)

            finish = proto.HandshakeMessage()
            finish.clientFinish.static = info.encrypted_static_key
            finish.clientFinish.payload = noise.encrypt(build_login_payload(me))
            await websocket.send(noise.encode_frame(finish.SerializeToString()))
            noise.finish_init()
        except Exception:
            await websocket.close()
            raise

        self.creds = creds
        self.noise = noise
        self.websocket = websocket

    async def close(self) -> None:
        if self.websocket is not None:
            await self.websocket.close()
        self.websocket = None
        self.noise = None

    async def send_node(self, node: BinaryNode) -> None:
        if self.websocket is None or self.noise is None:
            raise SocketNotConnectedError("client is not connected")
        await self.websocket.send(self.noise.encode_frame(encode_binary_node(node)))

    async def receive_nodes(self, timeout: float = 30) -> list[BinaryNode]:
        if self.websocket is None or self.noise is None:
            raise SocketNotConnectedError("client is not connected")
        raw = await asyncio.wait_for(self.websocket.recv(), timeout=timeout)
        if isinstance(raw, str):
            raw = raw.encode("latin1")
        return [
            decode_binary_node(decompress_if_required(plaintext), has_stream_prefix=False)
            for plaintext in self.noise.decode_transport_frames(raw)
        ]

    async def wait_for_success(self, timeout: float = 60, *, reply_to_pings: bool = True) -> BinaryNode:
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise QueryTimeoutError("timed out waiting for login success", operation="login", timeout=timeout)
            for node in await self.receive_nodes(min(30, remaining)):
                kind = classify_node(node)
                if kind == SocketNodeKind.LOGIN_SUCCESS:
                    return node
                if kind == SocketNodeKind.SERVER_PING and reply_to_pings:
                    await self.send_node(server_ping_reply(node))
                    continue
                if kind == SocketNodeKind.EDGE_ROUTING:
                    self.persist_edge_routing_if_present(node)
                    continue
                if kind in {SocketNodeKind.FAILURE, SocketNodeKind.STREAM_ERROR, SocketNodeKind.IQ_ERROR}:
                    raise ProtocolError(f"socket failed before success: {node!r}")

    def persist_edge_routing_if_present(self, node: BinaryNode) -> bool:
        if self.creds is None:
            raise AuthStateError("client has no loaded credentials")
        routing_info = find_child(find_child(node, "edge_routing"), "routing_info")
        content = node_content_bytes(routing_info)
        if not content:
            return False
        import base64

        self.creds["routing_info"] = base64.b64encode(content).decode("ascii")
        save_creds(self.creds_path, self.creds)
        return True
