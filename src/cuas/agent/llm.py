from __future__ import annotations

import json
import os
from typing import Any, Protocol

from cuas.models.action import ActionSpec, ActionType, Locator, LocatorStrategy, Target


class DecisionClient(Protocol):
    def decide(self, system: str, user: str) -> dict[str, Any]: ...


class XAIGrokClient:
    """OpenAI-compatible client pointed at api.x.ai. Discovery only."""

    def __init__(self, model: str | None = None) -> None:
        from openai import OpenAI

        api_key = os.environ.get("XAI_API_KEY")
        if not api_key:
            raise RuntimeError("XAI_API_KEY is not set. Discovery requires a live xAI key.")
        self.model = model or os.environ.get("XAI_MODEL", "grok-4.6")
        self.client = OpenAI(api_key=api_key, base_url="https://api.x.ai/v1")

    def decide(self, system: str, user: str) -> dict[str, Any]:
        response = self.client.chat.completions.create(
            model=self.model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)


class ScriptedClient:
    """Deterministic stand-in for tests. Not a substitute for a live discovery run."""

    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions = list(decisions)
        self.i = 0

    def decide(self, system: str, user: str) -> dict[str, Any]:
        if self.i >= len(self.decisions):
            return {"type": "finish", "goal_complete": False, "reason": "script exhausted"}
        item = self.decisions[self.i]
        self.i += 1
        return item


def parse_decision(raw: dict[str, Any], controls: list) -> ActionSpec:
    action_type = ActionType(raw.get("type", "wait"))
    target = None
    if raw.get("index") is not None and 0 <= int(raw["index"]) < len(controls):
        control = controls[int(raw["index"])]
        target = Target(
            primary=Locator(
                strategy=LocatorStrategy.ROLE_NAME if control.name else LocatorStrategy.PLACEHOLDER,
                role=control.role,
                name=control.name or None,
                text=control.placeholder if not control.name else control.name,
                frame=list(control.frame),
            )
        )
        if not control.name and control.placeholder:
            target.primary.strategy = LocatorStrategy.PLACEHOLDER
            target.primary.text = control.placeholder
    elif raw.get("target"):
        t = raw["target"]
        strategy = LocatorStrategy.ROLE_NAME
        if not t.get("name") and t.get("placeholder"):
            strategy = LocatorStrategy.PLACEHOLDER
        target = Target(
            primary=Locator(
                strategy=strategy,
                role=t.get("role"),
                name=t.get("name"),
                text=t.get("text") or t.get("placeholder") or t.get("name"),
                frame=list(t.get("frame") or []),
            )
        )
    return ActionSpec(
        type=action_type,
        target=target,
        value=raw.get("value"),
        url=raw.get("url"),
        key=raw.get("key"),
        reason=raw.get("reason"),
        outputs=raw.get("outputs"),
        goal_complete=bool(raw.get("goal_complete")),
        extract_as=raw.get("extract_as"),
    )
