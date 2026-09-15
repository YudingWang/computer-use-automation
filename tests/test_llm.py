import os

import pytest

from cuas.agent.llm import OpenAIClient, ScriptedClient


def test_scripted_client_is_labeled_not_live() -> None:
    client = ScriptedClient([{"type": "finish", "goal_complete": True, "reason": "done"}])
    payload, provenance = client.decide("sys", "user")
    assert client.live is False
    assert payload["type"] == "finish"
    assert provenance["live"] is False
    assert provenance["provider"] == "scripted"
    assert provenance["openai_id"] is None


def test_openai_client_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIClient()


def test_openai_client_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    client = OpenAIClient()
    assert client.live is True
    assert client.model == "gpt-4o-mini"
    assert "openai.com" in client.base_url
