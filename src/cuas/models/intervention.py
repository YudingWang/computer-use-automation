from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

from cuas.util import utc_now


class ControlOwner(str, Enum):
    AUTOMATION = "AUTOMATION"
    HUMAN = "HUMAN"


class InterventionState(str, Enum):
    WAITING = "WAITING"
    HUMAN_OWNED = "HUMAN_OWNED"
    RESUMED = "RESUMED"
    CANCELLED = "CANCELLED"


class Intervention(BaseModel):
    intervention_id: str
    run_id: str
    capability_id: str | None = None
    step_id: str | None = None
    reason: str
    current_url: str | None = None
    screenshot_ref: str | None = None
    expected: str | None = None
    observed: str | None = None
    control_owner: ControlOwner = ControlOwner.AUTOMATION
    state: InterventionState = InterventionState.WAITING
    operator_url: str | None = None
    created_at: str = Field(default_factory=utc_now)
    human_took_control: bool = False
    human_events: list[dict] = Field(default_factory=list)
