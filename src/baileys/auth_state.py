from __future__ import annotations

import copy
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol

from .auth import AuthCredentials


class CredentialStore(Protocol):
    def load_credentials(self) -> dict[str, Any]:
        ...

    def save_credentials(self, credentials: dict[str, Any]) -> None:
        ...


class SignalKeyStore(Protocol):
    def get(self, namespace: str, key: str) -> Any:
        ...

    def set(self, namespace: str, key: str, value: Any) -> None:
        ...

    def delete(self, namespace: str, key: str) -> bool:
        ...


@dataclass
class AuthState:
    credentials: dict[str, Any]
    credential_store: CredentialStore | None = None
    signal_store: SignalKeyStore | None = None

    @classmethod
    def from_store(
        cls,
        credential_store: CredentialStore,
        *,
        signal_store: SignalKeyStore | None = None,
        allow_missing: bool = False,
    ) -> "AuthState":
        if allow_missing and isinstance(credential_store, JsonCredentialStore) and not credential_store.path.exists():
            return cls(credentials={}, credential_store=credential_store, signal_store=signal_store)
        return cls(
            credentials=credential_store.load_credentials(),
            credential_store=credential_store,
            signal_store=signal_store,
        )

    @property
    def typed_credentials(self) -> AuthCredentials:
        return AuthCredentials.from_dict(self.credentials)

    def save_credentials(self) -> None:
        if self.credential_store is None:
            raise RuntimeError("auth state has no credential store")
        self.credential_store.save_credentials(self.credentials)

    @contextmanager
    def transaction(self) -> Iterator[dict[str, Any]]:
        working = copy.deepcopy(self.credentials)
        yield working
        self.credentials = working
        self.save_credentials()


@dataclass(frozen=True)
class JsonCredentialStore:
    path: Path

    def __init__(self, path: str | Path) -> None:
        object.__setattr__(self, "path", Path(path))

    def load_credentials(self) -> dict[str, Any]:
        return json.loads(self.path.read_text(encoding="utf-8"))

    def load_credentials_or_empty(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return self.load_credentials()

    def save_credentials(self, credentials: dict[str, Any]) -> None:
        _write_json_atomic(self.path, credentials)

    def load_typed_credentials(self) -> AuthCredentials:
        return AuthCredentials.from_dict(self.load_credentials())

    def save_typed_credentials(self, credentials: AuthCredentials) -> None:
        self.save_credentials(credentials.to_dict())


@dataclass
class MemorySignalKeyStore:
    values: dict[str, dict[str, Any]] = field(default_factory=dict)

    def get(self, namespace: str, key: str) -> Any:
        value = self.values.get(namespace, {}).get(key)
        return copy.deepcopy(value)

    def set(self, namespace: str, key: str, value: Any) -> None:
        self.values.setdefault(namespace, {})[key] = copy.deepcopy(value)

    def delete(self, namespace: str, key: str) -> bool:
        bucket = self.values.get(namespace)
        if not bucket or key not in bucket:
            return False
        del bucket[key]
        if not bucket:
            del self.values[namespace]
        return True


@dataclass(frozen=True)
class MultiFileAuthState:
    root: Path

    def __init__(self, root: str | Path) -> None:
        object.__setattr__(self, "root", Path(root))

    @property
    def credential_store(self) -> JsonCredentialStore:
        return JsonCredentialStore(self.root / "creds.json")

    def load(self) -> AuthState:
        return AuthState.from_store(
            self.credential_store,
            signal_store=DirectorySignalKeyStore(self.root / "keys"),
            allow_missing=True,
        )


@dataclass(frozen=True)
class DirectorySignalKeyStore:
    root: Path

    def __init__(self, root: str | Path) -> None:
        object.__setattr__(self, "root", Path(root))

    def get(self, namespace: str, key: str) -> Any:
        path = self._path(namespace, key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def set(self, namespace: str, key: str, value: Any) -> None:
        _write_json_atomic(self._path(namespace, key), value)

    def delete(self, namespace: str, key: str) -> bool:
        path = self._path(namespace, key)
        if not path.exists():
            return False
        path.unlink()
        return True

    def _path(self, namespace: str, key: str) -> Path:
        return self.root / _safe_component(namespace) / f"{_safe_component(key)}.json"


def use_multi_file_auth_state(root: str | Path) -> MultiFileAuthState:
    return MultiFileAuthState(root)


useMultiFileAuthState = use_multi_file_auth_state


def _safe_component(value: str) -> str:
    return value.replace("/", "__").replace("\\", "__").replace(":", "-")


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp_path.write_text(json.dumps(value, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()
