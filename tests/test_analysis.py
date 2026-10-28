import asyncio

import pytest

from fieldnote import analysis


def test_parse_json_object_plain():
    assert analysis._parse_json_object('{"action": "none"}') == {"action": "none"}


def test_parse_json_object_fenced_and_padded():
    raw = 'Here is the result:\n```json\n{"action": "flush_dns_cache", "reason": "stale"}\n```'
    parsed = analysis._parse_json_object(raw)
    assert parsed["action"] == "flush_dns_cache"


def test_parse_json_object_rejects_non_object():
    with pytest.raises(ValueError):
        analysis._parse_json_object("not json")


def test_propose_rectification_valid(monkeypatch):
    async def fake_ask(*args, **kwargs):
        assert kwargs["json_mode"] is True
        return '{"action": "flush_dns_cache", "reason": "DNS lookup failed"}'

    monkeypatch.setattr(analysis, "ask", fake_ask)
    result = asyncio.run(
        analysis.propose_rectification("m", "complaint", {"os": "Windows"}, "analysis")
    )
    assert result == {"action": "flush_dns_cache", "reason": "DNS lookup failed"}


def test_propose_rectification_rejects_unknown_action(monkeypatch):
    async def fake_ask(*args, **kwargs):
        return '{"action": "delete_everything", "reason": "no"}'

    monkeypatch.setattr(analysis, "ask", fake_ask)
    with pytest.raises(ValueError):
        asyncio.run(
            analysis.propose_rectification("m", "complaint", {"os": "Windows"}, "analysis")
        )


def test_system_prompt_mentions_uncertainty():
    assert "Uncertainty" in analysis.SYSTEM_PROMPT
    assert "untrusted data" in analysis.SYSTEM_PROMPT


def test_backend_prefers_claude_when_installed(monkeypatch):
    monkeypatch.delenv("DIAG_BACKEND", raising=False)
    monkeypatch.setattr(analysis.claude_code, "available", lambda: True)
    assert analysis.backend_name() == "claude"


def test_backend_falls_back_to_ollama(monkeypatch):
    monkeypatch.delenv("DIAG_BACKEND", raising=False)
    monkeypatch.setattr(analysis.claude_code, "available", lambda: False)
    assert analysis.backend_name() == "ollama"


def test_backend_can_be_forced(monkeypatch):
    monkeypatch.setenv("DIAG_BACKEND", "ollama")
    monkeypatch.setattr(analysis.claude_code, "available", lambda: True)
    assert analysis.backend_name() == "ollama"


def test_analyse_uses_claude_backend(monkeypatch):
    monkeypatch.setenv("DIAG_BACKEND", "claude")
    captured = {}

    async def fake_claude_ask(model, prompt_file, payload, timeout=180):
        captured["model"] = model
        captured["prompt_file"] = prompt_file
        captured["payload"] = payload
        return "claude result"

    monkeypatch.setattr(analysis.claude_code, "ask", fake_claude_ask)
    result = asyncio.run(analysis.analyse("m", "complaint", {"os": "Windows"}))
    assert result == "claude result"
    assert captured["prompt_file"] == analysis.SYSTEM_PROMPT_PATH
    assert captured["payload"]["complaint"] == "complaint"


def test_analyse_uses_ollama_fallback(monkeypatch):
    monkeypatch.setenv("DIAG_BACKEND", "ollama")

    async def fake_ask(*args, **kwargs):
        return "ollama result"

    monkeypatch.setattr(analysis, "ask", fake_ask)
    assert asyncio.run(analysis.analyse("m", "c", {"os": "Linux"})) == "ollama result"
