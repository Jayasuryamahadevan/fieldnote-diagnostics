import asyncio

from fieldnote import agent


def test_parse_action_run():
    action = agent.parse_action('{"action":"run","command":"uname -s","reason":"OS"}')
    assert action == {"action": "run", "command": "uname -s", "reason": "OS"}


def test_parse_action_answer_with_markdown():
    action = agent.parse_action('{"action":"answer","answer":"Direct answer: yes.\\n\\nObserved\\n- x"}')
    assert action["action"] == "answer"
    assert action["answer"].startswith("Direct answer: yes.")
    assert "Observed" in action["answer"]


def test_parse_action_plain_text_becomes_answer():
    action = agent.parse_action("The HDMI connector is disconnected.")
    assert action == {"action": "answer", "answer": "The HDMI connector is disconnected."}


def test_investigate_runs_command_then_answers(monkeypatch):
    calls = []

    async def fake_request_model(model, prompt_file, prompt, payload, timeout=180, **kwargs):
        calls.append(payload)
        if len(calls) == 1:
            return '{"action":"run","command":"cat /sys/class/drm/card0-HDMI-A-1/status","reason":"Check HDMI"}'
        return '{"action":"answer","answer":"Direct answer: connected.\\n\\nObserved\\n- status is connected."}'

    def fake_run(command):
        return {
            "command": command,
            "allowed": True,
            "exit_code": 0,
            "output": "connected",
            "reason": None,
        }

    monkeypatch.setattr(agent.analysis, "request_model", fake_request_model)
    monkeypatch.setattr(agent, "run_read_only", fake_run)
    result = asyncio.run(agent.investigate("m", "Is HDMI connected?", {"os": "Linux"}, max_steps=3))

    assert result["analysis"].startswith("Direct answer: connected.")
    assert result["commands"][0]["output"] == "connected"
    assert result["commands"][0]["purpose"] == "Check HDMI"
    assert calls[1]["commands"][0]["command"] == "cat /sys/class/drm/card0-HDMI-A-1/status"


def test_investigate_reports_denied_command(monkeypatch):
    calls = []

    async def fake_request_model(model, prompt_file, prompt, payload, timeout=180, **kwargs):
        calls.append(payload)
        if len(calls) == 1:
            return '{"action":"run","command":"rm -rf /","reason":"bad"}'
        return '{"action":"answer","answer":"Cannot inspect that."}'

    def fake_run(command):
        return {
            "command": command,
            "allowed": False,
            "exit_code": None,
            "output": "",
            "reason": "not allowed",
        }

    monkeypatch.setattr(agent.analysis, "request_model", fake_request_model)
    monkeypatch.setattr(agent, "run_read_only", fake_run)
    result = asyncio.run(agent.investigate("m", "q", {"os": "Linux"}, max_steps=2))
    assert result["commands"][0]["allowed"] is False
    assert calls[1]["commands"][0]["allowed"] is False


def test_investigate_skips_posix_loop_on_windows(monkeypatch):
    async def fail_request_model(*args, **kwargs):
        raise AssertionError("Windows should not request POSIX commands")

    async def fake_analyse(*args, **kwargs):
        return "Snapshot answer."

    monkeypatch.setattr(agent.analysis, "request_model", fail_request_model)
    monkeypatch.setattr(agent.analysis, "analyse", fake_analyse)
    result = asyncio.run(agent.investigate("m", "q", {"os": "Windows"}, max_steps=2))

    assert result == {"analysis": "Snapshot answer.", "commands": []}


def test_investigate_falls_back_when_budget_exhausted(monkeypatch):
    async def always_run(*args, **kwargs):
        return '{"action":"run","command":"uname -s","reason":"again"}'

    async def fake_analyse(*args, **kwargs):
        return "Fallback answer."

    monkeypatch.setattr(agent.analysis, "request_model", always_run)
    monkeypatch.setattr(agent.analysis, "analyse", fake_analyse)
    monkeypatch.setattr(
        agent,
        "run_read_only",
        lambda command: {
            "command": command,
            "allowed": True,
            "exit_code": 0,
            "output": "Linux",
            "reason": None,
        },
    )
    result = asyncio.run(agent.investigate("m", "q", {"os": "Linux"}, max_steps=1))
    assert result["analysis"] == "Fallback answer."
    assert len(result["commands"]) == 1
