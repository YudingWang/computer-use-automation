from pathlib import Path

from cuas.observability.evidence import EvidenceWriter
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


def test_write_json_redacts_trace_payload(tmp_path: Path) -> None:
    writer = EvidenceWriter(tmp_path)
    writer.write_json(
        "trace.json",
        [{"event": "observation", "visible_text": "No record matches member id 12345."}],
    )
    text = (tmp_path / "trace.json").read_text()
    assert "12345" not in text
    assert "***45" in text


def test_events_jsonl_starts_clean_each_run(tmp_path: Path) -> None:
    first = EvidenceWriter(tmp_path)
    first.event("replay_start", run_id="run_a")
    second = EvidenceWriter(tmp_path)
    second.event("replay_start", run_id="run_b")
    lines = [line for line in (tmp_path / "events.jsonl").read_text().splitlines() if line.strip()]
    assert len(lines) == 1
    assert "run_b" in lines[0]
    assert "run_a" not in (tmp_path / "events.jsonl").read_text()
