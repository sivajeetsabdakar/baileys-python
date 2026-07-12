from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from .wabinary import BinaryNode


LOGGER_NAME = "baileys"
REDACTED = "<redacted>"
SECRET_ATTR_PARTS = ("key", "secret", "token", "signature", "cert", "enc", "hash", "mac")
LONG_VALUE_RE = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/=]{48,}(?![A-Za-z0-9+/=])")
JID_NUMBER_RE = re.compile(r"\b\d{8,}(?=[:@])")


def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}" if name else LOGGER_NAME)


def configure_logging(level: int | str = logging.INFO, *, handler: logging.Handler | None = None) -> logging.Logger:
    logger = get_logger()
    if handler is None and not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    if handler is not None and handler not in logger.handlers:
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


def redact_value(key: str, value: Any) -> Any:
    lower_key = key.lower()
    if any(part in lower_key for part in SECRET_ATTR_PARTS):
        return REDACTED
    if not isinstance(value, str):
        return value
    redacted = JID_NUMBER_RE.sub("<number>", value)
    redacted = LONG_VALUE_RE.sub(REDACTED, redacted)
    if len(redacted) > 120:
        return f"{redacted[:48]}...{redacted[-24:]}"
    return redacted


def redact_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {key: redact_value(key, value) for key, value in mapping.items()}


def node_log_summary(node: BinaryNode) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "tag": node.tag,
        "attrs": redact_mapping(node.attrs),
    }
    if isinstance(node.content, list):
        summary["children"] = [child.tag for child in node.content if isinstance(child, BinaryNode)]
    elif isinstance(node.content, bytes):
        summary["content"] = {"type": "bytes", "length": len(node.content)}
    elif isinstance(node.content, str):
        summary["content"] = {"type": "str", "length": len(node.content)}
    elif node.content is None:
        summary["content"] = None
    else:
        summary["content"] = {"type": type(node.content).__name__}
    return summary


def exception_log_summary(exc: BaseException) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


configureLogging = configure_logging
