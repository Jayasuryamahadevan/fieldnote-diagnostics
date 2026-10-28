"""Run the Claude Code CLI against Ollama's Anthropic-compatible endpoint.

Claude Code is used only as a local model client. It is launched with no
built-in tools, no MCP servers, no session files and an explicit system prompt.
The model request is routed to the local Ollama daemon, which serves cloud or
local models.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .ollama_client import host as ollama_host


def claude_path() -> str | None:
    return (
        os.getenv("CLAUDE_BIN")
        or shutil.which("claude")
        or shutil.which("claude.cmd")
    )


def available() -> bool:
    return claude_path() is not None


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["ANTHROPIC_BASE_URL"] = (
        os.getenv("DIAG_ANTHROPIC_BASE_URL") or ollama_host()
    )
    environment["ANTHROPIC_AUTH_TOKEN"] = (
        os.getenv("DIAG_ANTHROPIC_AUTH_TOKEN")
        or os.getenv("OLLAMA_API_KEY")
        or "ollama"
    )
    environment.pop("ANTHROPIC_API_KEY", None)
    environment.setdefault("CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "1")
    return environment


def build_command(
    executable: str,
    model: str,
    system_prompt_file: str | Path,
    *,
    windows: bool | None = None,
) -> list[str]:
    command = [
        executable,
        "--print",
        "--output-format",
        "text",
        "--tools",
        "",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--no-session-persistence",
        "--model",
        model,
        "--system-prompt-file",
        str(system_prompt_file),
    ]
    is_windows = os.name == "nt" if windows is None else windows
    if is_windows and executable.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", *command]
    return command


def chat(
    model: str,
    system_prompt_file: str | Path,
    payload: dict[str, Any],
    timeout: float = 180,
) -> str:
    executable = claude_path()
    if not executable:
        raise RuntimeError(
            "Claude Code was not found. Install it, set CLAUDE_BIN, or use "
            "DIAG_BACKEND=ollama to use the direct Ollama API."
        )

    command = build_command(executable, model, system_prompt_file)
    options: dict[str, Any] = {
        "input": json.dumps(payload, ensure_ascii=True),
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "check": False,
        "env": _environment(),
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        completed = subprocess.run(command, **options)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            f"Claude Code timed out after {timeout:g}s while using model '{model}'."
        ) from error
    except OSError as error:
        raise RuntimeError(f"Claude Code could not start: {error}") from error

    if completed.returncode != 0:
        detail = (completed.stderr or "").strip()[-500:]
        raise RuntimeError(
            f"Claude Code failed with exit code {completed.returncode}"
            + (f": {detail}" if detail else ".")
        )

    answer = (completed.stdout or "").strip()
    if not answer:
        raise RuntimeError(
            f"Claude Code returned an empty response from model '{model}'."
        )
    return answer


async def ask(
    model: str,
    system_prompt_file: str | Path,
    payload: dict[str, Any],
    timeout: float = 180,
) -> str:
    return await asyncio.to_thread(chat, model, system_prompt_file, payload, timeout)
