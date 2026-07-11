from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any, Iterable

from signal_protocol import address, session_cipher

from baileys.auth_store import build_signal_store, export_session, unb64
from baileys.generated import WAProto_pb2 as proto
from baileys.jid import jid_decode_tuple
from baileys.wabinary import BinaryNode


@dataclass(frozen=True)
class OutboundMessage:
    node: BinaryNode
    message_id: str
    signal_type: str
    recipient_address: address.ProtocolAddress
    participant_jids: list[str]
    signal_types: dict[str, str]


@dataclass(frozen=True)
class MessageOptions:
    quoted: proto.MessageKey | dict[str, Any] | None = None
    mentions: list[str] | None = None
    forwarding_score: int | None = None
    is_forwarded: bool = False


class UnsupportedMessageContent(ValueError):
    pass


def jid_decode(jid: str) -> tuple[str, str, int]:
    return jid_decode_tuple(jid)


def jid_encode(user: str, server: str, device: int | None = None) -> str:
    from baileys.jid import jid_encode as _jid_encode

    return _jid_encode(user, server, device)


def protocol_address_for_jid(jid: str) -> address.ProtocolAddress:
    user, _, device = jid_decode(jid)
    return address.ProtocolAddress(user, device)


def generate_message_id(user_jid: str | None = None) -> str:
    data = bytearray(8 + 20 + 16)
    data[:8] = int(time.time()).to_bytes(8, "big")
    if user_jid:
        user, _, _ = jid_decode(user_jid)
        user_bytes = user.encode("ascii")[:15]
        data[8 : 8 + len(user_bytes)] = user_bytes
        data[8 + len(user_bytes) : 8 + len(user_bytes) + 5] = b"@c.us"
    data[28:] = os.urandom(16)
    return "3EB0" + hashlib.sha256(data).hexdigest().upper()[:18]


def random_pad_max_16(data: bytes) -> bytes:
    pad = (os.urandom(1)[0] & 0x0F) + 1
    return data + bytes([pad]) * pad


def participant_hash_v2(participants: list[str]) -> str:
    joined = "".join(sorted(participants)).encode("utf-8")
    digest = hashlib.sha256(joined).digest()
    import base64

    return "2:" + base64.b64encode(digest).decode("ascii")[:6]


def text_message(text: str) -> proto.Message:
    message = proto.Message()
    message.conversation = text
    message.messageContextInfo.messageSecret = os.urandom(32)
    return message


def extended_text_message(text: str, options: MessageOptions | None = None) -> proto.Message:
    message = proto.Message()
    message.extendedTextMessage.text = text
    _apply_context_info(message.extendedTextMessage.contextInfo, options)
    message.messageContextInfo.messageSecret = os.urandom(32)
    return message


def reaction_message(key: proto.MessageKey | dict[str, Any], text: str = "") -> proto.Message:
    message = proto.Message()
    message.reactionMessage.key.CopyFrom(_coerce_message_key(key))
    message.reactionMessage.text = text
    message.reactionMessage.senderTimestampMs = int(time.time() * 1000)
    message.messageContextInfo.messageSecret = os.urandom(32)
    return message


def delete_message(key: proto.MessageKey | dict[str, Any]) -> proto.Message:
    message = proto.Message()
    message.protocolMessage.key.CopyFrom(_coerce_message_key(key))
    message.protocolMessage.type = proto.Message.ProtocolMessage.Type.REVOKE
    message.messageContextInfo.messageSecret = os.urandom(32)
    return message


def edit_message(key: proto.MessageKey | dict[str, Any], text: str) -> proto.Message:
    edited = text_message(text)
    message = proto.Message()
    message.protocolMessage.key.CopyFrom(_coerce_message_key(key))
    message.protocolMessage.type = proto.Message.ProtocolMessage.Type.MESSAGE_EDIT
    message.protocolMessage.editedMessage.CopyFrom(edited)
    message.protocolMessage.timestampMs = int(time.time() * 1000)
    message.messageContextInfo.messageSecret = os.urandom(32)
    return message


