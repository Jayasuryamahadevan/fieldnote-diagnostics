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
    async def fake_analyse(model, complaint, evidence, timeout=180):
        assert model == "test:model"
        assert complaint == "Slow PC"
        assert timeout == 30
        return "The evidence is limited."

    monkeypatch.setattr(cli, "collect_system", lambda: {"os": "Linux", "cpu_count": 8})
    monkeypatch.setattr(cli, "analyse", fake_analyse)

    code = cli.main(
        ["analyze", "Slow PC", "--json", "--model", "test:model", "--timeout", "30"]
    )
    assert code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["model"] == "test:model"
    assert result["analysis"] == "The evidence is limited."
    assert result["action"] is None
    assert result["action_supported"] is False


def test_empty_complaint_is_rejected(capsys):
    assert cli.main(["analyze", ""]) == 1
    assert "complaint must contain" in capsys.readouterr().err


def test_bad_dns_host_is_rejected(capsys):
    assert cli.main(["analyze", "Slow PC", "--dns-host", "bad host!"]) == 1
    assert "dns-host must be a hostname" in capsys.readouterr().err


def test_short_timeout_is_rejected(capsys):
    assert cli.main(["analyze", "Slow PC", "--timeout", "1"]) == 1
    assert "timeout must be at least" in capsys.readouterr().err


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
        },
    )()
    assert asyncio.run(cli._analyze(args)) == 0
