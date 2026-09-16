"""Deterministic replay. No LLM in the decision loop."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable, Coroutine

from cuas.handoff.manager import HandoffManager
from cuas.models.action import ActionSpec, ActionType, RiskClass, Target
from cuas.models.capability import Capability, Step
from cuas.models.intervention import ControlOwner
from cuas.models.result import RunResult, Status
from cuas.observability.evidence import EvidenceWriter
from cuas.safety.policy import PolicyEngine
from cuas.surface.playwright_web import AmbiguousTarget, PlaywrightWebSurface, TargetNotFound
from cuas.util import monotonic_ms, new_id, render_template


class ReplayExecutor:
    def __init__(
        self,
        capability: Capability,
        params: dict[str, Any],
        *,
        evidence_dir: Path,
        headed: bool = False,
        allow_risky: bool = False,
        wait_for_operator: bool = False,
        auto_operator: Callable[[HandoffManager], Coroutine[Any, Any, None]] | None = None,
        tenant_id: str | None = None,
        start_url: str | None = None,
    ) -> None:
        self.capability = capability.apply_tenant(tenant_id)
        self.params = params
        self.evidence = EvidenceWriter(evidence_dir)
        self.headed = headed
        self.allow_risky = allow_risky
        self.wait_for_operator = wait_for_operator
        self.auto_operator = auto_operator
        self.start_url = start_url or self.capability.binding.entry_url
        self.run_id = new_id("run")
        self.surface = PlaywrightWebSurface(headed=headed)
        self.policy = PolicyEngine.from_capability(self.capability, allow_risky=allow_risky)
        self.handoff: HandoffManager | None = None
        self.outputs: dict[str, Any] = {}

    def _validate_inputs(self) -> None:
        for name, spec in self.capability.interface.inputs.items():
            if spec.required and name not in self.params:
                raise ValueError(f"missing required input: {name}")

    async def run(self) -> RunResult:
        self._validate_inputs()
        self.evidence.event(
            "replay_start",
            run_id=self.run_id,
            capability_id=self.capability.id,
            params={k: v for k, v in self.params.items()},
        )
        await self.surface.start()
        self.handoff = HandoffManager(
            self.surface,
            self.evidence,
            self.run_id,
            capability_id=self.capability.id,
            auto_operator=self.auto_operator,
        )
        await self.handoff.start()
        try:
            if not self.start_url:
                raise RuntimeError("capability has no entry_url")
            nav = ActionSpec(type=ActionType.NAVIGATE, url=self.start_url)
            decision = self.policy.check_action(nav, current_url=self.start_url)
            if not decision.allowed:
                return await self._fail("policy_denied", expected="allowlisted entry url", observed=decision.reason)
            await self.surface.goto(self.start_url)
            for step in self.capability.implementation.steps:
                result = await self._run_step(step)
                if result is not None:
                    return result
            extracted = await self._extract_outputs()
            self.outputs.update(extracted)
            ok = await self.surface.checkpoint(self.capability.implementation.success)
            if not ok:
                return await self._fail(
                    "success_checkpoint_failed",
                    expected=self.capability.implementation.success.text,
                    observed=(await self.surface.visible_text())[:400],
                    step_id=self.capability.implementation.steps[-1].id if self.capability.implementation.steps else None,
                )
            await self._screenshot("success.png")
            self.evidence.event("replay_success", outputs=self.outputs)
            return RunResult(
                status=Status.SUCCESS,
                run_id=self.run_id,
                capability_id=self.capability.id,
                mode="replay",
                outputs=self.outputs,
                evidence_dir=str(self.evidence.directory),
            )
        finally:
            await self._shutdown()

    async def _run_step(self, step: Step) -> RunResult | None:
        assert self.handoff is not None
        await self.handoff.assert_automation_owns()
        started = monotonic_ms()
        outcome = await self._detect_outcome()
        if outcome:
            return outcome
        recovered = await self._handle_recoverables()
        if recovered is not None:
            return recovered

        current_url = await self.surface.current_url()
        decision = self.policy.check_step(step, self.capability, current_url=current_url)
        if not decision.allowed and decision.risk is RiskClass.RISKY:
            return await self._handle_risky_step(step, decision.reason)
        if not decision.allowed:
            return await self._fail("policy_denied", expected="allowed action", observed=decision.reason, step_id=step.id)

        action = _step_to_action(step, self.params)
        self.evidence.event(
            "step_start",
            step_id=step.id,
            action=step.action.value,
            value=action.value,
        )
        try:
            exec_result = await self.surface.execute(action)
        except (TargetNotFound, AmbiguousTarget) as exc:
            await self._screenshot(f"fail_{step.id}.png")
            return await self._fail(
                "target_unresolved",
                expected=step.target.primary.model_dump_json() if step.target else "target",
                observed=str(exc),
                step_id=step.id,
            )
        except Exception as exc:
            await self._screenshot(f"fail_{step.id}.png")
            return await self._fail("action_error", expected=step.action.value, observed=str(exc), step_id=step.id)

        if action.extract_as:
            text = await self.surface.visible_text()
            self.outputs[action.extract_as] = text[:500]

        outcome = await self._detect_outcome(step_id=step.id)
        if outcome:
            return outcome
        recovered = await self._handle_recoverables(step_id=step.id)
        if recovered is not None:
            return recovered

        if step.checkpoint:
            ok = await self.surface.checkpoint(step.checkpoint)
            if not ok:
                outcome = await self._detect_outcome(step_id=step.id)
                if outcome:
                    return outcome
                await self._screenshot(f"fail_{step.id}.png")
                return await self._fail(
                    "checkpoint_mismatch",
                    expected=step.checkpoint.text or step.checkpoint.pattern,
                    observed=(await self.surface.visible_text())[:400],
                    step_id=step.id,
                )
        self.evidence.event(
            "step_ok",
            step_id=step.id,
            duration_ms=monotonic_ms() - started,
            strategy=exec_result.get("strategy"),
            url=exec_result.get("url"),
        )
        return None

    async def _detect_outcome(self, step_id: str | None = None) -> RunResult | None:
        for detector in self.capability.implementation.known_outcomes:
            if await self.surface.matches(detector.when):
                self.evidence.event("business_outcome", code=detector.code, step_id=step_id)
                await self._screenshot(f"outcome_{detector.code}.png")
                return RunResult(
                    status=Status.BUSINESS_OUTCOME,
                    run_id=self.run_id,
                    capability_id=self.capability.id,
                    mode="replay",
                    outcome_code=detector.code,
                    message=detector.message or detector.code,
                    step_id=step_id,
                    evidence_dir=str(self.evidence.directory),
                )
        return None

    async def _handle_recoverables(self, step_id: str | None = None) -> RunResult | None:
        for spec in self.capability.implementation.recoverables:
            if not await self.surface.matches(spec.when):
                continue
            self.evidence.event("recoverable", code=spec.code, on_match=spec.on_match, step_id=step_id)
            if spec.on_match == "escalate":
                return await self._escalate(
                    spec.code,
                    step_id=step_id,
                    expected=spec.when.text,
                    observed=spec.code,
                    wait=False,
                )
            if spec.on_match == "wait":
                import asyncio

                deadline = monotonic_ms() + spec.when.timeout_ms
                while await self.surface.matches(spec.when):
                    if monotonic_ms() > deadline:
                        return await self._fail(
                            "recoverable_timeout",
                            expected=spec.code,
                            observed="still present",
                            step_id=step_id,
                        )
                    await asyncio.sleep(0.2)
                continue
            if spec.on_match == "dismiss" and spec.resolve is not None:
                try:
                    await self.surface.execute(spec.resolve)
                except Exception as exc:
                    return await self._fail("recoverable_failed", expected=spec.code, observed=str(exc), step_id=step_id)
                if await self.surface.matches(spec.when):
                    return await self._fail(
                        "recoverable_failed",
                        expected=f"{spec.code} dismissed",
                        observed="still visible",
                        step_id=step_id,
                    )
        return None

    async def _extract_outputs(self) -> dict[str, Any]:
        extracted: dict[str, Any] = {}
        for extractor in self.capability.implementation.extractors:
            if extractor.strategy == "visible_regex" and extractor.pattern:
                value = await self.surface.extract_regex(extractor.pattern)
            elif extractor.strategy == "label_value" and extractor.label:
                value = await self.surface.extract_regex(rf"{extractor.label}\s*[:|]?\s*(.+)")
            else:
                value = None
            if value:
                extracted[extractor.output] = value.strip()
        return extracted

    async def _handle_risky_step(self, step: Step, reason: str) -> RunResult | None:
        """Pause for a human on the same session; skip the action if they already did it."""
        should_wait = self.auto_operator is not None or self.wait_for_operator
        result = await self._escalate(reason, step=step, wait=should_wait)
        if result is not None:
            return result
        if step.checkpoint and await self.surface.matches(step.checkpoint):
            self.evidence.event("step_completed_by_human", step_id=step.id)
            return None
        if await self.surface.matches(self.capability.implementation.success):
            self.evidence.event("step_completed_by_human", step_id=step.id)
            return None
        return await self._fail(
            "human_resume_incomplete",
            expected=step.checkpoint.text if step.checkpoint else "post-risk state",
            observed=(await self.surface.visible_text())[:400],
            step_id=step.id,
        )

    async def _escalate(
        self,
        reason: str,
        *,
        step: Step | None = None,
        step_id: str | None = None,
        expected: str | None = None,
        observed: str | None = None,
        wait: bool | None = None,
    ) -> RunResult | None:
        assert self.handoff is not None
        sid = step_id or (step.id if step else None)
        should_wait = self.auto_operator is not None or self.wait_for_operator if wait is None else wait
        expected_text = expected
        if expected_text is None and step and step.description:
            expected_text = _render_known(step.description, self.params)
        intervention = await self.handoff.escalate(
            reason,
            step_id=sid,
            expected=expected_text,
            observed=observed,
            wait=should_wait,
        )
        if should_wait:
            if self.handoff.owner is not ControlOwner.AUTOMATION:
                return await self._fail(
                    "control_not_returned",
                    expected="AUTOMATION",
                    observed=self.handoff.owner.value,
                    step_id=sid,
                )
            return None
        return RunResult(
            status=Status.HUMAN_REQUIRED,
            run_id=self.run_id,
            capability_id=self.capability.id,
            mode="replay",
            message=reason,
            step_id=sid,
            intervention_id=intervention.intervention_id,
            expected=expected,
            observed=observed,
            evidence_dir=str(self.evidence.directory),
        )

    async def _fail(
        self,
        code: str,
        *,
        expected: str | None,
        observed: str | None,
        step_id: str | None = None,
    ) -> RunResult:
        self.evidence.event(
            "hard_failure",
            code=code,
            step_id=step_id,
            expected=expected,
            observed=observed,
        )
        return RunResult(
            status=Status.HARD_FAILURE,
            run_id=self.run_id,
            capability_id=self.capability.id,
            mode="replay",
            outcome_code=code,
            message=code,
            step_id=step_id,
            expected=expected,
            observed=observed,
            evidence_dir=str(self.evidence.directory),
        )

    async def _screenshot(self, name: str) -> None:
        try:
            await self.surface.screenshot(str(self.evidence.path(name)))
        except Exception:
            pass

    async def _shutdown(self) -> None:
        if self.handoff:
            await self.handoff.close()
        await self.surface.close()


def _render_known(text: str, params: dict[str, Any]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in params:
            return str(params[key])
        return match.group(0)

    return re.sub(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}", repl, text)


def _step_to_action(step: Step, params: dict[str, Any]) -> ActionSpec:
    value = render_template(step.value, params) if step.value is not None else None
    url = render_template(step.url, params) if step.url is not None else None
    return ActionSpec(
        type=step.action,
        target=_render_target(step.target, params),
        value=value,
        url=url,
        key=step.key,
        extract_as=step.extract_as,
    )


def _render_target(target: Target | None, params: dict[str, Any]) -> Target | None:
    if target is None:
        return None
    clone = target.model_copy(deep=True)
    for loc in [clone.primary, *clone.fallbacks]:
        if loc.name:
            loc.name = render_template(loc.name, params)
        if loc.text:
            loc.text = render_template(loc.text, params)
        if loc.selector:
            loc.selector = render_template(loc.selector, params)
    return clone
