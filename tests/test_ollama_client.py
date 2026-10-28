import io
import json
import urllib.error
import urllib.request

import pytest

from fieldnote import ollama_client


class FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_chat_sends_expected_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse({"message": {"content": " OK "}})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    answer = ollama_client.chat("qwen2.5:3b", "system", {"ping": True}, timeout=12)

    assert answer == "OK"
    assert captured["body"]["model"] == "qwen2.5:3b"
    assert captured["body"]["stream"] is False
    assert captured["body"]["messages"][0]["role"] == "system"
    assert captured["body"]["options"]["num_predict"] == 1200
    assert "format" not in captured["body"]
    assert captured["timeout"] == 12


def test_chat_json_mode_sets_format(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        return FakeResponse({"message": {"content": '{"action": "none"}'}})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    answer = ollama_client.chat("m", "s", {}, json_mode=True, max_output=64)

    assert answer == '{"action": "none"}'
    assert captured["body"]["format"] == "json"
    assert captured["body"]["options"]["num_predict"] == 64


def test_missing_model_gets_actionable_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            404,
            "Not Found",
            {},
            io.BytesIO(b'{"error":"model not found"}'),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(ollama_client.OllamaError) as error:
        ollama_client.chat("missing:model", "s", {})
    message = str(error.value)
    assert "not available" in message
    assert "ollama pull missing:model" in message


def test_server_status_reports_unreachable(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:1")
    reachable, message = ollama_client.server_status(timeout=0.5)
    assert reachable is False
    assert "Could not reach Ollama" in message


def test_default_model_env(monkeypatch):
    monkeypatch.setenv("DIAG_MODEL", "custom:cloud")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    assert ollama_client.default_model() == "custom:cloud"


def test_list_models(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse({"models": [{"name": "a:1"}, {"name": "b:2"}, {"bad": 1}]})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert ollama_client.list_models() == ["a:1", "b:2"]
