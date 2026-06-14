from __future__ import annotations

import base64
from urllib.parse import urlencode


def base64url_no_padding(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def websocket_url_with_routing(base_url: str, routing_info: bytes | None = None) -> str:
    if not routing_info:
        return base_url
    separator = "&" if "?" in base_url else "?"
    return f"{base_url}{separator}{urlencode({'ED': base64url_no_padding(routing_info)})}"
