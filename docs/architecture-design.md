# Architecture Design

This document describes the target architecture for the rest of the package.
It is meant to keep later implementation work consistent with the current
product shape.

## Goals

- Keep `src/baileys/` as the production package.
- Keep protocol experiments and risky live probes outside the package surface.
- Preserve a Pythonic async API while retaining common Baileys aliases.
- Make account-gated WhatsApp behavior explicit through typed errors and
  compatibility matrix notes.
- Keep storage and socket logic separated so file, SQLite, Postgres, or Redis
  backends can be added without rewriting protocol code.
- Keep live probes as reusable verification tools, not as implementation style.

## Layers

### Protocol Layer

The protocol layer owns generated and wire-level behavior:

- WAProto generated classes.
- WABinary tokenized node encode/decode.
- JID parsing and normalization.
- Crypto, media keys, app-state keys, Noise, Signal, and sender-key helpers.
- WAM constants and telemetry encoding.
- WAUSync node builders and parsers.

This layer should stay deterministic and heavily covered by offline vectors.

### State Layer

The state layer owns credentials, keys, app-state cursors, mapping tables, and
message/store data:

- `AuthState`
- `CredentialStore`
- `SignalKeyStore`
- built-in JSON and directory-backed stores
- future durable adapters
- `InMemoryStore`
- future event-backed durable store

Socket code should talk to interfaces, not concrete persistence backends.

### Socket Layer

The socket layer owns connection lifecycle and WhatsApp node flow:

- WebSocket connection and Noise handshake.
- QR and pairing-code linking.
- saved reconnect, keepalive, logout, and disconnect mapping.
- query correlation.
- receive loop and node dispatch.
- automatic ACKs and retry handling.
- public `WhatsAppClient` methods.

Socket methods should build nodes, send/query them, parse responses, update
state through interfaces, and emit events. They should not know file layouts
except for the current compatibility bridge to `WhatsAppWebClient`.

### Message Layer

The message layer owns message generation, decryption, normalization, and media:

- content builders.
- outbound fanout and Signal session assertion.
- inbound decrypt and sender-key decrypt.
- retry receipt handling.
- media upload, download, encryption, and retry.
- content-specific event updates.

Message content support should be implemented as focused builder/parser helpers
with tests for each wire shape.

### API Layer

The API layer is the public surface:

- Pythonic async names are primary.
- Baileys camelCase aliases call the same implementation.
- public dataclasses and typed errors are stable.
- unsupported account-gated operations raise clear errors.

The public API guide and migration guide should be updated whenever a new
surface is added.

## Event Taxonomy

Events should stay stable and granular:

- `connection.update`
- `creds.update`
- `messages.upsert`
- `messages.update`
- `messages.media-update`
- `message-receipt.update`
- `messages.retry`
- `messages.retry_error`
- `messages.decrypt_error`
- `chats.upsert`
- `chats.update`
- `contacts.upsert`
- `contacts.update`
- `groups.update`
- `group-participants.update`
- `presence.update`
- `call`
- `notification`
- `dirty`
- `offline`

Unknown nodes should remain observable through raw node events and should not
crash the receive loop.

## Error Model

Errors should keep their source and context:

- transport failures map to deterministic disconnect reasons.
- IQ/server errors keep status, reason, and server text where available.
- account-gated behavior is reported as a server rejection, not hidden.
- unsupported local content raises a typed validation error before send.
- decrypt failures emit events and do not stop the receive loop.

## Remaining Designs

The remaining nontrivial implementation work is split into:

- `docs/storage-design.md`
- `docs/inbound-processing-design.md`
- `docs/live-verification-design.md`
- `docs/release-hardening-design.md`

Each design is intended to become a concrete implementation checklist.
