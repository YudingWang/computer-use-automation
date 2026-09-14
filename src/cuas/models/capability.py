"""Typed, versioned, reviewable capability artifact.

The calling agent should only need `interface`. Replay uses `implementation`.
`binding` is how the same capability is reused across tenants of one vendor app
without being re-recorded for each institution.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from cuas.models.action import (
    ActionType,
    Checkpoint,
    OutcomeDetector,
    RecoverableSpec,
    RiskClass,
    Target,
)


class InputParam(BaseModel):
    type: Literal["string", "number", "boolean"] = "string"
    required: bool = True
    description: str | None = None
    sensitive: bool = False
    minimum: float | None = None
    enum: list[str] | None = None


class OutputField(BaseModel):
    type: Literal["string", "number", "boolean"] = "string"
    description: str | None = None
    sensitive: bool = False


class CapabilityInterface(BaseModel):
    """Agent-facing contract: what to supply, what you get back, what can happen."""

    name: str
    description: str
    inputs: dict[str, InputParam] = Field(default_factory=dict)
    outputs: dict[str, OutputField] = Field(default_factory=dict)
    outcomes: list[str] = Field(
        default_factory=list,
        description="Stable business-outcome codes the caller should handle.",
    )


class TenantOverride(BaseModel):
    tenant_id: str
    label: str | None = None
    locator_overrides: dict[str, Target] = Field(
        default_factory=dict,
        description="step_id → replacement target chain",
    )
    text_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Exact visible-text substitutions (e.g. Search → Find Member).",
    )


class AppBinding(BaseModel):
    app_family: str
    surface: Literal["web", "desktop"] = "web"
    entry_url: str | None = None
    compatible_versions: list[str] = Field(default_factory=lambda: ["1.0"])
    tenants: list[TenantOverride] = Field(default_factory=list)


class Extractor(BaseModel):
    output: str
    strategy: Literal["visible_regex", "label_value", "control_value"] = "visible_regex"
    pattern: str | None = None
    label: str | None = None
    target: Target | None = None


class Step(BaseModel):
    id: str
    action: ActionType
    description: str | None = None
    target: Target | None = None
    value: str | None = Field(default=None, description="Literal or {{param}} template.")
    url: str | None = None
    key: str | None = None
    extract_as: str | None = None
    checkpoint: Checkpoint | None = None
    risk: RiskClass = RiskClass.REVERSIBLE
    timeout_ms: int = 8000


class Implementation(BaseModel):
    steps: list[Step]
    success: Checkpoint
    extractors: list[Extractor] = Field(default_factory=list)
    known_outcomes: list[OutcomeDetector] = Field(default_factory=list)
    recoverables: list[RecoverableSpec] = Field(default_factory=list)


class CapabilityPolicy(BaseModel):
    allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "localhost"])
    allowed_actions: list[str] = Field(
        default_factory=lambda: [t.value for t in ActionType]
    )
    risky_step_ids: list[str] = Field(default_factory=list)


class Capability(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    id: str
    version: str = "1.0.0"
    interface: CapabilityInterface
    binding: AppBinding
    implementation: Implementation
    policy: CapabilityPolicy = Field(default_factory=CapabilityPolicy)

    def apply_tenant(self, tenant_id: str | None) -> Capability:
        """Return a copy with tenant locator/text overrides merged into steps."""
        if not tenant_id:
            return self
        override = next((t for t in self.binding.tenants if t.tenant_id == tenant_id), None)
        if override is None:
            return self
        clone = self.model_copy(deep=True)
        mapping = override.text_overrides
        for step in clone.implementation.steps:
            if step.id in override.locator_overrides:
                step.target = override.locator_overrides[step.id]
            elif step.target and mapping:
                _rewrite_target_text(step.target, mapping)
        return clone

    def summary(self) -> str:
        inputs = ", ".join(self.interface.inputs) or "(none)"
        outputs = ", ".join(self.interface.outputs) or "(none)"
        outcomes = ", ".join(self.interface.outcomes) or "(none)"
        return (
            f"{self.id}@{self.version}\n"
            f"  {self.interface.description}\n"
            f"  inputs: {inputs}\n"
            f"  outputs: {outputs}\n"
            f"  outcomes: {outcomes}\n"
            f"  steps: {len(self.implementation.steps)}  "
            f"app_family: {self.binding.app_family}  surface: {self.binding.surface}"
        )


def _rewrite_target_text(target: Target, mapping: dict[str, str]) -> None:
    for loc in [target.primary, *target.fallbacks]:
        if loc.name:
            loc.name = mapping.get(loc.name, loc.name)
        if loc.text:
            loc.text = mapping.get(loc.text, loc.text)


def dump_capability(capability: Capability) -> dict[str, Any]:
    return capability.model_dump(mode="json")
