"""Field-aware redaction for artifacts, logs, and evidence."""

from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEYS = {
    "member_id",
    "password",
    "ssn",
    "token",
    "secret",
    "api_key",
    "authorization",
    "account_number",
}

_MEMBER_ID = re.compile(r"\b(\d{5})\b")
_SECRET_ASSIGN = re.compile(
    r"(?i)(password|token|secret|api[_-]?key)\s*[:=]\s*\S+"
)


def mask_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key.lower() in SENSITIVE_KEYS or any(part in key.lower() for part in SENSITIVE_KEYS):
        text = str(value)
        if len(text) <= 2:
            return "***"
        return "*" * max(3, len(text) - 2) + text[-2:]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(text: str) -> str:
    text = _SECRET_ASSIGN.sub(lambda m: m.group(0).split("=")[0].split(":")[0] + "=***", text)

    def _mask_id(match: re.Match[str]) -> str:
        digits = match.group(1)
        return f"***{digits[-2:]}"

    return _MEMBER_ID.sub(_mask_id, text)


def redact_event(event: dict[str, Any]) -> dict[str, Any]:
    return {k: _redact_any(k, v) for k, v in event.items()}


def _redact_any(key: str, value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _redact_any(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_any(key, item) for item in value]
    return mask_value(key, value)
