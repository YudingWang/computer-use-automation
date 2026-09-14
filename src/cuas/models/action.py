from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    PRESS = "press"
    READ = "read"
    WAIT = "wait"
    NAVIGATE = "navigate"
    EXTRACT = "extract"
    FINISH = "finish"


class LocatorStrategy(str, Enum):
    ROLE_NAME = "role_name"
    LABEL = "label"
    PLACEHOLDER = "placeholder"
    TEXT = "text"
    CSS = "css"


class Locator(BaseModel):
    """How to find a control. Semantic strategies first; CSS is last resort."""

    strategy: LocatorStrategy
    role: str | None = None
    name: str | None = None
    text: str | None = None
    selector: str | None = None
    frame: list[str] = Field(default_factory=list, description="Frame names from the top page inward.")
    nth: int | None = None
    exact: bool = True


class Target(BaseModel):
    """Ordered locator chain. Replay requires a unique resolution unless nth is set."""

    primary: Locator
    fallbacks: list[Locator] = Field(default_factory=list)


class ActionSpec(BaseModel):
    """Surface-agnostic action. Adapters map this onto Playwright, AX, or desktop APIs."""

    type: ActionType
    target: Target | None = None
    value: str | None = None
    url: str | None = None
    key: str | None = None
    reason: str | None = Field(default=None, description="Discovery rationale; not used on replay.")
    extract_as: str | None = None
    outputs: dict[str, Any] | None = None
    goal_complete: bool = False


class RiskClass(str, Enum):
    SAFE = "safe"
    REVERSIBLE = "reversible"
    RISKY = "risky"
    BLOCKED = "blocked"


class CheckpointKind(str, Enum):
    VISIBLE_TEXT = "visible_text"
    TITLE = "title"
    URL_REGEX = "url_regex"
    ROLE_NAME = "role_name"
    ABSENT_TEXT = "absent_text"


class Checkpoint(BaseModel):
    kind: CheckpointKind
    text: str | None = None
    role: str | None = None
    name: str | None = None
    pattern: str | None = None
    timeout_ms: int = 8000


class OutcomeDetector(BaseModel):
    """Declared business outcome. Matching this is a legitimate result, not a crash."""

    code: str
    when: Checkpoint
    message: str | None = None


class RecoverableSpec(BaseModel):
    """Known runtime interruption the engine may handle without an LLM."""

    code: str
    when: Checkpoint
    resolve: ActionSpec | None = None
    on_match: Literal["dismiss", "wait", "escalate"] = "dismiss"
    max_attempts: int = 1
