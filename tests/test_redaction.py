from cuas.safety.redaction import mask_value, redact_event, redact_text


def test_member_id_is_masked() -> None:
    assert mask_value("member_id", "12345").endswith("45")
    assert "12345" not in mask_value("member_id", "12345")


def test_free_text_masks_member_shaped_tokens() -> None:
    assert "***45" in redact_text("looked up 12345")
    assert "12345" not in redact_text("looked up 12345")


def test_nested_event_redaction() -> None:
    event = redact_event({"params": {"member_id": "12345", "nickname": "Vacation"}, "password": "demo1234"})
    assert event["params"]["member_id"].endswith("45")
    assert "demo1234" not in str(event["password"])
    assert event["params"]["nickname"] == "Vacation"
