from __future__ import annotations

from baileys import generate_pairing_code, pairing_code_hello_node


pairing_code = generate_pairing_code()
node = pairing_code_hello_node(
    phone_number="15551234567",
    tag_id="example-1",
    pairing_code=pairing_code,
    companion_ephemeral_public=bytes(32),
    noise_public=bytes(32),
)

print(pairing_code)
print(node)
