from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import HistorySyncResult, MessageUpsert, make_socket  # noqa: E402


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
    parser.add_argument(
        "--sync-app-state",
        action="store_true",
        help="Request and apply app-state snapshots/patches through the product sync API.",
    )
    parser.add_argument(
        "--force-snapshot",
        action="store_true",
        help="Request snapshots even when saved collection versions exist.",
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
        "app_state_syncs": 0,
        "app_state_sync_blocked": 0,
        "app_state_mutations": 0,
        "history_sets": 0,
        "history_errors": 0,
        "decrypt_errors": 0,
    }

    def on_connection(payload: dict) -> None:
        safe = {key: value for key, value in payload.items() if key != "qr"}
        print(f"EVENT connection.update {safe}", flush=True)

    def on_keys(payload: dict) -> None:
        counters["app_state_key_updates"] += 1
        print(f"EVENT app-state.keys.update {payload}", flush=True)

    def on_app_state_sync(payload) -> None:
        counters["app_state_syncs"] += len(payload)
        for item in payload:
            print(
                "EVENT app-state.sync "
                f"collection={item.collection} "
                f"version={item.state.version} "
                f"mutations={len(item.mutations)} "
                f"patches={len(item.patches)} "
                f"has_more_patches={item.has_more_patches}",
                flush=True,
            )

    def on_app_state_sync_blocked(payload: dict) -> None:
        counters["app_state_sync_blocked"] += 1
        print(
            "EVENT app-state.sync_blocked "
            f"collection={payload.get('collection')} "
            f"key_id={payload.get('key_id') or ''} "
            f"error={payload.get('error')}",
            flush=True,
        )

    def on_app_state_mutations(payload: dict) -> None:
        mutations = payload.get("mutations") or []
        counters["app_state_mutations"] += len(mutations)
        print(
            "EVENT app-state.mutations "
            f"collection={payload.get('collection')} "
            f"count={len(mutations)}",
            flush=True,
        )

    def on_history(payload: HistorySyncResult) -> None:
        counters["history_sets"] += 1
        print(
            "EVENT messaging-history.set "
            f"sync_type={payload.sync_type} "
            f"progress={payload.progress} "
            f"chats={len(payload.chats)} "
            f"contacts={len(payload.contacts)} "
            f"messages={len(payload.messages)} "
            f"mappings={len(payload.lid_pn_mappings)}",
            flush=True,
        )

    def on_history_error(payload: dict) -> None:
        counters["history_errors"] += 1
        print(f"EVENT messaging-history.error {payload.get('error')}", flush=True)

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
    client.ev.on("app-state.sync", on_app_state_sync)
    client.ev.on("app-state.sync_blocked", on_app_state_sync_blocked)
    client.ev.on("app-state.mutations", on_app_state_mutations)
    client.ev.on("messaging-history.set", on_history)
    client.ev.on("messaging-history.error", on_history_error)

    try:
        await client.connect_and_wait(success_timeout=60)
        if args.request_snapshots:
            collections = args.collections or list(DEFAULT_COLLECTIONS)
            snapshots = await client.fetch_app_state_snapshots(collections, timeout=45)
            for snapshot in snapshots:
                print(
                    "SNAPSHOT "
                    f"collection={snapshot.collection} "
                    f"version={snapshot.version} "
                    f"records={snapshot.records} "
                    f"key_id={snapshot.key_id or ''} "
                    f"has_key={snapshot.has_key} "
                    f"missing_key={snapshot.missing_key} "
                    f"has_more_patches={snapshot.has_more_patches}",
                    flush=True,
                )

        if args.sync_app_state:
            collections = args.collections or list(DEFAULT_COLLECTIONS)
            applied = await client.sync_app_state(
                collections,
                timeout=45,
                force_snapshot=args.force_snapshot,
            )
            print(f"SYNC_APP_STATE_DONE applied={len(applied)}", flush=True)

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


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
