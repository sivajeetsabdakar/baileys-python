from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.signal_session_probe import run_signal_session_round_trip  # noqa: E402


def main() -> int:
    result = run_signal_session_round_trip()
    print(f"OK Alice -> Bob prekey decrypt: {result.alice_to_bob!r}")
    print(f"OK Bob -> Alice signal decrypt: {result.bob_to_alice!r}")
    print("Signal session compatibility check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

