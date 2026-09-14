"""Runtime policy. Discovery and replay share the same engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from cuas.models.action import ActionSpec, ActionType, RiskClass
from cuas.models.capability import Capability, Step


@dataclass
class PolicyConfig:
    allowed_hosts: list[str] = field(default_factory=lambda: ["127.0.0.1", "localhost"])
    allowed_actions: list[str] = field(
        default_factory=lambda: [t.value for t in ActionType]
    )
    blocked_actions: list[str] = field(default_factory=lambda: ["eval_js", "file_upload"])
    risky_button_names: list[str] = field(
        default_factory=lambda: ["Confirm Open Account", "Submit Transfer", "Delete"]
    )
    allow_risky: bool = False


@dataclass
class PolicyDecision:
    allowed: bool
    risk: RiskClass
    reason: str


class PolicyEngine:
    def __init__(self, config: PolicyConfig | None = None) -> None:
        self.config = config or PolicyConfig()

    @classmethod
    def from_capability(cls, capability: Capability, *, allow_risky: bool) -> PolicyEngine:
        cfg = PolicyConfig(
            allowed_hosts=list(capability.policy.allowed_hosts),
            allowed_actions=list(capability.policy.allowed_actions),
            allow_risky=allow_risky,
        )
        return cls(cfg)

    def check_url(self, url: str) -> PolicyDecision:
        host = urlparse(url).hostname or ""
        if host not in self.config.allowed_hosts:
            return PolicyDecision(False, RiskClass.BLOCKED, f"host not allowlisted: {host}")
        return PolicyDecision(True, RiskClass.SAFE, "allowlisted host")

    def check_action(self, action: ActionSpec, *, current_url: str | None = None) -> PolicyDecision:
        if action.type.value in self.config.blocked_actions:
            return PolicyDecision(False, RiskClass.BLOCKED, f"action type blocked: {action.type}")
        if action.type.value not in self.config.allowed_actions:
            return PolicyDecision(False, RiskClass.BLOCKED, f"action type not allowed: {action.type}")
        if action.type is ActionType.NAVIGATE and action.url:
            decision = self.check_url(action.url)
            if not decision.allowed:
                return decision
        if current_url:
            decision = self.check_url(current_url)
            if not decision.allowed:
                return decision
        risk = self._risk_for_action(action)
        if risk is RiskClass.BLOCKED:
            return PolicyDecision(False, risk, "action is blocked by risk class")
        if risk is RiskClass.RISKY and not self.config.allow_risky:
            return PolicyDecision(
                False,
                risk,
                "risky/irreversible action requires approval or a human",
            )
        return PolicyDecision(True, risk, "ok")

    def check_step(self, step: Step, capability: Capability, *, current_url: str | None) -> PolicyDecision:
        if step.action.value not in self.config.allowed_actions:
            return PolicyDecision(False, RiskClass.BLOCKED, f"action type not allowed: {step.action}")
        if current_url:
            decision = self.check_url(current_url)
            if not decision.allowed:
                return decision
        risk = step.risk
        if step.id in capability.policy.risky_step_ids:
            risk = RiskClass.RISKY
        if risk is RiskClass.RISKY and not self.config.allow_risky:
            return PolicyDecision(
                False,
                risk,
                f"step {step.id} is risky and not auto-approved",
            )
        return PolicyDecision(True, risk, "ok")

    def _risk_for_action(self, action: ActionSpec) -> RiskClass:
        if action.type in {ActionType.READ, ActionType.WAIT, ActionType.EXTRACT, ActionType.FINISH}:
            return RiskClass.SAFE
        name = ""
        if action.target:
            name = action.target.primary.name or action.target.primary.text or ""
        if name in self.config.risky_button_names:
            return RiskClass.RISKY
        if action.type is ActionType.NAVIGATE:
            return RiskClass.REVERSIBLE
        return RiskClass.REVERSIBLE
