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
