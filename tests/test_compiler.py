from cuas.capability.compiler import compile_trace
from cuas.models.action import ActionType


def test_compiler_parameterizes_typed_values() -> None:
    events = [
        {
            "event": "action_result",
            "action": {
                "type": "type",
                "value": "12345",
                "target": {
                    "primary": {"strategy": "role_name", "role": "textbox", "name": "Member ID", "frame": ["work"]}
                },
                "reason": "enter id",
            },
            "title_after": "Member Search",
            "visible_after": "Member Search",
        },
        {
            "event": "action_result",
            "action": {
                "type": "click",
                "target": {
                    "primary": {"strategy": "role_name", "role": "button", "name": "Search", "frame": ["work"]}
                },
            },
            "title_after": "Member 12345",
            "visible_after": "Member detail",
        },
    ]
    cap = compile_trace(
        events,
        capability_id="lookup_member",
        description="Look up a member",
        params={"member_id": "12345"},
        entry_url="http://127.0.0.1:8765/",
    )
    assert cap.implementation.steps[0].value == "{{member_id}}"
    assert cap.implementation.steps[0].action is ActionType.TYPE
    assert "MEMBER_NOT_FOUND" in cap.interface.outcomes
    assert "{{member_id}}" in cap.model_dump_json()
    assert "12345" not in cap.implementation.steps[0].value
