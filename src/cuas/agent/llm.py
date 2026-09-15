from __future__ import annotations

import json
import os
from typing import Any, Protocol

from cuas.models.action import ActionSpec, ActionType, Locator, LocatorStrategy, Target
from cuas.util import monotonic_ms

DEFAULT_OPENAI_MODEL = "gpt-4o"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class DecisionClient(Protocol):
    live: bool

    def decide(self, system: str, user: str) -> tuple[dict[str, Any], dict[str, Any]]: ...


class OpenAIClient:
    """Discovery-only client. Replay never instantiates this.

    Auth is OPENAI_API_KEY (never persisted). Each call records the OpenAI
    completion id, token usage, and latency so a reviewer can tell a live run
    from a test fixture.
    """

    live = True

    def __init__(self, model: str | None = None, base_url: str | None = None) -> None:
        from openai import OpenAI

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is not set. Discovery requires a live OpenAI key. "
                "Copy .env.example to .env and set OPENAI_API_KEY."
            )
        self.model = model or os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)
        self.client = OpenAI(api_key=api_key, base_url=self.base_url)

    def decide(self, system: str, user: str) -> tuple[dict[str, Any], dict[str, Any]]:
        started = monotonic_ms()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        # Some models (e.g. gpt-5.x) reject temperature=0 and only allow the default.
        temp = os.environ.get("OPENAI_TEMPERATURE")
        if temp is not None and temp != "":
            kwargs["temperature"] = float(temp)
        response = self.client.chat.completions.create(**kwargs)
        latency_ms = monotonic_ms() - started
        content = (response.choices[0].message.content or "{}").strip()
        if content.startswith("```"):
            content = content.strip("`")
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()
        usage = response.usage
        provenance = {
            "live": True,
            "provider": "openai",
            "requested_model": self.model,
            "model": response.model,
            "openai_id": response.id,
            "created": response.created,
            "system_fingerprint": getattr(response, "system_fingerprint", None),
            "base_url": self.base_url,
            "latency_ms": latency_ms,
            "usage": {
                "prompt_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                "completion_tokens": getattr(usage, "completion_tokens", None) if usage else None,
                "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
            },
        }
        return json.loads(content), provenance


class ScriptedClient:
    """Deterministic stand-in for tests. Not a substitute for a live discovery run."""

    live = False

    def __init__(self, decisions: list[dict[str, Any]]) -> None:
        self.decisions = list(decisions)
        self.i = 0

    def decide(self, system: str, user: str) -> tuple[dict[str, Any], dict[str, Any]]:
        if self.i >= len(self.decisions):
            payload = {"type": "finish", "goal_complete": False, "reason": "script exhausted"}
        else:
            payload = self.decisions[self.i]
            self.i += 1
        provenance = {
            "live": False,
            "provider": "scripted",
            "model": "fixture",
            "openai_id": None,
            "latency_ms": 0,
            "usage": None,
            "note": "Not a live LLM call. Reviewers should not count this as the required discovery run.",
        }
        return payload, provenance


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
