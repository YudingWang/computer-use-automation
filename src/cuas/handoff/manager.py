"""Same-session control transfer.

Invariant: only the current control owner may act. Automation checks the lease
before every step. A human takes the same Playwright page — not a new browser.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Coroutine

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

from cuas.models.action import ActionSpec
from cuas.models.intervention import ControlOwner, Intervention, InterventionState
from cuas.observability.evidence import EvidenceWriter
from cuas.surface.playwright_web import PlaywrightWebSurface
from cuas.util import free_port, new_id


class OperatorAct(BaseModel):
    type: str
    role: str | None = None
    name: str | None = None
    value: str | None = None
    frame: list[str] = []


class HandoffManager:
    def __init__(
        self,
        surface: PlaywrightWebSurface,
        evidence: EvidenceWriter,
        run_id: str,
        *,
        capability_id: str | None = None,
        auto_operator: Callable[["HandoffManager"], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        self.surface = surface
        self.evidence = evidence
        self.run_id = run_id
        self.capability_id = capability_id
        self.auto_operator = auto_operator
        self.owner = ControlOwner.AUTOMATION
        self.intervention: Intervention | None = None
        self.operator_url: str | None = None
        self._resume = asyncio.Event()
        self._server: uvicorn.Server | None = None
        self._serve_task: asyncio.Task[None] | None = None
        self._operator_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        port = free_port()
        app = self._build_app()
        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", lifespan="off")
        self._server = uvicorn.Server(config)
        self._serve_task = asyncio.create_task(self._server.serve())
        self.operator_url = f"http://127.0.0.1:{port}"
        for _ in range(50):
            if self._server.started:
                break
            await asyncio.sleep(0.05)
        self.evidence.write_json(
            "operator_endpoint.json",
            {"url": self.operator_url, "run_id": self.run_id},
        )
        try:
            await self.surface.install_human_listeners(self.operator_url)
        except Exception:
            pass

    async def assert_automation_owns(self) -> None:
        if self.owner is not ControlOwner.AUTOMATION:
            raise PermissionError("automation does not own the session")

    async def escalate(
        self,
        reason: str,
        *,
        step_id: str | None = None,
        expected: str | None = None,
        observed: str | None = None,
        wait: bool = True,
    ) -> Intervention:
        screenshot = self.evidence.path("escalation.png")
        try:
            await self.surface.screenshot(str(screenshot))
            shot_ref = str(screenshot)
        except Exception:
            shot_ref = None
        url = await self.surface.current_url()
        intervention = Intervention(
            intervention_id=new_id("int"),
            run_id=self.run_id,
            capability_id=self.capability_id,
            step_id=step_id,
            reason=reason,
            current_url=url,
            screenshot_ref=shot_ref,
            expected=expected,
            observed=observed,
            control_owner=ControlOwner.AUTOMATION,
            state=InterventionState.WAITING,
            operator_url=self.operator_url,
        )
        self.intervention = intervention
        self._resume = asyncio.Event()
        self.evidence.write_json("intervention.json", intervention.model_dump(mode="json"))
        self.evidence.event(
            "escalation",
            intervention_id=intervention.intervention_id,
            reason=reason,
            step_id=step_id,
        )
        if self.auto_operator and self._operator_task is None:
            self._operator_task = asyncio.create_task(self.auto_operator(self))
        if wait:
            if not self.auto_operator:
                endpoint = self.operator_url or ""
                print(
                    "\n=== HUMAN HANDOFF ===\n"
                    f"Paused at step {step_id}: {reason}\n"
                    "Leave the headed browser open. In another terminal:\n"
                    f"  python -m cuas operator take-control --endpoint {endpoint}\n"
                    "  Click Confirm Open Account in THAT browser window.\n"
                    f"  python -m cuas operator resume --endpoint {endpoint}\n",
                    flush=True,
                )
            await self._resume.wait()
        return intervention

    async def take_control(self) -> None:
        if self.intervention is None:
            raise RuntimeError("no pending intervention")
        self.owner = ControlOwner.HUMAN
        self.intervention.control_owner = ControlOwner.HUMAN
        self.intervention.state = InterventionState.HUMAN_OWNED
        self.intervention.human_took_control = True
        self.evidence.event("take_control", intervention_id=self.intervention.intervention_id)
        self.evidence.write_json("intervention.json", self.intervention.model_dump(mode="json"))

    async def human_act(self, action: ActionSpec) -> dict[str, Any]:
        if self.owner is not ControlOwner.HUMAN:
            raise PermissionError("human does not own the session")
        result = await self.surface.execute(action)
        event = {
            "actor": "human",
            "action": action.model_dump(mode="json"),
            "result": {k: v for k, v in result.items() if k != "text"},
        }
        if self.intervention:
            self.intervention.human_events.append(event)
            self.evidence.write_json("intervention.json", self.intervention.model_dump(mode="json"))
        self.evidence.event("human_action", **event)
        return result

    async def resume(self) -> None:
        if self.intervention is None:
            raise RuntimeError("no pending intervention")
        self.owner = ControlOwner.AUTOMATION
        self.intervention.control_owner = ControlOwner.AUTOMATION
        self.intervention.state = InterventionState.RESUMED
        self.evidence.event("resume", intervention_id=self.intervention.intervention_id)
        self.evidence.write_json("intervention.json", self.intervention.model_dump(mode="json"))
        self._resume.set()

    async def close(self) -> None:
        if self._server:
            self._server.should_exit = True
        if self._serve_task:
            self._serve_task.cancel()
        if self._operator_task:
            self._operator_task.cancel()

    def _build_app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/status")
        async def status() -> dict[str, Any]:
            if not self.intervention:
                return {"pending": False, "owner": self.owner.value}
            return {
                "pending": True,
                "owner": self.owner.value,
                "intervention": self.intervention.model_dump(mode="json"),
            }

        @app.post("/take-control")
        async def take_control() -> JSONResponse:
            await self.take_control()
            return JSONResponse({"ok": True, "owner": self.owner.value})

        @app.post("/act")
        async def act(body: OperatorAct) -> JSONResponse:
            from cuas.models.action import ActionType, Locator, LocatorStrategy, Target

            target = None
            if body.role or body.name:
                target = Target(
                    primary=Locator(
                        strategy=LocatorStrategy.ROLE_NAME,
                        role=body.role or "button",
                        name=body.name or "",
                        frame=body.frame,
                    )
                )
            action = ActionSpec(type=ActionType(body.type), target=target, value=body.value)
            result = await self.human_act(action)
            return JSONResponse({"ok": True, "result": {k: v for k, v in result.items() if k != "text"}})

        @app.post("/resume")
        async def resume() -> JSONResponse:
            await self.resume()
            return JSONResponse({"ok": True, "owner": self.owner.value})

        @app.post("/human-event")
        async def human_event(payload: dict[str, Any]) -> JSONResponse:
            if self.owner is ControlOwner.HUMAN and self.intervention:
                self.intervention.human_events.append({"actor": "human_browser", **payload})
                self.evidence.event("human_browser_event", **payload)
            return JSONResponse({"ok": True})

        return app
