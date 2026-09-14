"""Synthetic member records. No real PII."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

MEMBERS: dict[str, dict[str, Any]] = {
    "12345": {
        "member_id": "12345",
        "name": "Alice Chen",
        "status": "Active",
        "branch": "Downtown",
        "accounts": [
            {"id": "SA-1001", "type": "Savings", "nickname": "Primary savings", "balance": "1250.00"},
            {"id": "CK-1001", "type": "Checking", "nickname": "Everyday", "balance": "430.50"},
        ],
    },
    "67890": {
        "member_id": "67890",
        "name": "Bob Rivera",
        "status": "Active",
        "branch": "Eastside",
        "accounts": [
            {"id": "SA-2001", "type": "Savings", "nickname": "Reserve", "balance": "8900.00"},
        ],
    },
    "24680": {
        "member_id": "24680",
        "name": "Priya Nair",
        "status": "Restricted",
        "branch": "Downtown",
        "accounts": [
            {"id": "SA-3001", "type": "Savings", "nickname": "Primary savings", "balance": "210.00"},
        ],
    },
}

ACCOUNT_SEQ = 9000


def lookup_member(member_id: str) -> dict[str, Any] | None:
    record = MEMBERS.get(str(member_id).strip())
    return deepcopy(record) if record else None


def next_account_id(account_type: str) -> str:
    global ACCOUNT_SEQ
    ACCOUNT_SEQ += 1
    prefix = "SA" if account_type.lower().startswith("sav") else "MM"
    return f"{prefix}-{ACCOUNT_SEQ}"
