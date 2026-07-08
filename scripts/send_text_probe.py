from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys import make_socket  # noqa: E402


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds-path", default=str(ROOT / "auth" / "pairing_code_creds.json"))
    parser.add_argument("--to", required=True, help="destination jid (for example: 120363427206088684@g.us)")
    parser.add_argument("--text", default="Python Baileys test message")
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--watch", type=int, default=30)
    parser.add_argument("--direct-enc", action="store_true", help="send without USync fanout")
    parser.add_argument("--participants-wrapper", action="store_true", help="kept for compatibility; uses USync fanout")
    parser.add_argument("--fanout-own-pn", action="store_true", help="kept for compatibility; product fanout decides own devices")
    parser.add_argument("--usync-fanout", action="store_true", help="discover devices with USync and send participants fanout")
    parser.add_argument("--force-usync-sessions", action="store_true", help="force encrypt session refresh for USync recipients")
    parser.add_argument("--include-phash", action="store_true", help="attach participant hash to outbound message attrs")
    args = parser.parse_args()

    client = make_socket(args.creds_path)
    try:
        await client.connect_and_wait(success_timeout=args.timeout)
        use_usync = False if args.direct_enc else (args.usync_fanout or args.participants_wrapper or args.to.endswith("@g.us"))
        result = await client.send_message(
            args.to,
            args.text,
            use_usync=use_usync,
            force_sessions=args.force_usync_sessions,
            include_phash=args.include_phash,
            timeout=args.timeout,
            wait_for_ack=args.watch,
        )
        print(
            f"SEND_TEXT_PROBE_DONE id={result.message_id} to={result.remote_jid} "
            f"participants={result.participant_jids} related_response={result.acked}",
            flush=True,
        )
    finally:
        await client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
