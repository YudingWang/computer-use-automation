from pathlib import Path

import pytest

from cuas.agent.discovery import DiscoveryAgent, default_open_subaccount_script
from cuas.agent.llm import ScriptedClient
from cuas.models.result import Status


@pytest.mark.asyncio
async def test_scripted_discovery_compiles_parameterized_artifact(tmp_path: Path, demo_url: str) -> None:
    params = {
        "member_id": "12345",
        "account_type": "Savings",
        "nickname": "Vacation",
        "initial_deposit": "500",
    }
    agent = DiscoveryAgent(ScriptedClient(default_open_subaccount_script(params)), evidence_dir=tmp_path)
    result, _events = await agent.run(
        "Open a savings sub-account named Vacation for member 12345 with initial deposit 500",
        demo_url,
    )
    assert result.status is Status.SUCCESS
    cap = agent.compile(
        capability_id="open_subaccount",
        description="Open a sub-account",
        params=params,
        entry_url=demo_url,
    )
    assert "{{member_id}}" in cap.model_dump_json()
    assert "12345" not in "".join(s.value or "" for s in cap.implementation.steps)
    assert cap.interface.inputs["member_id"].type == "string"
    assert cap.interface.inputs["initial_deposit"].type == "number"
    assert "account_type" in cap.interface.inputs
    assert "savings_balance" not in cap.interface.outputs
    assert cap.implementation.steps[0].target and cap.implementation.steps[0].target.fallbacks
    assert cap.implementation.steps
    assert any(s.risk.value == "risky" for s in cap.implementation.steps)

    from cuas.replay.executor import ReplayExecutor

    replay = ReplayExecutor(
        cap,
        {
            "member_id": "67890",
            "account_type": "Savings",
            "nickname": "Compiled",
            "initial_deposit": "75",
        },
        evidence_dir=tmp_path / "replay",
        start_url=demo_url,
        allow_risky=True,
    )
    replayed = await replay.run()
    assert replayed.status is Status.SUCCESS
    assert str(replayed.outputs.get("confirmation_id", "")).startswith("CNF-")
