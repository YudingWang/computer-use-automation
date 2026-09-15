from pathlib import Path

import pytest

from fixtures import approve_confirm_operator, open_subaccount_capability
from cuas.models.result import Status
from cuas.replay.executor import ReplayExecutor


def _params(**overrides: str) -> dict[str, str]:
    base = {
        "member_id": "12345",
        "account_type": "Savings",
        "nickname": "Vacation",
        "initial_deposit": "500",
    }
    base.update(overrides)
    return base


async def _run(tmp_path: Path, demo_url: str, params: dict[str, str], **kwargs) -> ReplayExecutor:
    cap = open_subaccount_capability(demo_url)
    executor = ReplayExecutor(cap, params, evidence_dir=tmp_path, start_url=demo_url, **kwargs)
    result = await executor.run()
    executor.evidence.write_json("result.json", result.model_dump(mode="json"))
    return executor


@pytest.mark.asyncio
async def test_happy_path_extracts_confirmation(tmp_path: Path, demo_url: str) -> None:
    executor = await _run(tmp_path, demo_url, _params(), allow_risky=True)
    result = _last_result(tmp_path)
    assert result["status"] == Status.SUCCESS.value
    assert str(result["outputs"].get("confirmation_id", "")).startswith("CNF-")
    assert result["outputs"].get("new_account_id")


@pytest.mark.asyncio
async def test_member_not_found_is_business_outcome(tmp_path: Path, demo_url: str) -> None:
    await _run(tmp_path, demo_url, _params(member_id="99999"), allow_risky=True)
    result = _last_result(tmp_path)
    assert result["status"] == Status.BUSINESS_OUTCOME.value
    assert result["outcome_code"] == "MEMBER_NOT_FOUND"


@pytest.mark.asyncio
async def test_restricted_member_is_business_outcome(tmp_path: Path, demo_url: str) -> None:
    await _run(tmp_path, demo_url, _params(member_id="24680"), allow_risky=True)
    result = _last_result(tmp_path)
    assert result["status"] == Status.BUSINESS_OUTCOME.value
    assert result["outcome_code"] == "MEMBER_RESTRICTED"


@pytest.mark.asyncio
async def test_negative_deposit_is_validation_outcome(tmp_path: Path, demo_url: str) -> None:
    await _run(tmp_path, demo_url, _params(initial_deposit="-10"), allow_risky=True)
    result = _last_result(tmp_path)
    assert result["status"] == Status.BUSINESS_OUTCOME.value
    assert result["outcome_code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_interstitial_is_dismissed(tmp_path: Path, demo_url: str) -> None:
    url = demo_url.rstrip("/") + "/?simulate=interstitial"
    cap = open_subaccount_capability(demo_url)
    executor = ReplayExecutor(
        cap,
        _params(),
        evidence_dir=tmp_path,
        start_url=url,
        allow_risky=True,
    )
    result = await executor.run()
    assert result.status is Status.SUCCESS


@pytest.mark.asyncio
async def test_eastside_tenant_override(tmp_path: Path, demo_url: str) -> None:
    url = demo_url.rstrip("/") + "/?brand=eastside"
    cap = open_subaccount_capability(demo_url)
    executor = ReplayExecutor(
        cap,
        _params(member_id="67890", nickname="RainyDay", initial_deposit="250"),
        evidence_dir=tmp_path,
        start_url=url,
        tenant_id="eastside",
        allow_risky=True,
    )
    result = await executor.run()
    assert result.status is Status.SUCCESS
    assert result.outputs.get("confirmation_id")


@pytest.mark.asyncio
async def test_risky_step_without_approval_escalates(tmp_path: Path, demo_url: str) -> None:
    executor = await _run(tmp_path, demo_url, _params(), allow_risky=False)
    result = _last_result(tmp_path)
    assert result["status"] == Status.HUMAN_REQUIRED.value
    assert result["step_id"] == "confirm_create"
    assert (tmp_path / "intervention.json").exists()


@pytest.mark.asyncio
async def test_same_session_auto_operator_handoff(tmp_path: Path, demo_url: str) -> None:
    cap = open_subaccount_capability(demo_url)
    executor = ReplayExecutor(
        cap,
        _params(member_id="67890", nickname="Ops", initial_deposit="100"),
        evidence_dir=tmp_path,
        start_url=demo_url,
        allow_risky=False,
        auto_operator=approve_confirm_operator(),
    )
    result = await executor.run()
    assert result.status is Status.SUCCESS
    intervention = (tmp_path / "intervention.json").read_text()
    assert "RESUMED" in intervention
    assert '"human_took_control": true' in intervention
    events = (tmp_path / "events.jsonl").read_text()
    assert "take_control" in events
    assert "human_action" in events


def _last_result(tmp_path: Path) -> dict:
    import json

    return json.loads((tmp_path / "result.json").read_text())
