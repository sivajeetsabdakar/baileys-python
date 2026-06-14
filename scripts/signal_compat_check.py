from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
NODE_COMPAT = ROOT / "node-compat"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from baileys.signal_crypto import (  # noqa: E402
    public_from_private,
    shared_key,
    sign,
    signal_public_from_private,
    verify,
)


PRIVATE_A = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
PRIVATE_B = bytes.fromhex("202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f")
MESSAGE = b"hello signal"

NODE_PUBLIC_A = bytes.fromhex("058f40c5adb68f25624ae5b214ea767a6ec94d829d3d7b5e1ad1ba6f3e2138285f")
NODE_PUBLIC_B = bytes.fromhex("05358072d6365880d1aeea329adf9121383851ed21a28e3b75e965d0d2cd166254")
NODE_SHARED_AB = bytes.fromhex("9663aa1da97e848a914a436d04163dfbb89178f107f1b5b77ed3854203382854")
NODE_SIGNATURE = bytes.fromhex(
    "9046777f9e290aaaf57f70a49e588e855e0d72b9a27a6e7800c625c1289dcdda36cdc6db4677d895b1b441433385900b62f6ffee56465779df9588fc68e2a004"
)


def verify_python_against_node_vectors() -> None:
    assert signal_public_from_private(PRIVATE_A) == NODE_PUBLIC_A
    assert signal_public_from_private(PRIVATE_B) == NODE_PUBLIC_B
    assert shared_key(PRIVATE_A, NODE_PUBLIC_B) == NODE_SHARED_AB
    assert shared_key(PRIVATE_B, NODE_PUBLIC_A) == NODE_SHARED_AB
    assert verify(NODE_PUBLIC_A, MESSAGE, NODE_SIGNATURE)
    print("OK Python matches libsignal public-key/agreement/signature vectors")


def verify_python_signature_in_node() -> None:
    signature = sign(PRIVATE_A, MESSAGE)
    assert verify(NODE_PUBLIC_A, MESSAGE, signature)

    script = f"""
const curve = require('libsignal/src/curve')
const pub = Buffer.from('{NODE_PUBLIC_A.hex()}', 'hex')
const msg = Buffer.from('{MESSAGE.hex()}', 'hex')
const sig = Buffer.from('{signature.hex()}', 'hex')
console.log(JSON.stringify({{ ok: curve.verifySignature(pub, msg, sig) }}))
"""
    result = subprocess.run(
        ["node", "-e", script],
        cwd=NODE_COMPAT,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    print("OK libsignal verifies Python XEdDSA signature")


def main() -> int:
    verify_python_against_node_vectors()
    verify_python_signature_in_node()
    print("Signal primitive compatibility check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

