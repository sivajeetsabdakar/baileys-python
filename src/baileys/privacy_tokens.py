from __future__ import annotations

import base64
import json
import re
import time
from typing import Callable, Iterable

from .auth_state import SignalKeyStore
from .jid import is_jid_bot, is_jid_meta_ai, is_lid, is_pn, jid_normalized_user
from .socket_nodes import find_child
from .wabinary import BinaryNode


TC_TOKEN_INDEX_KEY = "__index"
TC_TOKEN_BUCKET_DURATION = 604800
TC_TOKEN_NUM_BUCKETS = 4
BOT_PHONE_RE = re.compile(r"^1313555\d{4}$|^131655500\d{2}$")


def is_tc_token_expired(timestamp: int | str | None) -> bool:
    if timestamp is None:
        return True
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return True
    current_bucket = int(time.time()) // TC_TOKEN_BUCKET_DURATION
    cutoff = (current_bucket - (TC_TOKEN_NUM_BUCKETS - 1)) * TC_TOKEN_BUCKET_DURATION
    return ts < cutoff


def should_send_new_tc_token(sender_timestamp: int | None) -> bool:
    if sender_timestamp is None:
        return True
    current_bucket = int(time.time()) // TC_TOKEN_BUCKET_DURATION
    return current_bucket > int(sender_timestamp) // TC_TOKEN_BUCKET_DURATION


def is_regular_user(jid: str | None) -> bool:
    if not jid:
        return False
    user = jid.split("@", 1)[0]
    if user == "0" or BOT_PHONE_RE.match(user):
        return False
    if is_jid_bot(jid) or is_jid_meta_ai(jid):
        return False
    return is_pn(jid) or is_lid(jid) or jid.endswith("@c.us")


def read_tc_token_index(store: SignalKeyStore) -> list[str]:
    entry = store.get("tctoken", TC_TOKEN_INDEX_KEY)
    token = _entry_token(entry)
    if not token:
        return []
    try:
        parsed = json.loads(token.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str) and item and item != TC_TOKEN_INDEX_KEY]


def write_tc_token_index(store: SignalKeyStore, added_jids: Iterable[str]) -> None:
    merged = set(read_tc_token_index(store))
    merged.update(jid for jid in added_jids if jid and jid != TC_TOKEN_INDEX_KEY)
    store.set("tctoken", TC_TOKEN_INDEX_KEY, {"token": base64.b64encode(json.dumps(sorted(merged)).encode("utf-8")).decode("ascii")})


def build_tc_token_from_jid(
    store: SignalKeyStore,
    jid: str,
    *,
    base_content: list[BinaryNode] | None = None,
    get_lid_for_pn: Callable[[str], str | None] | None = None,
) -> list[BinaryNode] | None:
    content = list(base_content or [])
    storage_jid = resolve_tc_token_jid(jid, get_lid_for_pn=get_lid_for_pn)
    entry = store.get("tctoken", storage_jid)
    token = _entry_token(entry)
    if not token or is_tc_token_expired(entry.get("timestamp") if isinstance(entry, dict) else None):
        if token:
            sender_timestamp = entry.get("senderTimestamp") if isinstance(entry, dict) else None
            store.set("tctoken", storage_jid, {"token": "", "senderTimestamp": sender_timestamp} if sender_timestamp is not None else None)
        return content or None
    content.append(BinaryNode("tctoken", {}, token))
    return content


def store_tc_tokens_from_iq_result(
    store: SignalKeyStore,
    result: BinaryNode,
    fallback_jid: str,
    *,
    get_lid_for_pn: Callable[[str], str | None] | None = None,
) -> list[str]:
    tokens = find_child(result, "tokens")
    if tokens is None or not isinstance(tokens.content, list):
        return []
    stored: list[str] = []
    for child in tokens.content:
        if child.tag != "token" or child.attrs.get("type") != "trusted_contact" or not isinstance(child.content, bytes):
            continue
        raw_jid = jid_normalized_user(fallback_jid or child.attrs.get("jid", ""))
        if not is_regular_user(raw_jid):
            continue
        timestamp = child.attrs.get("t")
        if not timestamp:
            continue
        storage_jid = resolve_tc_token_jid(raw_jid, get_lid_for_pn=get_lid_for_pn)
        existing = store.get("tctoken", storage_jid)
        try:
            existing_ts = int(existing.get("timestamp") or 0) if isinstance(existing, dict) else 0
            incoming_ts = int(timestamp)
        except (TypeError, ValueError):
            continue
        if existing_ts and existing_ts > incoming_ts:
            continue
        next_entry = dict(existing) if isinstance(existing, dict) else {}
        next_entry.update({"token": base64.b64encode(child.content).decode("ascii"), "timestamp": str(timestamp)})
        store.set("tctoken", storage_jid, next_entry)
        stored.append(storage_jid)
    if stored:
        write_tc_token_index(store, stored)
    return stored


def resolve_tc_token_jid(jid: str, *, get_lid_for_pn: Callable[[str], str | None] | None = None) -> str:
    if is_lid(jid):
        return jid
    if get_lid_for_pn is None:
        return jid
    return get_lid_for_pn(jid) or jid


def resolve_issuance_jid(
    jid: str,
    *,
    issue_to_lid: bool,
    get_lid_for_pn: Callable[[str], str | None] | None = None,
    get_pn_for_lid: Callable[[str], str | None] | None = None,
) -> str:
    if issue_to_lid:
        return resolve_tc_token_jid(jid, get_lid_for_pn=get_lid_for_pn)
    if not is_lid(jid):
        return jid
    return get_pn_for_lid(jid) if get_pn_for_lid is not None and get_pn_for_lid(jid) else jid


def _entry_token(entry) -> bytes | None:
    if not isinstance(entry, dict):
        return None
    token = entry.get("token")
    if isinstance(token, bytes):
        return token
    if isinstance(token, str) and token:
        try:
            return base64.b64decode(token)
        except ValueError:
            return token.encode("utf-8")
    return None
