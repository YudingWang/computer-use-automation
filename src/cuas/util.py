"""Small shared helpers."""

from __future__ import annotations

import re
import secrets
import socket
import time
from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(6)}"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def render_template(value: Any, params: dict[str, Any]) -> Any:
    """Replace {{param}} tokens. Non-strings are returned unchanged."""
    if not isinstance(value, str):
        return value
    pattern = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in params:
            raise KeyError(f"unbound template parameter: {key}")
        return str(params[key])

    return pattern.sub(repl, value)


def values_match(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return False
    if str(left) == str(right):
        return True
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return False


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)
