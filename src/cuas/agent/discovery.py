from __future__ import annotations

from pathlib import Path
from typing import Any

from cuas.agent.llm import DecisionClient, parse_decision
from cuas.agent.prompts import SYSTEM_PROMPT, user_prompt
from cuas.capability.compiler import compile_trace, target_from_control
from cuas.models.action import ActionSpec, ActionType
from cuas.models.capability import Capability
from cuas.models.observation import Control
from cuas.models.result import RunResult, Status
from cuas.observability.evidence import EvidenceWriter
from cuas.safety.policy import PolicyEngine
from cuas.surface.playwright_web import PlaywrightWebSurface
from cuas.util import new_id


class DiscoveryAgent:
    def __init__(
        self,
        client: DecisionClient,
        *,
        evidence_dir: Path,
        headed: bool = False,
        max_steps: int = 18,
        allow_risky: bool = True,
    ) -> None:
        self.client = client
        self.evidence = EvidenceWriter(evidence_dir)
        self.headed = headed
        self.max_steps = max_steps
        self.policy = PolicyEngine()
        self.policy.config.allow_risky = allow_risky
        self.surface = PlaywrightWebSurface(headed=headed)
        self.run_id = new_id("disc")
        self.events: list[dict[str, Any]] = []

    async def run(self, goal: str, start_url: str) -> tuple[RunResult, list[dict[str, Any]]]:
        await self.surface.start()
        history: list[str] = []
        try:
            nav = ActionSpec(type=ActionType.NAVIGATE, url=start_url)
            decision = self.policy.check_action(nav, current_url=start_url)
            if not decision.allowed:
                return (
                    RunResult(
                        status=Status.HARD_FAILURE,
                        run_id=self.run_id,
                        mode="discovery",
                        message=decision.reason,
                        evidence_dir=str(self.evidence.directory),
                    ),
                    self.events,
                )
            await self.surface.goto(start_url)
            self._record("navigate", url=start_url)

            for step in range(1, self.max_steps + 1):
                observation = await self.surface.observe()
                obs_payload = {
                    "event": "observation",
                    "url": observation.url,
                    "title": observation.title,
                    "visible_text": observation.visible_text[:2000],
                    "controls": [c.model_dump() for c in observation.controls],
                }
                self.events.append(obs_payload)
                self.evidence.event("observation", url=observation.url, title=observation.title, step=step)

                raw = self.client.decide(
                    SYSTEM_PROMPT,
                    user_prompt(goal, observation.compact(), history, step, self.max_steps),
                )
                self.evidence.event("decision", raw=raw, step=step)
                action = parse_decision(raw, observation.controls)
                control = _control_for(action, observation.controls)
                policy = self.policy.check_action(action, current_url=observation.url)
                if not policy.allowed:
                    self.evidence.event("policy_denied", reason=policy.reason, action=action.model_dump(mode="json"))
                    await self._screenshot("policy_denied.png")
                    return (
                        RunResult(
                            status=Status.HARD_FAILURE,
                            run_id=self.run_id,
                            mode="discovery",
                            message=policy.reason,
                            evidence_dir=str(self.evidence.directory),
                        ),
                        self.events,
                    )

                if action.type is ActionType.FINISH:
                    self._record("finish", action=action.model_dump(mode="json"), goal_complete=action.goal_complete)
                    status = Status.SUCCESS if action.goal_complete else Status.STOPPED
                    if not action.goal_complete:
                        visible = observation.visible_text
                        if "Account successfully created" in visible:
                            status = Status.SUCCESS
                            action.goal_complete = True
                    return (
                        RunResult(
                            status=status,
                            run_id=self.run_id,
                            mode="discovery",
                            outputs=action.outputs or {},
                            message=action.reason,
                            evidence_dir=str(self.evidence.directory),
                        ),
                        self.events,
                    )

                try:
                    result = await self.surface.execute(action)
                except Exception as exc:
                    await self._screenshot(f"discovery_fail_step{step}.png")
                    self.evidence.event("action_error", error=str(exc), step=step)
                    return (
                        RunResult(
                            status=Status.HARD_FAILURE,
                            run_id=self.run_id,
                            mode="discovery",
                            message=str(exc),
                            step_id=str(step),
                            evidence_dir=str(self.evidence.directory),
                        ),
                        self.events,
                    )

                after = await self.surface.observe()
                action_event = {
                    "event": "action_result",
                    "action": action.model_dump(mode="json"),
                    "control": control.model_dump() if control else None,
                    "result": {k: v for k, v in result.items() if k != "text"},
                    "title_after": after.title,
                    "visible_after": after.visible_text[:1500],
                }
                self.events.append(action_event)
                self.evidence.event(
                    "action_result",
                    type=action.type.value,
                    reason=action.reason,
                    strategy=result.get("strategy"),
                    url=result.get("url"),
                )
                history.append(f"{action.type.value} {action.target.primary.name if action.target else ''} {action.value or ''}".strip())

                if action.goal_complete or "Account successfully created" in after.visible_text:
                    await self._screenshot("discovery_success.png")
                    return (
                        RunResult(
                            status=Status.SUCCESS,
                            run_id=self.run_id,
                            mode="discovery",
                            outputs=action.outputs or {},
                            evidence_dir=str(self.evidence.directory),
                        ),
                        self.events,
                    )

            await self._screenshot("discovery_max_steps.png")
            return (
                RunResult(
                    status=Status.STOPPED,
                    run_id=self.run_id,
                    mode="discovery",
                    message="max_steps",
                    evidence_dir=str(self.evidence.directory),
                ),
                self.events,
            )
        finally:
            await self.surface.close()

    def compile(
        self,
        *,
        capability_id: str,
        description: str,
        params: dict[str, Any],
        entry_url: str,
    ) -> Capability:
        return compile_trace(
            self.events,
            capability_id=capability_id,
            description=description,
            params=params,
            entry_url=entry_url,
        )

    def _record(self, event: str, **fields: Any) -> None:
        payload = {"event": event, **fields}
        self.events.append(payload)
        self.evidence.event(event, **fields)

    async def _screenshot(self, name: str) -> None:
        try:
            await self.surface.screenshot(str(self.evidence.path(name)))
        except Exception:
            pass


