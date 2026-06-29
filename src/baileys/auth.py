from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SignalKeyPairData:
    public: str
    private: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalKeyPairData":
        return cls(public=str(data["public"]), private=str(data["private"]))

    def to_dict(self) -> dict[str, str]:
        return {"public": self.public, "private": self.private}


@dataclass(frozen=True)
class MeInfo:
    id: str
    lid: str | None = None
    name: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MeInfo":
        return cls(id=str(data["id"]), lid=data.get("lid"), name=data.get("name"))

    def to_dict(self) -> dict[str, str]:
        out = {"id": self.id}
        if self.lid is not None:
            out["lid"] = self.lid
        if self.name is not None:
            out["name"] = self.name
        return out


@dataclass
class AuthCredentials:
    identity_public: str
    identity_private: str
    registration_id: int
    signed_pre_key_id: int
    signed_pre_key_public: str
    signed_pre_key_private: str
    signed_pre_key_signature: str
    noise_public: str | None = None
    noise_private: str | None = None
    adv_secret_key: str | None = None
    signed_pre_key_timestamp: int | None = None
    account: str | None = None
    me: MeInfo | None = None
    platform: str | None = None
    routing_info: str | None = None
    pre_keys: dict[str, SignalKeyPairData] = field(default_factory=dict)
    signal_sessions: dict[str, str] = field(default_factory=dict)
    sender_keys: dict[str, str] = field(default_factory=dict)
    next_pre_key_id: int | None = None
    first_unuploaded_pre_key_id: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuthCredentials":
        known = {
            "identity_public",
            "identity_private",
            "registration_id",
            "signed_pre_key_id",
            "signed_pre_key_public",
            "signed_pre_key_private",
            "signed_pre_key_signature",
            "noise_public",
            "noise_private",
            "adv_secret_key",
            "signed_pre_key_timestamp",
            "account",
            "me",
            "platform",
            "routing_info",
            "pre_keys",
            "signal_sessions",
            "sender_keys",
            "next_pre_key_id",
            "first_unuploaded_pre_key_id",
        }
        return cls(
            identity_public=str(data["identity_public"]),
            identity_private=str(data["identity_private"]),
            registration_id=int(data["registration_id"]),
            signed_pre_key_id=int(data["signed_pre_key_id"]),
            signed_pre_key_public=str(data["signed_pre_key_public"]),
            signed_pre_key_private=str(data["signed_pre_key_private"]),
            signed_pre_key_signature=str(data["signed_pre_key_signature"]),
            noise_public=data.get("noise_public"),
            noise_private=data.get("noise_private"),
            adv_secret_key=data.get("adv_secret_key"),
            signed_pre_key_timestamp=(
                int(data["signed_pre_key_timestamp"]) if data.get("signed_pre_key_timestamp") is not None else None
            ),
            account=data.get("account"),
            me=MeInfo.from_dict(data["me"]) if data.get("me") else None,
            platform=data.get("platform"),
            routing_info=data.get("routing_info"),
            pre_keys={
                str(key_id): SignalKeyPairData.from_dict(pair)
                for key_id, pair in (data.get("pre_keys") or {}).items()
            },
            signal_sessions={str(key): str(value) for key, value in (data.get("signal_sessions") or {}).items()},
            sender_keys={str(key): str(value) for key, value in (data.get("sender_keys") or {}).items()},
            next_pre_key_id=int(data["next_pre_key_id"]) if data.get("next_pre_key_id") is not None else None,
            first_unuploaded_pre_key_id=(
                int(data["first_unuploaded_pre_key_id"])
                if data.get("first_unuploaded_pre_key_id") is not None
                else None
            ),
            extra={key: value for key, value in data.items() if key not in known},
        )

    @classmethod
    def from_json_file(cls, path: str | Path) -> "AuthCredentials":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "identity_public": self.identity_public,
            "identity_private": self.identity_private,
            "registration_id": self.registration_id,
            "signed_pre_key_id": self.signed_pre_key_id,
            "signed_pre_key_public": self.signed_pre_key_public,
            "signed_pre_key_private": self.signed_pre_key_private,
            "signed_pre_key_signature": self.signed_pre_key_signature,
        }
        optional = {
            "noise_public": self.noise_public,
            "noise_private": self.noise_private,
            "adv_secret_key": self.adv_secret_key,
            "signed_pre_key_timestamp": self.signed_pre_key_timestamp,
            "account": self.account,
            "platform": self.platform,
            "routing_info": self.routing_info,
            "next_pre_key_id": self.next_pre_key_id,
            "first_unuploaded_pre_key_id": self.first_unuploaded_pre_key_id,
        }
        out.update({key: value for key, value in optional.items() if value is not None})
        if self.me is not None:
            out["me"] = self.me.to_dict()
        if self.pre_keys:
            out["pre_keys"] = {key: value.to_dict() for key, value in self.pre_keys.items()}
        if self.signal_sessions:
            out["signal_sessions"] = dict(self.signal_sessions)
        if self.sender_keys:
            out["sender_keys"] = dict(self.sender_keys)
        out.update(self.extra)
        return out

    def save_json_file(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