def pin_message(key: proto.MessageKey | dict[str, Any], *, pin: bool = True, duration: int = 86400) -> proto.Message:
    message = proto.Message()
    message.pinInChatMessage.key.CopyFrom(_coerce_message_key(key))
    message.pinInChatMessage.type = (
        proto.Message.PinInChatMessage.PIN_FOR_ALL if pin else proto.Message.PinInChatMessage.UNPIN_FOR_ALL
    )
    message.pinInChatMessage.senderTimestampMs = int(time.time() * 1000)
    message.messageContextInfo.messageAddOnDurationInSecs = int(duration) if pin else 0
    message.messageContextInfo.messageSecret = os.urandom(32)
    return message


def poll_message(
    name: str,
    values: Iterable[str],
    *,
    selectable_count: int = 1,
    to_announcement_group: bool = False,
) -> proto.Message:
    options = [str(value) for value in values]
    if not options:
        raise UnsupportedMessageContent("poll content requires at least one option")
    if selectable_count < 0 or selectable_count > len(options):
        raise UnsupportedMessageContent("poll selectable_count must be between 0 and option count")

    message = proto.Message()
    message.messageContextInfo.messageSecret = os.urandom(32)
    target = (
        message.pollCreationMessageV2
        if to_announcement_group
        else message.pollCreationMessageV3
        if selectable_count == 1
        else message.pollCreationMessage
    )
    target.name = name
    target.selectableOptionsCount = selectable_count
    for option_name in options:
        target.options.add().optionName = option_name
    return message


def location_message(
    latitude: float,
    longitude: float,
    *,
    name: str | None = None,
    address_text: str | None = None,
    url: str | None = None,
) -> proto.Message:
    message = proto.Message()
    location = message.locationMessage
    location.degreesLatitude = latitude
    location.degreesLongitude = longitude
    if name:
        location.name = name
    if address_text:
        location.address = address_text
    if url:
        location.url = url
    message.messageContextInfo.messageSecret = os.urandom(32)
    return message


def contact_message(display_name: str, vcard: str) -> proto.Message:
    message = proto.Message()
    contact = message.contactMessage
    contact.displayName = display_name
    contact.vcard = vcard
    message.messageContextInfo.messageSecret = os.urandom(32)
    return message


def contacts_array_message(display_name: str, contacts: Iterable[dict[str, str]]) -> proto.Message:
    message = proto.Message()
    array = message.contactsArrayMessage
    array.displayName = display_name
    for item in contacts:
        contact = array.contacts.add()
        contact.displayName = item["display_name"]
        contact.vcard = item["vcard"]
    message.messageContextInfo.messageSecret = os.urandom(32)
    return message


def group_invite_message(
    group_jid: str,
    invite_code: str,
    group_name: str,
    *,
    invite_expiration: int = 0,
    caption: str | None = None,
    jpeg_thumbnail: bytes | None = None,
) -> proto.Message:
    message = proto.Message()
    invite = message.groupInviteMessage
    invite.groupJid = group_jid
    invite.inviteCode = invite_code
    invite.inviteExpiration = int(invite_expiration)
    invite.groupName = group_name
    if caption:
        invite.caption = caption
    if jpeg_thumbnail:
        invite.jpegThumbnail = jpeg_thumbnail
    message.messageContextInfo.messageSecret = os.urandom(32)
    return message


