"""Minimal Ollama chat client using only the Python standard library.

The local Ollama daemon serves both local and cloud models. Sign in with
``ollama signin``, then select any model with ``--model``, ``DIAG_MODEL`` or
``OLLAMA_MODEL``. ``OLLAMA_HOST`` changes the daemon address and
``OLLAMA_API_KEY`` is sent when set (useful for a remote Ollama endpoint).
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any


def default_model() -> str:
    return (
        os.getenv("DIAG_MODEL")
        or os.getenv("OLLAMA_MODEL")
        or "nemotron-3-nano:30b-cloud"
    )


DEFAULT_MODEL = default_model()


def host() -> str:
    value = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").strip().rstrip("/")
    if "://" not in value:
        value = "http://" + value
    return value


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    key = os.getenv("OLLAMA_API_KEY")
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


class OllamaError(RuntimeError):
    """A readable Ollama request failure."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _request(
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    url = f"{host()}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers=_headers(),
        method="GET" if data is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:500]
        raise OllamaError(f"Ollama HTTP {error.code}: {detail}", error.code) from error
    except urllib.error.URLError as error:
        raise OllamaError(
            f"Could not reach Ollama at {host()}: {error.reason}. "
            "Start Ollama and run 'ollama signin'."
        ) from error
    except (TimeoutError, OSError) as error:
        raise OllamaError(
            f"Ollama request to {host()} timed out after {timeout:g}s."
        ) from error

    try:
        parsed = json.loads(raw)
    except ValueError as error:
        raise OllamaError("Ollama returned a response that was not valid JSON.") from error
    if not isinstance(parsed, dict):
        raise OllamaError("Ollama returned an unexpected response.")
    return parsed


def chat(
    model: str,
    system: str,
    payload: dict[str, Any],
    timeout: float = 180,
    *,
    json_mode: bool = False,
    max_output: int = 1200,
) -> str:
    """Send one non-streaming chat request and return the assistant text."""
    selected = (model or default_model()).strip()
    if not selected:
        raise OllamaError("No Ollama model was selected.")

    body: dict[str, Any] = {
        "model": selected,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=True)},
        ],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": max_output},
    }
    if json_mode:
        body["format"] = "json"

    try:
        data = _request("/api/chat", body, timeout)
    except OllamaError as error:
        if error.status == 404:
            raise OllamaError(
                f"Model '{selected}' is not available to this Ollama account. "
                f"Run 'ollama pull {selected}' or choose another with --model. "
                f"({error})",
                404,
            ) from error
        if error.status in (401, 403):
            raise OllamaError(
                f"Ollama rejected access to '{selected}'. Run 'ollama signin' "
                f"or set OLLAMA_API_KEY. ({error})",
                error.status,
            ) from error
        raise

    answer = (data.get("message") or {}).get("content")
    if not isinstance(answer, str) or not answer.strip():
        raise OllamaError(
            f"Ollama returned an empty response from model '{selected}'. "
            "Try again or select another model."
        )
    return answer.strip()


async def ask(
    model: str,
    instruction: str,
    payload: dict[str, Any],
    timeout: float = 180,
    *,
    json_mode: bool = False,
    max_output: int = 1200,
) -> str:
    """Async wrapper so the FastAPI app can await the blocking HTTP call."""
    return await asyncio.to_thread(
        chat,
        model,
        instruction,
        payload,
        timeout,
        json_mode=json_mode,
        max_output=max_output,
    )


def list_models(timeout: float = 3) -> list[str]:
    """Return locally known model names. Cloud models may not be listed."""
    try:
        data = _request("/api/tags", timeout=timeout)
    except OllamaError:
        return []
    models = data.get("models")
    if not isinstance(models, list):
        return []
    names = []
    for item in models:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            names.append(item["name"])
    return names


def server_status(timeout: float = 2) -> tuple[bool, str]:
    """Return whether the Ollama daemon answers, plus a readable message."""
    try:
        _request("/api/tags", timeout=timeout)
        return True, "Ollama is reachable."
    except OllamaError as error:
        return False, str(error)


def available(timeout: float = 2) -> bool:
    """True when the Ollama daemon answers; does not prove model access."""
    return server_status(timeout)[0]
