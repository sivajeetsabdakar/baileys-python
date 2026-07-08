from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
import sys

if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import make_socket  # noqa: E402


def _join(items: Iterable[str]) -> str:
    return ", ".join(items)


async def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only Phase 5 live checks.")
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "pairing_code_creds.json"))
    parser.add_argument("--group-jid", help="Optional group JID for metadata/invite checks")
    parser.add_argument("--profile-jid", help="Optional jid for profilePictureUrl", default="")
    parser.add_argument("--on-whatsapp-jid", action="append", dest="check_jids", default=[], help="One or more jids to check with onWhatsApp")
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    client = make_socket(Path(args.creds_path))
    try:
        await client.connect_and_wait(success_timeout=args.timeout)
        me = client.auth_state.credentials.get("me", {}).get("id", "")
        if not me:
            print("ME_UNKNOWN", flush=True)
            return 2

        profile_jid = args.profile_jid or me
        presence = await client.fetch_privacy_settings(timeout=20)
        print(f"PRIVACY_SETTINGS keys={_join(sorted(presence.keys()))}", flush=True)

        picture = await client.profile_picture_url(profile_jid, timeout=20)
        print(f"PROFILE_PICTURE_URL jid={profile_jid} value={picture!r}", flush=True)

        blocklist = await client.fetch_blocklist(timeout=20)
        print(f"BLOCKLIST_COUNT count={len(blocklist)}", flush=True)

        try:
            if args.check_jids:
                whatsapp = await client.on_whatsapp(*args.check_jids, timeout=20)
                print(f"ON_WHATSAPP {whatsapp}", flush=True)
            else:
                whatsapp = await client.on_whatsapp(me, timeout=20)
                print(f"ON_WHATSAPP self={whatsapp}", flush=True)
        except TimeoutError:
            print("ON_WHATSAPP TIMEOUT", flush=True)

        if args.group_jid:
            try:
                metadata = await client.group_metadata(args.group_jid, timeout=20)
                invite = await client.group_invite_code(args.group_jid, timeout=20)
                print(f"GROUP_METADATA id={metadata.id} subject={metadata.subject} size={metadata.size}", flush=True)
                print(f"GROUP_INVITE code={invite!r}", flush=True)
            except TimeoutError:
                print(f"GROUP_METADATA_TIMEOUT jid={args.group_jid}", flush=True)
        return 0
    finally:
        await client.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
