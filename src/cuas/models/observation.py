from __future__ import annotations

from pydantic import BaseModel, Field


class Control(BaseModel):
    index: int
    role: str
    name: str = ""
    value: str | None = None
    frame: list[str] = Field(default_factory=list)
    placeholder: str | None = None
    enabled: bool = True


class Observation(BaseModel):
    url: str
    title: str
    aria_snapshot: str = ""
    visible_text: str = ""
    controls: list[Control] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def compact(self, max_chars: int = 6000) -> str:
        lines = [
            f"url: {self.url}",
            f"title: {self.title}",
        ]
        if self.errors:
            lines.append("errors: " + " | ".join(self.errors))
        lines.append("controls:")
        if not self.controls:
            lines.append("  (none)")
        for control in self.controls:
            frame = "/".join(control.frame) if control.frame else "top"
            value = f' value="{control.value}"' if control.value else ""
            disabled = "" if control.enabled else " disabled"
            lines.append(
                f'  [{control.index}] {control.role} "{control.name}" frame={frame}{value}{disabled}'
            )
        snap = self.aria_snapshot.strip() or self.visible_text[:1500]
        lines.append("aria:")
        lines.append(snap)
        text = "\n".join(lines)
        if len(text) > max_chars:
            return text[: max_chars - 20] + "\n...[truncated]"
        return text
