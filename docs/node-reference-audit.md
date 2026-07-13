# Node Reference Audit

The local Node reference is Baileys `7.0.0-rc13`. Public socket parity is
tracked by `tests/fixtures/public_api_parity.json` and checked with:

```powershell
python scripts/audit_node_public_api.py --node-root ../Baileys-master/Baileys-master
```

The audit parses socket factory return objects from the Node source and compares
them with the Python parity manifest. Internal low-level return keys such as
`ev`, `ws`, `query`, mutexes, caches, and raw socket helpers are reported as
ignored internals rather than public parity gaps.

Current result:

- Node socket keys parsed: 126
- Tracked Python manifest methods: 134
- Missing in Python manifest: none

Manifest entries that are not direct Node factory keys are intentional
compatibility wrappers or Python-visible aliases:

- `communityAcceptInviteV4`
- `communityInviteInfo`
- `communityRevokeInviteV4`
- `fetchMessageCappingInfo`
- `groupParticipantsUpdateOrInvite`
- `sendWAM`
- `updateBusinessProfile`
- `updatePrivacySetting`

Deferred live-proof items stay in `docs/compatibility-matrix.md` and
`docs/release-hardening-design.md`. They are not treated as missing API surface
when the code path and offline tests exist but the account/server condition is
not currently available.
