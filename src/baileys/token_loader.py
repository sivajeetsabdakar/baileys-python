from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from typing import NamedTuple


class WABinaryTokens(NamedTuple):
    single_byte_tokens: list[str]
    double_byte_tokens: list[list[str]]
    token_map: dict[str, tuple[int | None, int]]


@lru_cache(maxsize=1)
def load_tokens() -> WABinaryTokens:
    package = "baileys.generated"
    try:
        raw = resources.files(package).joinpath("wabinary_tokens.json").read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError("Run scripts/generate_wabinary_tokens.py before tokenized binary-node checks") from exc

    payload = json.loads(raw)
    single = payload["single_byte_tokens"]
    double = payload["double_byte_tokens"]

    token_map: dict[str, tuple[int | None, int]] = {}
    for index, token in enumerate(single):
        if token:
            token_map[token] = (None, index)

    for dict_index, dictionary in enumerate(double):
        for index, token in enumerate(dictionary):
            if token:
                token_map[token] = (dict_index, index)

    return WABinaryTokens(single, double, token_map)

