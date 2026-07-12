from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .auth_state import AuthState
from .replay import binary_node_from_json, binary_node_to_json
from .wabinary import BinaryNode


@dataclass(frozen=True)
class SQLiteCredentialStore:
    path: Path

    def __init__(self, path: str | Path) -> None:
        object.__setattr__(self, "path", Path(path))
        _init_schema(self.path)

    def load_credentials(self) -> dict[str, Any]:
        with _connect(self.path) as db:
            row = db.execute("select value from credentials where name = 'default'").fetchone()
        if row is None:
            return {}
        return json.loads(str(row["value"]))

    def save_credentials(self, credentials: dict[str, Any]) -> None:
        payload = json.dumps(credentials, indent=2, sort_keys=True)
        with _connect(self.path) as db:
            db.execute(
                """
                insert into credentials(name, value)
                values('default', ?)
                on conflict(name) do update set value = excluded.value
                """,
                (payload,),
            )


@dataclass(frozen=True)
class SQLiteSignalKeyStore:
    path: Path

    def __init__(self, path: str | Path) -> None:
        object.__setattr__(self, "path", Path(path))
        _init_schema(self.path)

    def get(self, namespace: str, key: str) -> Any:
        with _connect(self.path) as db:
            row = db.execute(
                "select value from signal_keys where namespace = ? and key = ?",
                (namespace, key),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["value"]))

    def set(self, namespace: str, key: str, value: Any) -> None:
        payload = json.dumps(value, indent=2, sort_keys=True)
        with _connect(self.path) as db:
            db.execute(
                """
                insert into signal_keys(namespace, key, value)
                values(?, ?, ?)
                on conflict(namespace, key) do update set value = excluded.value
                """,
                (namespace, key, payload),
            )

    def delete(self, namespace: str, key: str) -> bool:
        with _connect(self.path) as db:
            cursor = db.execute(
                "delete from signal_keys where namespace = ? and key = ?",
                (namespace, key),
            )
            return cursor.rowcount > 0


@dataclass(frozen=True)
class SQLiteReplayStore:
    path: Path

    def __init__(self, path: str | Path) -> None:
        object.__setattr__(self, "path", Path(path))
        _init_schema(self.path)

    def save_recent_outbound(self, message_id: str, node: BinaryNode, expires_at: float) -> None:
        if not message_id:
            return
        payload = json.dumps(binary_node_to_json(node), separators=(",", ":"), sort_keys=True)
        with _connect(self.path) as db:
            db.execute(
                """
                insert into recent_outbound(message_id, node_json, expires_at)
                values(?, ?, ?)
                on conflict(message_id) do update set
                    node_json = excluded.node_json,
                    expires_at = excluded.expires_at
                """,
                (message_id, payload, float(expires_at)),
            )

    def load_recent_outbound(self, message_id: str) -> BinaryNode | None:
        with _connect(self.path) as db:
            row = db.execute(
                "select node_json, expires_at from recent_outbound where message_id = ?",
                (message_id,),
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) <= time.time():
                db.execute("delete from recent_outbound where message_id = ?", (message_id,))
                return None
        return binary_node_from_json(json.loads(str(row["node_json"])))

    def delete_recent_outbound(self, message_id: str) -> None:
        with _connect(self.path) as db:
            db.execute("delete from recent_outbound where message_id = ?", (message_id,))

    def prune_expired(self, now: float | None = None) -> int:
        cutoff = time.time() if now is None else now
        with _connect(self.path) as db:
            cursor = db.execute("delete from recent_outbound where expires_at <= ?", (float(cutoff),))
            return cursor.rowcount


def use_sqlite_auth_state(path: str | Path) -> AuthState:
    database = Path(path)
    return AuthState.from_store(
        SQLiteCredentialStore(database),
        signal_store=SQLiteSignalKeyStore(database),
        allow_missing=True,
    )


useSqliteAuthState = use_sqlite_auth_state


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("pragma journal_mode = wal")
    db.execute("pragma foreign_keys = on")
    return db


def _init_schema(path: Path) -> None:
    with _connect(path) as db:
        db.executescript(
            """
            create table if not exists credentials (
                name text primary key,
                value text not null
            );

            create table if not exists signal_keys (
                namespace text not null,
                key text not null,
                value text not null,
                primary key(namespace, key)
            );

            create table if not exists recent_outbound (
                message_id text primary key,
                node_json text not null,
                expires_at real not null
            );

            create index if not exists idx_recent_outbound_expires_at
                on recent_outbound(expires_at);
            """
        )
