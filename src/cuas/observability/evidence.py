from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cuas.safety.redaction import redact_event, redact_payload
from cuas.util import utc_now


class EvidenceWriter:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.log_path = self.directory / "events.jsonl"
        self.log_path.write_text("", encoding="utf-8")

    def event(self, event_type: str, **fields: Any) -> dict[str, Any]:
        payload = redact_event({"ts": utc_now(), "event": event_type, **fields})
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        return payload

    def write_json(self, name: str, data: Any) -> Path:
        path = self.directory / name
        path.write_text(
            json.dumps(redact_payload(data), indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        return path

    def path(self, name: str) -> Path:
        return self.directory / name
