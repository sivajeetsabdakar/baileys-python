from __future__ import annotations

from dataclasses import dataclass

from signal_protocol import address, group_cipher, identity_key, sender_keys, storage


@dataclass(frozen=True)
class GroupSenderRoundTrip:
    plaintext: bytes
    distribution_message_length: int
    ciphertext_length: int


def run_group_sender_round_trip() -> GroupSenderRoundTrip:
    sender_store = storage.InMemSignalProtocolStore(identity_key.IdentityKeyPair.generate(), 1111)
    receiver_store = storage.InMemSignalProtocolStore(identity_key.IdentityKeyPair.generate(), 2222)
    sender_address = address.ProtocolAddress("alice", 1)
    sender_name = sender_keys.SenderKeyName("group@g.us", sender_address)

    distribution_message = group_cipher.create_sender_key_distribution_message(sender_name, sender_store)
    ciphertext = group_cipher.group_encrypt(sender_store, sender_name, b"hello group")

    group_cipher.process_sender_key_distribution_message(sender_name, distribution_message, receiver_store)
    plaintext = group_cipher.group_decrypt(ciphertext, receiver_store, sender_name)

    return GroupSenderRoundTrip(
        plaintext=plaintext,
        distribution_message_length=len(distribution_message.serialize()),
        ciphertext_length=len(ciphertext),
    )

