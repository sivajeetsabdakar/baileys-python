from __future__ import annotations

import argparse

from baileys import generate_pairing_code, pairing_code_hello_node


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a pairing-code request node without opening a socket.")
    parser.add_argument("--phone-number", default="15551234567")
    parser.add_argument("--tag-id", default="example-1")
    args = parser.parse_args()

    pairing_code = generate_pairing_code()
    node = pairing_code_hello_node(
        phone_number=args.phone_number,
        tag_id=args.tag_id,
        pairing_code=pairing_code,
        companion_ephemeral_public=bytes(32),
        noise_public=bytes(32),
    )

    print(pairing_code)
    print(node)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