def normalize_message_content(content: str | proto.Message | dict[str, Any]) -> tuple[proto.Message, str]:
    if isinstance(content, proto.Message):
        return content, _message_type_for_proto(content)
    if isinstance(content, str):
        return text_message(content), "text"
    if not isinstance(content, dict):
        raise UnsupportedMessageContent(f"unsupported message content: {type(content).__name__}")

    options = _options_from_dict(content)
    if "text" in content:
        text = str(content["text"])
        if options.mentions or options.quoted or options.forwarding_score or options.is_forwarded:
            return extended_text_message(text, options), "text"
        return text_message(text), "text"
    if "extended_text" in content:
        return extended_text_message(str(content["extended_text"]), options), "text"
    if "reaction" in content:
        reaction = content["reaction"]
        if not isinstance(reaction, dict) or "key" not in reaction:
            raise UnsupportedMessageContent("reaction content requires a key")
        return reaction_message(reaction["key"], str(reaction.get("text", ""))), "reaction"
    if "delete" in content:
        return delete_message(content["delete"]), "protocol"
    if "edit" in content:
        edit = content["edit"]
        if not isinstance(edit, dict) or "key" not in edit or "text" not in edit:
            raise UnsupportedMessageContent("edit content requires key and text")
        return edit_message(edit["key"], str(edit["text"])), "protocol"
    if "pin" in content:
        pin = content["pin"]
        if not isinstance(pin, dict) or "key" not in pin:
            raise UnsupportedMessageContent("pin content requires a key")
        return (
            pin_message(pin["key"], pin=bool(pin.get("pin", True)), duration=int(pin.get("duration", 86400))),
            "text",
        )
    if "poll" in content:
        poll = content["poll"]
        if not isinstance(poll, dict) or "name" not in poll or "values" not in poll:
            raise UnsupportedMessageContent("poll content requires name and values")
        values = poll["values"]
        if not isinstance(values, list):
            raise UnsupportedMessageContent("poll values must be a list")
        return (
            poll_message(
                str(poll["name"]),
                [str(value) for value in values],
                selectable_count=int(poll.get("selectable_count", poll.get("selectableCount", 1))),
                to_announcement_group=bool(poll.get("to_announcement_group", poll.get("toAnnouncementGroup", False))),
            ),
            "poll",
        )
    if "location" in content:
        location = content["location"]
        if not isinstance(location, dict):
            raise UnsupportedMessageContent("location content must be a mapping")
        return (
            location_message(
                float(location["latitude"]),
                float(location["longitude"]),
                name=location.get("name"),
                address_text=location.get("address"),
                url=location.get("url"),
            ),
            "location",
        )
    if "contact" in content:
        contact = content["contact"]
        if not isinstance(contact, dict):
            raise UnsupportedMessageContent("contact content must be a mapping")
        return contact_message(str(contact["display_name"]), str(contact["vcard"])), "contact"
    if "contacts" in content:
        contacts = content["contacts"]
        if not isinstance(contacts, list):
            raise UnsupportedMessageContent("contacts content must be a list")
        return contacts_array_message(str(content.get("display_name") or "Contacts"), contacts), "contacts"
    if "group_invite" in content or "groupInvite" in content:
        invite = content.get("group_invite") or content.get("groupInvite")
        if not isinstance(invite, dict):
            raise UnsupportedMessageContent("group_invite content must be a mapping")
        for key in ("jid", "invite_code", "subject"):
            if key not in invite:
                raise UnsupportedMessageContent(f"group_invite content requires {key}")
        return (
            group_invite_message(
                str(invite["jid"]),
                str(invite["invite_code"]),
                str(invite["subject"]),
                invite_expiration=int(invite.get("invite_expiration", invite.get("inviteExpiration", 0))),
                caption=invite.get("caption") or invite.get("text"),
                jpeg_thumbnail=invite.get("jpeg_thumbnail") or invite.get("jpegThumbnail"),
            ),
            "url",
        )

    raise UnsupportedMessageContent(f"unsupported message content keys: {', '.join(sorted(content))}")


def device_sent_message(destination_jid: str, message: proto.Message) -> proto.Message:
    wrapper = proto.Message()
    wrapper.deviceSentMessage.destinationJid = destination_jid
    wrapper.deviceSentMessage.message.CopyFrom(message)
    if message.HasField("messageContextInfo"):
        wrapper.messageContextInfo.CopyFrom(message.messageContextInfo)
    return wrapper


def encode_message_payload(message: proto.Message) -> bytes:
    return random_pad_max_16(message.SerializeToString())


