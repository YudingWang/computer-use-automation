"""Canonical open_subaccount capability.

Hand-authored against the local console so replay and tests do not depend on an
LLM. Live discovery compiles an equivalent artifact from a real trace.
"""

from __future__ import annotations

from cuas.capability.compiler import load_profile
from cuas.models.action import (
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
    TenantOverride,
)


def _loc(
    strategy: LocatorStrategy,
    *,
    role: str | None = None,
    name: str | None = None,
    text: str | None = None,
    selector: str | None = None,
    frame: list[str] | None = None,
) -> Locator:
    return Locator(strategy=strategy, role=role, name=name, text=text, selector=selector, frame=frame or [])


def _role(role: str, name: str, frame: list[str] | None = None, extra: Locator | None = None) -> Target:
    primary = _loc(LocatorStrategy.ROLE_NAME, role=role, name=name, frame=frame)
    fallbacks = [_loc(LocatorStrategy.TEXT, text=name, frame=frame)]
    if extra:
        fallbacks.append(extra)
    return Target(primary=primary, fallbacks=fallbacks)


def open_subaccount_capability(entry_url: str) -> Capability:
    profile = load_profile("legacy_credit_union_console")
    known_outcomes = [OutcomeDetector.model_validate(item) for item in profile.get("known_outcomes", [])]
    recoverables = [RecoverableSpec.model_validate(item) for item in profile.get("recoverables", [])]
    extractors = [
        Extractor(
            output=item["output"],
            strategy=item.get("strategy", "visible_regex"),
            pattern=item.get("pattern"),
            label=item.get("label"),
        )
        for item in profile.get("extractors", [])
    ]
    steps = [
        Step(
            id="enter_member_id",
            action=ActionType.TYPE,
            description="Type the member id into the search workspace iframe.",
            target=_role(
                "textbox",
                "Member ID",
                ["work"],
                extra=_loc(LocatorStrategy.LABEL, name="Member ID", frame=["work"]),
            ),
            value="{{member_id}}",
            risk=RiskClass.SAFE,
            checkpoint=Checkpoint(kind=CheckpointKind.VISIBLE_TEXT, text="Member Search"),
        ),
        Step(
            id="search_member",
            action=ActionType.CLICK,
            description="Submit member search.",
            target=_role("button", "Search", ["work"]),
            risk=RiskClass.SAFE,
            checkpoint=Checkpoint(kind=CheckpointKind.VISIBLE_TEXT, text="Member detail"),
        ),
        Step(
            id="open_subaccount_form",
            action=ActionType.CLICK,
            description="Start sub-account origination.",
            target=_role("button", "Open New Sub-account"),
            risk=RiskClass.REVERSIBLE,
            checkpoint=Checkpoint(kind=CheckpointKind.VISIBLE_TEXT, text="Open New Sub-account"),
        ),
        Step(
            id="select_account_type",
            action=ActionType.SELECT,
            description="Choose the share type.",
            target=_role("combobox", "Account type", extra=_loc(LocatorStrategy.LABEL, name="Account type")),
            value="{{account_type}}",
            risk=RiskClass.REVERSIBLE,
        ),
        Step(
            id="enter_nickname",
            action=ActionType.TYPE,
            description="Nickname has no <label for>, so placeholder is primary.",
            target=Target(
                primary=_loc(LocatorStrategy.PLACEHOLDER, text="Nickname"),
                fallbacks=[_loc(LocatorStrategy.CSS, selector="input[name='nickname']")],
            ),
            value="{{nickname}}",
            risk=RiskClass.REVERSIBLE,
        ),
        Step(
            id="enter_deposit",
            action=ActionType.TYPE,
            description="Initial deposit field is labelled only by adjacent table text.",
            target=Target(
                primary=_loc(LocatorStrategy.PLACEHOLDER, text="0.00"),
                fallbacks=[_loc(LocatorStrategy.CSS, selector="input[name='initial_deposit']")],
            ),
            value="{{initial_deposit}}",
            risk=RiskClass.REVERSIBLE,
        ),
        Step(
            id="review",
            action=ActionType.CLICK,
            description="Move to the review screen.",
            target=_role("button", "Review"),
            risk=RiskClass.REVERSIBLE,
            checkpoint=Checkpoint(kind=CheckpointKind.VISIBLE_TEXT, text="Review sub-account"),
        ),
        Step(
            id="confirm_create",
            action=ActionType.CLICK,
            description="Irreversible origination. Gated by policy unless approved.",
            target=_role("button", "Confirm Open Account"),
            risk=RiskClass.RISKY,
            checkpoint=Checkpoint(kind=CheckpointKind.VISIBLE_TEXT, text="Account successfully created"),
        ),
    ]
    return Capability(
        id="open_subaccount",
        version="1.0.0",
        interface=CapabilityInterface(
            name="Open Sub-account",
            description="Look up a member and open a new sub-account through the confirmation screen.",
            inputs={
                "member_id": InputParam(type="string", required=True, sensitive=True, description="Member identifier"),
                "account_type": InputParam(type="string", required=True, enum=["Savings", "Money Market"]),
                "nickname": InputParam(type="string", required=True),
                "initial_deposit": InputParam(type="number", required=True, minimum=0),
            },
            outputs={
                "confirmation_id": OutputField(type="string"),
                "new_account_id": OutputField(type="string"),
            },
            outcomes=["MEMBER_NOT_FOUND", "MEMBER_RESTRICTED", "VALIDATION_ERROR"],
        ),
        binding=AppBinding(
            app_family="legacy_credit_union_console",
            surface="web",
            entry_url=entry_url,
            compatible_versions=["1.0"],
            tenants=[
                TenantOverride(
                    tenant_id="eastside",
                    label="Eastside Community CU — same vendor product, different chrome",
                    text_overrides={
                        "Member ID": "Member Number",
                        "Search": "Find Member",
                        "Open New Sub-account": "Open Sub Account",
                    },
                )
            ],
        ),
        implementation=Implementation(
            steps=steps,
            success=Checkpoint(kind=CheckpointKind.VISIBLE_TEXT, text="Account successfully created"),
            extractors=extractors,
            known_outcomes=known_outcomes,
            recoverables=recoverables,
        ),
        policy=CapabilityPolicy(risky_step_ids=["confirm_create"]),
    )


def approve_confirm_operator():
    """Scripted operator: take the live session, click confirm, hand it back."""

    async def _run(handoff) -> None:
        import asyncio

        from cuas.models.action import ActionSpec, ActionType

        while handoff.intervention is None:
            await asyncio.sleep(0.05)
        await handoff.take_control()
        await handoff.human_act(
            ActionSpec(
                type=ActionType.CLICK,
                target=_role("button", "Confirm Open Account"),
            )
        )
        await handoff.resume()

    return _run
