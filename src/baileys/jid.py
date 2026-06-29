from __future__ import annotations

import re
from dataclasses import dataclass

from .defaults import (
    BROADCAST_SERVER,
    GROUP_SERVER,
    HOSTED_LID_SERVER,
    HOSTED_SERVER,
    LID_SERVER,
    NEWSLETTER_SERVER,
    S_WHATSAPP_NET,
    STATUS_BROADCAST_JID,
)


DOMAIN_WHATSAPP = 0
DOMAIN_LID = 1
DOMAIN_HOSTED = 128
DOMAIN_HOSTED_LID = 129


@dataclass(frozen=True)
class JidParts:
    user: str
    server: str
    device: int = 0
    agent: int | None = None
    integrator: int | None = None
    domain_type: int = DOMAIN_WHATSAPP


def jid_decode(jid: str) -> JidParts:
    if "@" not in jid:
        raise ValueError(f"invalid jid without server: {jid!r}")

    left, server = jid.split("@", 1)
    if not left or not server:
        raise ValueError(f"invalid jid: {jid!r}")

    device = 0
    agent: int | None = None
    integrator: int | None = None

    if ":" in left:
        left, device_part = left.rsplit(":", 1)
        if not device_part.isdigit():
            raise ValueError(f"invalid jid device in {jid!r}")
        device = int(device_part)

    if "_" in left:
        user_part, agent_part = left.rsplit("_", 1)
        if agent_part.isdigit():
            left = user_part
            agent = int(agent_part)

    if "." in server:
        base_server, integrator_part = server.rsplit(".", 1)
        if integrator_part.isdigit():
            server = base_server
            integrator = int(integrator_part)

    return JidParts(
        user=left,
        server=server,
        device=device,
        agent=agent,
        integrator=integrator,
        domain_type=domain_type_for_server(server, agent=agent),
    )


def jid_decode_tuple(jid: str) -> tuple[str, str, int]:
    parts = jid_decode(jid)
    return parts.user, parts.server, parts.device


def jid_encode(
    user: str,
    server: str = S_WHATSAPP_NET,
    device: int | None = None,
    *,
    agent: int | None = None,
    integrator: int | None = None,
) -> str:
    left = str(user)
    if agent is not None:
        left = f"{left}_{agent}"
    if device:
        left = f"{left}:{device}"
    encoded_server = f"{server}.{integrator}" if integrator is not None else server
    return f"{left}@{encoded_server}"


def jid_normalized_user(jid: str) -> str:
    parts = jid_decode(jid)
    server = S_WHATSAPP_NET if parts.server == "c.us" else parts.server
    return jid_encode(parts.user, server, agent=parts.agent, integrator=parts.integrator)


def protocol_address_name_and_device(jid: str) -> tuple[str, int]:
    parts = jid_decode(jid)
    return parts.user, parts.device


def are_jids_same_user(jid1: str | None, jid2: str | None) -> bool:
    if not jid1 or not jid2:
        return False
    try:
        return jid_decode(jid1).user == jid_decode(jid2).user
    except ValueError:
        return False


def is_jid_user(jid: str) -> bool:
    return jid_decode(jid).server in {S_WHATSAPP_NET, HOSTED_SERVER}


def is_jid_group(jid: str) -> bool:
    return jid_decode(jid).server == GROUP_SERVER


def is_jid_broadcast(jid: str) -> bool:
    return jid_decode(jid).server == BROADCAST_SERVER or jid == STATUS_BROADCAST_JID


def is_jid_status(jid: str) -> bool:
    return jid == STATUS_BROADCAST_JID


def is_lid(jid: str) -> bool:
    return jid_decode(jid).server in {LID_SERVER, HOSTED_LID_SERVER}


def is_pn(jid: str) -> bool:
    return jid_decode(jid).server in {S_WHATSAPP_NET, HOSTED_SERVER}


def is_newsletter(jid: str) -> bool:
    return jid_decode(jid).server == NEWSLETTER_SERVER


def is_jid_meta_ai(jid: str | None) -> bool:
    return bool(jid and jid.endswith("@bot"))


def is_jid_bot(jid: str | None) -> bool:
    if not jid or not jid.endswith("@c.us"):
        return False
    return bool(re.match(r"^(1313555\d{4}|131655500\d{2})@", jid))


def is_hosted_pn_user(jid: str | None) -> bool:
    return bool(jid and jid.endswith(f"@{HOSTED_SERVER}"))


def is_hosted_lid_user(jid: str | None) -> bool:
    return bool(jid and jid.endswith(f"@{HOSTED_LID_SERVER}"))


def transfer_device(from_jid: str, to_jid: str) -> str:
    from_parts = jid_decode(from_jid)
    to_parts = jid_decode(to_jid)
    return jid_encode(
        to_parts.user,
        to_parts.server,
        from_parts.device,
        agent=to_parts.agent,
        integrator=to_parts.integrator,
    )


def domain_type_for_server(server: str, *, agent: int | None = None) -> int:
    if server == LID_SERVER:
        return DOMAIN_LID
    if server == HOSTED_SERVER:
        return DOMAIN_HOSTED
    if server == HOSTED_LID_SERVER:
        return DOMAIN_HOSTED_LID
    if agent is not None:
        return agent
    return DOMAIN_WHATSAPP


def server_from_domain_type(initial_server: str, domain_type: int | None = None) -> str:
    if domain_type == DOMAIN_LID:
        return LID_SERVER
    if domain_type == DOMAIN_HOSTED:
        return HOSTED_SERVER
    if domain_type == DOMAIN_HOSTED_LID:
        return HOSTED_LID_SERVER
    return initial_server


def normalize_phone_number(phone_number: str) -> str:
    return re.sub(r"\D", "", phone_number.split("@", 1)[0])


def phone_number_to_jid(phone_number: str) -> str:
    return jid_encode(normalize_phone_number(phone_number), S_WHATSAPP_NET)


areJidsSameUser = are_jids_same_user
jidDecode = jid_decode
jidEncode = jid_encode
jidNormalizedUser = jid_normalized_user
isJidBroadcast = is_jid_broadcast
isJidBot = is_jid_bot
isJidGroup = is_jid_group
isJidMetaAI = is_jid_meta_ai
isJidNewsletter = is_newsletter
isJidStatusBroadcast = is_jid_status
isLidUser = is_lid
isPnUser = is_pn
isHostedLidUser = is_hosted_lid_user
isHostedPnUser = is_hosted_pn_user
transferDevice = transfer_device