def encrypt_for_recipient(
    creds: dict, recipient_jid: str, plaintext: bytes
) -> tuple[str, bytes, address.ProtocolAddress]:
    addr = protocol_address_for_jid(recipient_jid)
    store = build_signal_store(creds)
    encrypted = session_cipher.message_encrypt(store, addr, plaintext)
    serialized = encrypted.serialize()
    export_session(creds, store, addr)
    signal_type = "pkmsg" if encrypted.message_type() == 3 else "msg"
    return signal_type, serialized, addr


def build_encrypted_node(creds: dict, recipient_jid: str, payload: proto.Message) -> tuple[BinaryNode, str, address.ProtocolAddress]:
    signal_type, ciphertext, addr = encrypt_for_recipient(creds, recipient_jid, encode_message_payload(payload))
    return BinaryNode("enc", {"v": "2", "type": signal_type}, ciphertext), signal_type, addr


def signed_device_identity_node(creds: dict) -> BinaryNode | None:
    if not creds.get("account"):
        return None
    account = proto.ADVSignedDeviceIdentity()
    account.ParseFromString(unb64(creds["account"]))
    account.ClearField("accountSignatureKey")
    return BinaryNode("device-identity", {}, account.SerializeToString())


def build_text_message_node(
    creds: dict,
    recipient_jid: str,
    text: str,
    *,
    message_id: str | None = None,
    direct_enc: bool = True,
    recipient_device_jids: Iterable[str] | None = None,
    own_fanout_jids: Iterable[str] = (),
    include_phash: bool = False,
) -> OutboundMessage:
    return build_proto_message_node(
        creds,
        recipient_jid,
        text_message(text),
        message_type="text",
        message_id=message_id,
        direct_enc=direct_enc,
        recipient_device_jids=recipient_device_jids,
        own_fanout_jids=own_fanout_jids,
        include_phash=include_phash,
    )


def build_message_content_node(
    creds: dict,
    recipient_jid: str,
    content: str | proto.Message | dict[str, Any],
    *,
    message_id: str | None = None,
    direct_enc: bool = True,
    recipient_device_jids: Iterable[str] | None = None,
    own_fanout_jids: Iterable[str] = (),
    include_phash: bool = False,
    additional_attributes: dict[str, str] | None = None,
    additional_nodes: Iterable[BinaryNode] = (),
) -> OutboundMessage:
    message, message_type = normalize_message_content(content)
    return build_proto_message_node(
        creds,
        recipient_jid,
        message,
        message_type=message_type,
        message_id=message_id,
        direct_enc=direct_enc,
        recipient_device_jids=recipient_device_jids,
        own_fanout_jids=own_fanout_jids,
        include_phash=include_phash,
        additional_attributes=additional_attributes,
        additional_nodes=additional_nodes,
    )


