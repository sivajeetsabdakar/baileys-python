from __future__ import annotations

import argparse
import asyncio
import base64
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import MessageUpsert, make_socket  # noqa: E402
from baileys.defaults import S_WHATSAPP_NET  # noqa: E402
from baileys.generated import WAProto_pb2 as proto  # noqa: E402
from baileys.media import download_external_blob  # noqa: E402
from baileys.wabinary import BinaryNode  # noqa: E402


DEFAULT_COLLECTIONS = (
    "regular_low",
    "regular",
    "regular_high",
    "critical_block",
    "critical_unblock_low",
)


def _message_fields(message) -> list[str]:
    return [field.name for field, _ in message.ListFields()]


async def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect live app-state key-share delivery for a saved session.")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "product_qr_creds.json"))
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument("--receive-timeout", type=float, default=20)
    parser.add_argument("--keepalive-interval", type=float, default=20)
    parser.add_argument(
        "--request-snapshots",
        action="store_true",
        help="Request app-state collection snapshots and print safe metadata.",
    )
    parser.add_argument("--collection", action="append", choices=DEFAULT_COLLECTIONS, dest="collections")
    parser.add_argument("--request-key", action="append", dest="request_keys", help="Request an app-state sync key id.")
    parser.add_argument("--wait-for-ack", type=float, default=0)
    args = parser.parse_args()

    creds_path = Path(args.creds_path).resolve()
    if not creds_path.exists():
        print(f"MISSING_CREDS {creds_path}", flush=True)
        return 2

    client = make_socket(creds_path)
    counters = {
        "messages": 0,
        "protocol_messages": 0,
        "app_state_key_updates": 0,
        "decrypt_errors": 0,
    }

    def on_connection(payload: dict) -> None:
        safe = {key: value for key, value in payload.items() if key != "qr"}
        print(f"EVENT connection.update {safe}", flush=True)

    def on_keys(payload: dict) -> None:
        counters["app_state_key_updates"] += 1
        print(f"EVENT app-state.keys.update {payload}", flush=True)

    def on_decrypt_error(payload: dict) -> None:
        counters["decrypt_errors"] += 1
        print(f"EVENT messages.decrypt_error {payload.get('error')}", flush=True)

    def on_upsert(payload: MessageUpsert) -> None:
        counters["messages"] += len(payload.messages)
        print(f"EVENT messages.upsert count={len(payload.messages)} type={payload.type}", flush=True)
        for item in payload.messages:
            message = item.message
            if message is None:
                print(f"MESSAGE no-decrypted-message key={item.key}", flush=True)
                continue
            fields = _message_fields(message)
            print(f"MESSAGE fields={fields} key={item.key}", flush=True)
            if message.HasField("protocolMessage"):
                counters["protocol_messages"] += 1
                protocol = message.protocolMessage
                type_name = protocol.Type.Name(protocol.type) if protocol.type in protocol.Type.values() else str(protocol.type)
                print(
                    "PROTOCOL "
                    f"type={int(protocol.type)} "
                    f"name={type_name} "
                    f"has_history={protocol.HasField('historySyncNotification')} "
                    f"has_app_state_key_share={protocol.HasField('appStateSyncKeyShare')}",
                    flush=True,
                )

    client.ev.on("connection.update", on_connection)
    client.ev.on("messages.upsert", on_upsert)
    client.ev.on("messages.decrypt_error", on_decrypt_error)
    client.ev.on("app-state.keys.update", on_keys)

    try:
        await client.connect_and_wait(success_timeout=60)
        if args.request_snapshots:
            collections = args.collections or list(DEFAULT_COLLECTIONS)
            for name in collections:
                node = BinaryNode(
                    "iq",
                    {
                        "to": S_WHATSAPP_NET,
                        "xmlns": "w:sync:app:state",
                        "type": "set",
                        "id": client.queries.next_tag(),
                    },
                    [
                        BinaryNode(
                            "sync",
                            {},
                            [
                                BinaryNode(
                                    "collection",
                                    {"name": name, "version": "0", "return_snapshot": "true"},
                                )
                            ],
                        )
                    ],
                )
                result = await client.query(node, timeout=30, drive_receive=True)
                await print_snapshot_summary(name, result)

        if args.request_keys:
            result = await client.request_app_state_sync_key(args.request_keys, timeout=30, wait_for_ack=args.wait_for_ack)
            print(
                "APP_STATE_KEY_REQUEST "
                f"message_id={result.message_id} "
                f"remote_jid={result.remote_jid} "
                f"participants={result.participant_jids} "
                f"acked={result.acked}",
                flush=True,
            )

        client.start_receive_loop(timeout=args.receive_timeout, keepalive_interval=args.keepalive_interval)
        print(f"APP_STATE_KEY_PROBE_STARTED seconds={args.duration}", flush=True)
        await asyncio.sleep(args.duration)
        print(f"APP_STATE_KEY_PROBE_OK counters={counters}", flush=True)
        return 0
    finally:
        await client.close()


async def print_snapshot_summary(collection: str, node: BinaryNode) -> None:
    for sync in _children(node, "sync"):
        for item in _children(sync, "collection"):
            name = item.attrs.get("name") or collection
            snapshots = _children(item, "snapshot")
            patches = _children(item, "patch")
            print(f"SNAPSHOT_RESPONSE collection={name} snapshots={len(snapshots)} patches={len(patches)}", flush=True)
            for snapshot_node in snapshots:
                if not isinstance(snapshot_node.content, bytes):
                    print(f"SNAPSHOT_EMPTY collection={name}", flush=True)
                    continue
                blob = proto.ExternalBlobReference()
                blob.ParseFromString(snapshot_node.content)
                print(
                    "SNAPSHOT_BLOB "
                    f"collection={name} "
                    f"direct_path={bool(blob.directPath)} "
                    f"media_key={bool(blob.mediaKey)} "
                    f"file_size={blob.fileSizeBytes if blob.fileSizeBytes else 0}",
                    flush=True,
                )
                data = await download_external_blob(blob, timeout=45)
                snapshot = proto.SyncdSnapshot()
                snapshot.ParseFromString(data)
                key_id = ""
                if snapshot.HasField("keyId") and snapshot.keyId.id:
                    key_id = base64.b64encode(snapshot.keyId.id).decode("ascii")
                print(
                    "SNAPSHOT "
                    f"collection={name} "
                    f"version={snapshot.version} "
                    f"records={len(snapshot.records)} "
                    f"key_id={key_id}",
                    flush=True,
                )


def _children(node: BinaryNode, tag: str) -> list[BinaryNode]:
    if not isinstance(node.content, list):
        return []
    return [child for child in node.content if isinstance(child, BinaryNode) and child.tag == tag]


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
