from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Status(str, Enum):
    SUCCESS = "SUCCESS"
    BUSINESS_OUTCOME = "BUSINESS_OUTCOME"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"
    HARD_FAILURE = "HARD_FAILURE"
    STOPPED = "STOPPED"


class RunResult(BaseModel):
    status: Status
    run_id: str
    capability_id: str | None = None
    mode: str
    outputs: dict[str, Any] = Field(default_factory=dict)
    outcome_code: str | None = None
    message: str | None = None
    step_id: str | None = None
    expected: str | None = None
    observed: str | None = None
    intervention_id: str | None = None
    evidence_dir: str | None = None

    def ok(self) -> bool:
        return self.status in {Status.SUCCESS, Status.BUSINESS_OUTCOME}
