# Full Baileys-Python Roadmap

## Goal

Build `Baileys-python` into a full Python equivalent of local Node Baileys
`7.0.0-rc13`, using `../baileys-python-test` only as the proven reference lab.

The API should be Pythonic async first, with compatibility aliases for common
Baileys names such as `sendMessage`, `relayMessage`, `groupMetadata`,
`useMultiFileAuthState`, and `downloadMediaMessage`.

## Timeline

| Phase | Target | Status |
| --- | --- | --- |
| 0 | Product repo bootstrap | Done |
| 1 | Protocol foundation | Seeded from spike |
| 2 | Auth and socket lifecycle | Seeded baseline |
| 3 | Event/store and inbound pipeline | Not started |
| 4 | Outbound messages and media breadth | Not started |
| 5 | Chats, profile, privacy, groups | Not started |
| 6 | History and app-state completeness | Not started |
| 7 | Business, newsletters, communities, edge surfaces | Not started |
| 8 | Core beta release hardening | Not started |
| 9 | Full parity hardening | Not started |

## Release Strategy

Ship a core beta before full parity once auth, sockets, events, common
send/receive, media, groups, profile/privacy, docs, examples, and live smoke
tests are stable.

## Phase 0 Delivered

- `src/baileys/` package seeded from the proven spike.
- `pyproject.toml`, package data, README, examples, tests, and live probe
  scripts added.
- Compatibility matrix created against Node Baileys `7.0.0-rc13`.
- Baseline verification: editable install, example execution, compile check,
  and offline tests.
