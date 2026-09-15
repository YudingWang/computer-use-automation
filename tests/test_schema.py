from fixtures import open_subaccount_capability


def test_capability_schema_is_typed_and_parameterized() -> None:
    cap = open_subaccount_capability("http://127.0.0.1:8765/")
    dumped = cap.model_dump()
    assert dumped["schema_version"] == "1.0"
    assert cap.interface.inputs["member_id"].type == "string"
    assert cap.interface.inputs["member_id"].sensitive
    assert cap.interface.inputs["initial_deposit"].type == "number"
    values = [step.value for step in cap.implementation.steps if step.value]
    assert "{{member_id}}" in values
    assert "12345" not in str(dumped)
    assert cap.implementation.known_outcomes
    assert "confirm_create" in cap.policy.risky_step_ids


def test_tenant_override_rewrites_search_chrome() -> None:
    cap = open_subaccount_capability("http://127.0.0.1:8765/").apply_tenant("eastside")
    search = next(s for s in cap.implementation.steps if s.id == "search_member")
    assert search.target is not None
    assert search.target.primary.name == "Find Member"
    member = next(s for s in cap.implementation.steps if s.id == "enter_member_id")
    assert member.target is not None
    assert member.target.primary.name == "Member Number"
