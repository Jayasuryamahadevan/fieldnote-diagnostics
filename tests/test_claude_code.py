import json
import subprocess

import pytest

from fieldnote import claude_code


def test_chat_builds_command_and_env(monkeypatch, tmp_path):
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("system", encoding="utf-8")
    captured = {}

    monkeypatch.delenv("CLAUDE_BIN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    monkeypatch.setattr(
        claude_code.shutil,
        "which",
        lambda name: "/usr/bin/claude" if name == "claude" else None,
    )

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, "analysis", "")

    monkeypatch.setattr(claude_code.subprocess, "run", fake_run)

    result = claude_code.chat("model:cloud", prompt, {"complaint": "slow"})

    assert result == "analysis"
    command = captured["command"]
    assert command[:2] == ["/usr/bin/claude", "--print"]
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--system-prompt-file") + 1] == str(prompt)
    assert command[command.index("--model") + 1] == "model:cloud"

    environment = captured["kwargs"]["env"]
    assert environment["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:11434"
    assert environment["ANTHROPIC_AUTH_TOKEN"] == "ollama"
    assert "ANTHROPIC_API_KEY" not in environment
    assert json.loads(captured["kwargs"]["input"]) == {"complaint": "slow"}


def test_build_command_wraps_windows_cmd():
    command = claude_code.build_command(r"C:\npm\claude.cmd", "m", "p.txt", windows=True)
    assert command[:3] == ["cmd.exe", "/c", r"C:\npm\claude.cmd"]


def test_missing_claude(monkeypatch):
    monkeypatch.delenv("CLAUDE_BIN", raising=False)
    monkeypatch.setattr(claude_code.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError, match="not found"):
        claude_code.chat("m", "p", {})


def test_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setattr(claude_code, "claude_path", lambda: "/usr/bin/claude")

    def fake_run(command, **kwargs):
        return subprocess.CompletedProcess(command, 2, "", "bad auth")

    monkeypatch.setattr(claude_code.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="bad auth"):
        claude_code.chat("m", tmp_path / "p", {})
