"""Compile a discovery trace into a reviewable capability artifact.

The raw model transcript is evidence. The artifact is a separate, parameterized
contract: steps, locator chains, typed I/O, checkpoints, and declared outcomes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from cuas.models.action import (
    ActionSpec,
    ActionType,
    Checkpoint,
    CheckpointKind,
    Locator,
    LocatorStrategy,
    OutcomeDetector,
    RecoverableSpec,
    RiskClass,
    Target,
)
from cuas.models.capability import (
    AppBinding,
    Capability,
    CapabilityInterface,
    CapabilityPolicy,
    Extractor,
    Implementation,
    InputParam,
    OutputField,
    Step,
)
from cuas.models.observation import Control
from cuas.util import values_match

PROFILES_DIR = Path(__file__).resolve().parent.parent / "profiles"

RISKY_NAMES = {"Confirm Open Account", "Submit Transfer", "Delete"}


def load_profile(app_family: str) -> dict[str, Any]:
    path = PROFILES_DIR / f"{app_family}.yaml"
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def compile_trace(
    events: list[dict[str, Any]],
    *,
    capability_id: str,
    description: str,
    params: dict[str, Any],
    input_meta: dict[str, InputParam] | None = None,
    app_family: str = "legacy_credit_union_console",
    entry_url: str,
    param_sensitive: set[str] | None = None,
) -> Capability:
    profile = load_profile(app_family)
    steps: list[Step] = []
    seen_outputs: dict[str, Any] = {}
    sensitive = param_sensitive or {"member_id"}

    for event in events:
        if event.get("event") != "action_result":
            continue
        action_data = event.get("action") or {}
        action = ActionSpec.model_validate(action_data)
        if action.type in {ActionType.FINISH, ActionType.WAIT, ActionType.READ}:
            if action.outputs:
                seen_outputs.update(action.outputs)
            continue
        control = event.get("control")
        target = action.target or (target_from_control(Control.model_validate(control)) if control else None)
        if target is None and action.type is not ActionType.NAVIGATE:
            continue
        value = action.value
        for key, raw in params.items():
            if values_match(value, raw):
                value = "{{" + key + "}}"
                break
        name = ""
        if target:
            name = target.primary.name or target.primary.text or ""
        risk = RiskClass.RISKY if name in RISKY_NAMES else _default_risk(action.type)
        checkpoint = _checkpoint_from_event(event)
        step_id = _step_id(action, len(steps) + 1)
        steps.append(
            Step(
                id=step_id,
                action=action.type,
                description=action.reason,
                target=target,
                value=value,
                url=action.url,
                key=action.key,
                extract_as=action.extract_as,
                checkpoint=checkpoint,
                risk=risk,
            )
        )

    inputs = input_meta or {
        key: InputParam(
            type=_input_type(key, val),
            required=True,
            sensitive=key in sensitive or key.lower().endswith("_id"),
        )
        for key, val in params.items()
    }
    output_names = [item["output"] for item in profile.get("extractors", [])]
    if not output_names:
        output_names = list(seen_outputs)
    outputs = {name: OutputField(type="string") for name in output_names}
    extractors = [
        Extractor(
            output=item["output"],
            strategy=item.get("strategy", "visible_regex"),
            pattern=item.get("pattern"),
            label=item.get("label"),
        )
        for item in profile.get("extractors", [])
    ]
    known_outcomes = [
        OutcomeDetector(
            code=item["code"],
            message=item.get("message"),
            when=Checkpoint.model_validate(item["when"]),
        )
        for item in profile.get("known_outcomes", [])
    ]
    recoverables = [RecoverableSpec.model_validate(item) for item in profile.get("recoverables", [])]
    success = Checkpoint(kind=CheckpointKind.VISIBLE_TEXT, text="Account successfully created")
    for event in reversed(events):
        if event.get("event") == "observation" and "Account successfully created" in (event.get("visible_text") or ""):
            success = Checkpoint(kind=CheckpointKind.VISIBLE_TEXT, text="Account successfully created")
            break

    return Capability(
        id=capability_id,
        version="1.0.0",
        interface=CapabilityInterface(
            name=capability_id.replace("_", " ").title(),
            description=description,
            inputs=inputs,
            outputs=outputs or {"confirmation_id": OutputField(type="string")},
            outcomes=list(dict.fromkeys(o.code for o in known_outcomes)),
        ),
        binding=AppBinding(
            app_family=app_family,
            surface="web",
            entry_url=entry_url,
            compatible_versions=["1.0"],
            tenants=[],
        ),
        implementation=Implementation(
            steps=steps,
            success=success,
            extractors=extractors,
            known_outcomes=known_outcomes,
            recoverables=recoverables,
        ),
        policy=CapabilityPolicy(
            risky_step_ids=[s.id for s in steps if s.risk is RiskClass.RISKY],
        ),
    )


def target_from_control(control: Control) -> Target:
    fallbacks: list[Locator] = []
    if control.name:
        primary = Locator(
            strategy=LocatorStrategy.ROLE_NAME,
            role=control.role,
            name=control.name,
            frame=list(control.frame),
        )
        fallbacks.append(Locator(strategy=LocatorStrategy.TEXT, text=control.name, frame=list(control.frame)))
    elif control.placeholder:
        primary = Locator(
            strategy=LocatorStrategy.PLACEHOLDER,
            text=control.placeholder,
            frame=list(control.frame),
        )
    else:
        primary = Locator(
            strategy=LocatorStrategy.ROLE_NAME,
            role=control.role,
            name=control.name,
            frame=list(control.frame),
            nth=0,
        )
    if control.placeholder and (not control.name or control.placeholder != control.name):
        fallbacks.append(
            Locator(
                strategy=LocatorStrategy.PLACEHOLDER,
                text=control.placeholder,
                frame=list(control.frame),
            )
        )
    return Target(primary=primary, fallbacks=fallbacks)


def _checkpoint_from_event(event: dict[str, Any]) -> Checkpoint | None:
    title = event.get("title_after") or ""
    visible = event.get("visible_after") or ""
    for needle in (
        "Account successfully created",
        "Review sub-account",
        "Open New Sub-account",
        "Member detail",
        "Member Search",
        "Member not found",
        "Permission denied",
        "System Notice",
    ):
        if needle.lower() in (title + " " + visible).lower():
            return Checkpoint(kind=CheckpointKind.VISIBLE_TEXT, text=needle, timeout_ms=8000)
    if title:
        return Checkpoint(kind=CheckpointKind.TITLE, text=title, timeout_ms=8000)
    return None


def _step_id(action: ActionSpec, n: int) -> str:
    name = ""
    if action.target:
        name = action.target.primary.name or action.target.primary.text or ""
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_")
    slug = slug or action.type.value
    return f"{n:02d}_{action.type.value}_{slug}"[:60]


def _default_risk(action_type: ActionType) -> RiskClass:
    if action_type in {ActionType.READ, ActionType.WAIT, ActionType.EXTRACT, ActionType.FINISH}:
        return RiskClass.SAFE
    if action_type in {ActionType.TYPE, ActionType.SELECT, ActionType.CLICK, ActionType.PRESS, ActionType.NAVIGATE}:
        return RiskClass.REVERSIBLE
    return RiskClass.REVERSIBLE


def _input_type(key: str, value: Any) -> str:
    """IDs stay strings even when they are all digits. Amounts are numbers."""
    key_l = key.lower()
    if key_l.endswith("_id") or key_l in {"id", "ssn"}:
        return "string"
    if key_l.endswith(("_deposit", "_amount", "_balance")) or key_l == "initial_deposit":
        return "number"
    if _looks_number(value):
        return "number"
    return "string"


def _looks_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
