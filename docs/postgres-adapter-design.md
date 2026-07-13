# Postgres Adapter Design

Postgres support should follow the SQLite store semantics and stay optional.
Core installs should not require a database driver.

## Package Boundary

- Keep Postgres behind the `postgres` optional dependency.
- Do not import the driver from `baileys.__init__` unless the adapter module is
  explicitly imported.
- Accept an application-supplied connection pool where possible.
- Keep socket code dependent on the same credential, signal-key, replay, and
  event-store method shapes already used by JSON, directory, memory, and SQLite
  stores.

## Driver

Use `psycopg` v3 with pool support:

```powershell
pip install "baileys-python[postgres]"
```

The adapter should support sync methods first because the current store
interfaces are sync. If async stores are added later, expose them as separate
classes instead of mixing awaitable behavior into existing methods.

## Logical Schema

Use the same logical tables as `SQLiteEventStore`:

- `credentials`
- `signal_keys`
- `recent_outbound`
- `messages`
- `message_updates`
- `message_receipts`
- `reactions`
- `chats`
- `contacts`
- `lid_pn_mappings`
- `app_state`

Column differences:

- Use `jsonb` for credential, signal-key, update, receipt, reaction, app-state,
  and BinaryNode JSON payloads.
- Use `bytea` for protobuf message bytes.
- Use `timestamptz` or `bigint` consistently for `updated_at`; `bigint`
  seconds keeps parity with SQLite and JSON stores.

## Implementation Status

The first sync adapter pass is available through `PostgresCredentialStore`,
`PostgresSignalKeyStore`, `PostgresReplayStore`, `PostgresEventStore`,
`use_postgres_auth_state`, and `make_postgres_event_store`, with camelCase
aliases for common migration paths. The adapter accepts a `conninfo`, a
connection pool, or an application-supplied connection object.

Current coverage validates the store contract with a mocked local connection so
core installs do not require `psycopg` or a database. An opt-in live Postgres
integration test also proves credential, signal-key, replay, event-store,
LID/PN, and app-state round-trips against a disposable database. The migration
runner records applied versions in `baileys_schema_migrations`, uses a
transaction-scoped advisory lock, and has opt-in live concurrent-writer proof.

Application-supplied connections should use dict-like rows, such as
`psycopg.rows.dict_row`, matching the adapter-created connection path.

## Transactions

Credential, signal-key, session, and prekey changes that belong to a single
socket action must commit together. Failed operations must not leave partial
Signal state behind.

Recommended rules:

- Use a transaction per public store method by default.
- Keep account-level auth mutations owned by one process or add application
  locks around higher-level credential and Signal-session workflows.
- Use row-level locks for the credential row when rotating signed prekeys,
  uploading prekeys, or injecting sessions.
- Use advisory locks for account-wide operations that span credentials, signal
  keys, and app-state state.

## Migrations

Migrations are versioned and idempotent. `apply_postgres_migrations` /
`applyPostgresMigrations` can run directly when an application wants to prepare
the schema before constructing store objects.

Recommended order:

1. Base auth and signal-key tables.
2. Replay table and expiry index.
3. Event-store tables.
4. LID/PN and app-state indexes.
5. Optional media cache table.

## Acceptance

- SQLite and Postgres stores pass the same store contract tests.
- Package import works without `psycopg` installed.
- Postgres extra installs cleanly in a fresh environment.
- Concurrent migration runners do not corrupt the schema ledger.
- Recent outbound replay, LID/PN mapping, and app-state state survive process
  restarts.
