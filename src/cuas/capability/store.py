from __future__ import annotations

import json
from pathlib import Path

from cuas.models.capability import Capability


class CapabilityStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, capability_id: str, version: str = "1.0.0") -> Path:
        safe = capability_id.replace("/", "_")
        return self.directory / f"{safe}.v{version}.json"

    def save(self, capability: Capability) -> Path:
        path = self.path_for(capability.id, capability.version)
        path.write_text(capability.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return path

    def load(self, path: Path) -> Capability:
        return Capability.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[Capability]:
        items = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                items.append(self.load(path))
            except Exception:
                continue
        return items

    def get(self, capability_id: str) -> Capability:
        matches = [c for c in self.list() if c.id == capability_id]
        if not matches:
            raise FileNotFoundError(capability_id)
        return matches[-1]


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
