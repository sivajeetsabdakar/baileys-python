from __future__ import annotations

from dataclasses import dataclass

from signal_protocol import address, curve, identity_key, protocol, session, session_cipher, state, storage


@dataclass(frozen=True)
class SignalSessionRoundTrip:
    alice_to_bob: bytes
    bob_to_alice: bytes
    prekey_message_type: int
    signal_message_type: int


def _key_pair_record() -> curve.KeyPair:
    public_key, private_key = curve.generate_keypair()
    return curve.KeyPair.from_public_and_private(public_key, private_key)


def run_signal_session_round_trip() -> SignalSessionRoundTrip:
    alice_identity = identity_key.IdentityKeyPair.generate()
    bob_identity = identity_key.IdentityKeyPair.generate()

    alice_store = storage.InMemSignalProtocolStore(alice_identity, 1111)
    bob_store = storage.InMemSignalProtocolStore(bob_identity, 2222)

    pre_key_id = 1
    signed_pre_key_id = 2

    bob_pre_key_pair = _key_pair_record()
    bob_pre_key = state.PreKeyRecord(pre_key_id, bob_pre_key_pair)
    bob_store.save_pre_key(pre_key_id, bob_pre_key)

    bob_signed_pre_key_pair = _key_pair_record()
    signed_pre_key_signature = bob_identity.private_key().calculate_signature(
        bob_signed_pre_key_pair.public_key().serialize()
    )
    bob_signed_pre_key = state.SignedPreKeyRecord(
        signed_pre_key_id,
        123456,
        bob_signed_pre_key_pair,
        signed_pre_key_signature,
    )
    bob_store.save_signed_pre_key(signed_pre_key_id, bob_signed_pre_key)

    bob_bundle = state.PreKeyBundle(
        2222,
        1,
        pre_key_id,
        bob_pre_key_pair.public_key(),
        signed_pre_key_id,
        bob_signed_pre_key_pair.public_key(),
        signed_pre_key_signature,
        bob_identity.identity_key(),
    )

    alice_address = address.ProtocolAddress("alice", 1)
    bob_address = address.ProtocolAddress("bob", 1)

    session.process_prekey_bundle(bob_address, alice_store, bob_bundle)

    prekey_ciphertext = session_cipher.message_encrypt(alice_store, bob_address, b"hello bob")
    prekey_message = protocol.PreKeySignalMessage.try_from(prekey_ciphertext.serialize())
    alice_to_bob = session_cipher.message_decrypt_prekey(bob_store, alice_address, prekey_message)

    signal_ciphertext = session_cipher.message_encrypt(bob_store, alice_address, b"hi alice")
    signal_message = protocol.SignalMessage.try_from(signal_ciphertext.serialize())
    bob_to_alice = session_cipher.message_decrypt_signal(alice_store, bob_address, signal_message)

    return SignalSessionRoundTrip(
        alice_to_bob=alice_to_bob,
        bob_to_alice=bob_to_alice,
        prekey_message_type=prekey_ciphertext.message_type(),
        signal_message_type=signal_ciphertext.message_type(),
    )

