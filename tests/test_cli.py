import asyncio
import json

import pytest

from fieldnote import cli


def test_version(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["--version"])
    assert error.value.code == 0
    assert "fieldnote" in capsys.readouterr().out


def test_inspect(monkeypatch, capsys):
    monkeypatch.setattr(cli, "collect_system", lambda: {"os": "Linux", "cpu_count": 4})
    assert cli.main(["inspect"]) == 0
    assert json.loads(capsys.readouterr().out) == {"os": "Linux", "cpu_count": 4}


def test_analyze_json(monkeypatch, capsys):
    async def fake_investigate(model, complaint, evidence, timeout=180):
        assert model == "test:model"
        assert complaint == "Slow PC"
        assert timeout == 30
        return {
            "analysis": "The evidence is limited.",
            "commands": [
                {"command": "uname -s", "allowed": True, "exit_code": 0, "output": "Linux"}
            ],
        }

    monkeypatch.setattr(cli, "collect_system", lambda: {"os": "Linux", "cpu_count": 8})
    monkeypatch.setattr(cli, "investigate", fake_investigate)

    code = cli.main(
        ["analyze", "Slow PC", "--json", "--model", "test:model", "--timeout", "30"]
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["model"] == "test:model"
    assert result["analysis"] == "The evidence is limited."
    assert result["backend"] in {"claude", "ollama"}
    assert result["commands"][0]["command"] == "uname -s"
    assert result["action"] is None
    assert result["action_supported"] is False


def test_analyze_can_disable_commands(monkeypatch, capsys):
    async def fake_analyse(model, complaint, evidence, timeout=180):
        return "No commands."

    monkeypatch.setattr(cli, "collect_system", lambda: {"os": "Linux"})
    monkeypatch.setattr(cli, "analyse", fake_analyse)

    code = cli.main(["analyze", "Slow PC", "--json", "--no-commands"])
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["analysis"] == "No commands."
    assert result["commands"] == []


def test_empty_complaint_is_rejected(capsys):
    assert cli.main(["analyze", ""]) == 1
    assert "complaint must contain" in capsys.readouterr().err


def test_bad_dns_host_is_rejected(capsys):
    assert cli.main(["analyze", "Slow PC", "--dns-host", "bad host!"]) == 1
    assert "dns-host must be a hostname" in capsys.readouterr().err


def test_short_timeout_is_rejected(capsys):
    assert cli.main(["analyze", "Slow PC", "--timeout", "1"]) == 1
    assert "timeout must be at least" in capsys.readouterr().err


def test_start_uses_existing_ollama_and_schedules_browser(monkeypatch, capsys):
    events = []
    monkeypatch.setattr(cli, "server_status", lambda timeout=2: (True, "ok"))
    monkeypatch.setattr(cli, "_serve", lambda args: events.append(args) or 0)
    monkeypatch.setattr(cli, "_schedule_browser", lambda url: events.append(url))

    assert cli.main(["start", "--port", "8123"]) == 0
    assert events[0] == "http://127.0.0.1:8123"
    assert events[1].port == 8123
    assert "Fieldnote: http://127.0.0.1:8123" in capsys.readouterr().out


def test_start_can_skip_browser(monkeypatch):
    events = []
    monkeypatch.setattr(cli, "server_status", lambda timeout=2: (True, "ok"))
    monkeypatch.setattr(cli, "_serve", lambda args: 0)
    monkeypatch.setattr(cli, "_schedule_browser", events.append)

    assert cli.main(["start", "--no-browser"]) == 0
    assert events == []


def test_ensure_ollama_starts_local_server(monkeypatch, tmp_path):
    statuses = iter([False, False, True])
    calls = []

    class FakeProcess:
        pid = 123

        def poll(self):
            return None

    monkeypatch.setattr(cli, "server_status", lambda timeout=2: (next(statuses, True), "ok"))
    monkeypatch.setattr(cli, "host", lambda: "http://127.0.0.1:11434")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(cli.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(
        cli.subprocess,
        "Popen",
        lambda command, **kwargs: calls.append((command, kwargs)) or FakeProcess(),
    )

    assert cli._ensure_ollama() is True
    assert calls[0][0] == ["/usr/bin/ollama", "serve"]


def test_doctor_offline(monkeypatch, capsys):
    monkeypatch.setattr(cli, "server_status", lambda: (False, "connection refused"))
    assert cli.main(["doctor"]) == 1
    output = capsys.readouterr()
    assert "Reachable: no" in output.out
    assert "connection refused" in output.err


def test_doctor_online(monkeypatch, capsys):
    monkeypatch.setattr(cli, "server_status", lambda: (True, "ok"))
    monkeypatch.setattr(cli, "list_models", lambda: ["qwen2.5:3b"])
    assert cli.main(["doctor", "--model", "gpt-oss:120b-cloud"]) == 0
    output = capsys.readouterr().out
    assert "qwen2.5:3b" in output
    assert "gpt-oss:120b-cloud" in output


def test_analyze_async_runner(monkeypatch):
    async def fake_analyse(*args, **kwargs):
        return "ok"

    monkeypatch.setattr(cli, "collect_system", lambda: {"os": "Linux"})
    monkeypatch.setattr(cli, "analyse", fake_analyse)
    args = type(
        "Args",
        (),
        {
            "complaint": "Slow",
            "timeout": 30,
            "dns_host": None,
            "model": "m",
            "json": False,
            "no_commands": True,
        },
    )()
    assert asyncio.run(cli._analyze(args)) == 0


def test_doctor_forced_claude_missing(monkeypatch, capsys):
    monkeypatch.setenv("DIAG_BACKEND", "claude")
    monkeypatch.setattr(cli, "server_status", lambda: (True, "ok"))
    monkeypatch.setattr(cli.claude_code, "available", lambda: False)
    assert cli.main(["doctor"]) == 1
    assert "not found" in capsys.readouterr().out