def build_proto_message_node(
    creds: dict,
    recipient_jid: str,
    message: proto.Message,
    *,
    message_type: str,
    message_id: str | None = None,
    direct_enc: bool = True,
    recipient_device_jids: Iterable[str] | None = None,
    own_fanout_jids: Iterable[str] = (),
    include_phash: bool = False,
    additional_attributes: dict[str, str] | None = None,
    additional_nodes: Iterable[BinaryNode] = (),
) -> OutboundMessage:
    message_id = message_id or generate_message_id(creds.get("me", {}).get("id"))
    recipient_user, recipient_server, _ = jid_decode(recipient_jid)
    recipient_device_jid = jid_encode(recipient_user, recipient_server, 0)
    enc_node, signal_type, addr = build_encrypted_node(creds, recipient_device_jid, message)
    signal_types = {recipient_device_jid: signal_type}

    attrs = {"id": message_id, "to": recipient_jid, "type": message_type}
    if additional_attributes:
        attrs.update(additional_attributes)
    is_peer_message = additional_attributes and additional_attributes.get("category") == "peer"
    if is_peer_message:
        content = [enc_node]
        participant_jids = [recipient_device_jid]
    elif direct_enc:
        content = [enc_node]
        participant_jids = [recipient_device_jid]
    else:
        participant_nodes = []
        participant_jids = []
        target_jids = list(recipient_device_jids) if recipient_device_jids is not None else [recipient_device_jid]
        for target_jid in target_jids:
            target_enc, target_type, _ = (
                (enc_node, signal_type, addr)
                if target_jid == recipient_device_jid
                else build_encrypted_node(creds, target_jid, message)
            )
            participant_nodes.append(BinaryNode("to", {"jid": target_jid}, [target_enc]))
            participant_jids.append(target_jid)
            signal_types[target_jid] = target_type

        for own_jid in own_fanout_jids:
            own_user, own_server, own_device = jid_decode(own_jid)
            own_device_jid = jid_encode(own_user, own_server, own_device)
            own_payload = device_sent_message(recipient_jid, message)
            own_enc, _, _ = build_encrypted_node(creds, own_device_jid, own_payload)
            own_type = own_enc.attrs["type"]
            participant_nodes.append(BinaryNode("to", {"jid": own_device_jid}, [own_enc]))
            participant_jids.append(own_device_jid)
            signal_types[own_device_jid] = own_type

        if include_phash:
            attrs["phash"] = participant_hash_v2(participant_jids)
        content = [
            BinaryNode(
                "participants",
                {},
                participant_nodes,
            )
        ]
        if "pkmsg" in signal_types.values():
            device_identity = signed_device_identity_node(creds)
            if device_identity is not None:
                content.append(device_identity)

    content.extend(additional_nodes)
    return OutboundMessage(
        node=BinaryNode("message", attrs, content),
        message_id=message_id,
        signal_type=signal_type,
        recipient_address=addr,
        participant_jids=participant_jids,
        signal_types=signal_types,
    )


def _apply_context_info(context: proto.ContextInfo, options: MessageOptions | None) -> None:
    if options is None:
        return
    if options.mentions:
        context.mentionedJid.extend(options.mentions)
    if options.forwarding_score is not None:
        context.forwardingScore = options.forwarding_score
    if options.is_forwarded:
        context.isForwarded = True
    if options.quoted is not None:
        context.placeholderKey.CopyFrom(_coerce_message_key(options.quoted))


def _coerce_message_key(key: proto.MessageKey | dict[str, Any]) -> proto.MessageKey:
    if isinstance(key, proto.MessageKey):
        return key
    if not isinstance(key, dict):
        raise UnsupportedMessageContent("message key must be a proto MessageKey or mapping")
    message_key = proto.MessageKey()
    if key.get("remote_jid") or key.get("remoteJid"):
        message_key.remoteJid = str(key.get("remote_jid") or key.get("remoteJid"))
    if key.get("id"):
        message_key.id = str(key["id"])
    if key.get("participant"):
        message_key.participant = str(key["participant"])
    if key.get("from_me") is not None or key.get("fromMe") is not None:
        message_key.fromMe = bool(key.get("from_me") if key.get("from_me") is not None else key.get("fromMe"))
    return message_key


def _options_from_dict(content: dict[str, Any]) -> MessageOptions:
    return MessageOptions(
        quoted=content.get("quoted"),
        mentions=list(content.get("mentions") or []),
        forwarding_score=content.get("forwarding_score"),
        is_forwarded=bool(content.get("is_forwarded", False)),
    )


def _message_type_for_proto(message: proto.Message) -> str:
    for field, message_type in (
        ("reactionMessage", "reaction"),
        ("protocolMessage", "text"),
        ("pollCreationMessage", "poll"),
        ("pollCreationMessageV2", "poll"),
        ("pollCreationMessageV3", "poll"),
        ("pinInChatMessage", "text"),
        ("locationMessage", "location"),
        ("contactMessage", "contact"),
        ("contactsArrayMessage", "contacts"),
        ("groupInviteMessage", "url"),
        ("imageMessage", "image"),
        ("videoMessage", "video"),
        ("audioMessage", "audio"),
        ("documentMessage", "document"),
        ("stickerMessage", "sticker"),
        ("extendedTextMessage", "text"),
    ):
        if message.HasField(field):
            return message_type
    return "text"