def _control_for(action: ActionSpec, controls: list[Control]) -> Control | None:
    if action.target is None:
        return None
    loc = action.target.primary
    for control in controls:
        if loc.role and control.role != loc.role:
            continue
        if loc.name and control.name == loc.name and list(control.frame) == list(loc.frame):
            return control
        if loc.text and (control.placeholder == loc.text or control.name == loc.text):
            return control
    if action.target and action.target.primary.name:
        for control in controls:
            if control.name == action.target.primary.name:
                return control
    return None


def default_open_subaccount_script(params: dict[str, Any]) -> list[dict[str, Any]]:
    """Scripted teller path used by tests. Live discovery uses Grok instead."""
    member_id = str(params.get("member_id", "12345"))
    nickname = str(params.get("nickname", "Vacation"))
    deposit = str(params.get("initial_deposit", "500"))
    account_type = str(params.get("account_type", "Savings"))
    return [
        {"type": "type", "target": {"role": "textbox", "name": "Member ID", "frame": ["work"]}, "value": member_id, "reason": "enter member"},
        {"type": "click", "target": {"role": "button", "name": "Search", "frame": ["work"]}, "reason": "search"},
        {"type": "click", "target": {"role": "button", "name": "Open New Sub-account"}, "reason": "start origination"},
        {"type": "select", "target": {"role": "combobox", "name": "Account type"}, "value": account_type, "reason": "choose type"},
        {"type": "type", "target": {"role": "textbox", "placeholder": "Nickname"}, "value": nickname, "reason": "nickname"},
        {"type": "type", "target": {"role": "textbox", "placeholder": "0.00"}, "value": deposit, "reason": "deposit"},
        {"type": "click", "target": {"role": "button", "name": "Review"}, "reason": "review"},
        {"type": "click", "target": {"role": "button", "name": "Confirm Open Account"}, "reason": "confirm"},
        {"type": "finish", "goal_complete": True, "outputs": {}, "reason": "confirmation visible"},
    ]
