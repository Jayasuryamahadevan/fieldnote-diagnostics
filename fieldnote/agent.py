"""Iterative read-only investigation loop for the diagnostic model.

The model receives the initial snapshot plus the history of commands it asked
Fieldnote to run. It can request one diagnostic command at a time, then answer.
This keeps execution in the harness instead of handing a shell to the model.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from . import analysis
from .commands import run_read_only

AGENT_PROMPT_PATH = Path(__file__).with_name("agent_prompt.txt")
try:
    AGENT_PROMPT = AGENT_PROMPT_PATH.read_text(encoding="utf-8").strip()
except OSError:
    AGENT_PROMPT = (
        "You are a read-only diagnostic agent. Return one JSON object with either "
        '{"action":"run","command":"..."} or {"action":"answer","answer":"..."}.'
    )

DEFAULT_MAX_COMMANDS = 4
MAX_COMMAND_BUDGET = 8


def max_commands() -> int:
    raw = os.getenv("DIAG_MAX_COMMANDS", str(DEFAULT_MAX_COMMANDS)).strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_COMMANDS
    return max(0, min(value, MAX_COMMAND_BUDGET))


def parse_action(raw: str) -> dict[str, str]:
    """Normalise a model response into a run or answer action."""
    text = (raw or "").strip()
    if not text:
        raise ValueError("Model returned an empty response.")
    try:
        data = analysis._parse_json_object(text)
    except ValueError:
        return {"action": "answer", "answer": text}

    if not isinstance(data, dict):
        raise ValueError("Model response was not a JSON object.")
    action = str(data.get("action", "")).strip().lower()
    if action == "answer" or ("answer" in data and not action):
        answer = str(data.get("answer", "")).strip()
        if not answer:
            raise ValueError("Model returned an empty answer.")
        return {"action": "answer", "answer": answer}
    if action == "run" or ("command" in data and not action):
        command = str(data.get("command", "")).strip()
        if not command:
            raise ValueError("Model requested an empty command.")
        return {
            "action": "run",
            "command": command,
            "reason": str(data.get("reason", "")).strip(),
        }
    raise ValueError(f"Unknown agent action {action!r}.")


async def investigate(
    model: str,
    complaint: str,
    evidence: dict[str, Any],
    timeout: float = 180,
    max_steps: int | None = None,
) -> dict[str, Any]:
    """Run the model in a bounded read-only command loop, then answer.

    Windows currently uses the collected snapshot only because the command
    validators and execution path are POSIX-oriented.
    """
    budget = max_commands() if max_steps is None else max(0, min(int(max_steps), MAX_COMMAND_BUDGET))
    commands: list[dict[str, Any]] = []

    if str(evidence.get("os", "")).lower() == "windows" or budget == 0:
        analysis_text = await analysis.analyse(model, complaint, evidence, timeout=timeout)
        return {"analysis": analysis_text, "commands": commands}

    for _ in range(budget + 1):
        payload = {
            "complaint": complaint,
            "evidence": evidence,
            "commands": commands,
            "commands_remaining": max(0, budget - len(commands)),
        }
        raw = await analysis.request_model(
            model,
            AGENT_PROMPT_PATH,
            AGENT_PROMPT,
            payload,
            timeout=timeout,
            json_mode=True,
            max_output=2400,
        )
        try:
            action = parse_action(raw)
        except ValueError as error:
            commands.append(
                {
                    "command": "(invalid agent response)",
                    "allowed": False,
                    "exit_code": None,
                    "output": "",
                    "reason": str(error),
                }
            )
            if len(commands) >= budget:
                break
            continue

        if action["action"] == "answer":
            return {"analysis": action["answer"], "commands": commands}

        if len(commands) >= budget:
            break

        result = await asyncio.to_thread(run_read_only, action["command"])
        result["purpose"] = action.get("reason", "")
        commands.append(result)

    final_evidence = dict(evidence)
    final_evidence["agent_commands"] = commands
    analysis_text = await analysis.analyse(model, complaint, final_evidence, timeout=timeout)
    return {"analysis": analysis_text, "commands": commands}
