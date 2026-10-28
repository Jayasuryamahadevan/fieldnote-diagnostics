"""Loopback diagnostic API. The web interface never executes corrective actions."""

from __future__ import annotations

import asyncio
import platform
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import __version__, claude_code
from .agent import investigate
from .analysis import analyse, analyser_model, backend_available, backend_name
from .collector import collect_system, dns_check
from .ollama_client import available, host, list_models

app = FastAPI(
    title="Fieldnote Diagnostics",
    version=__version__,
    docs_url=None,
    redoc_url=None,
)
PAGE = Path(__file__).with_name("index.html")
LIMIT = asyncio.Semaphore(1)


class DiagnosisRequest(BaseModel):
    complaint: str = Field(min_length=3, max_length=4000)
    dns_host: str | None = Field(default=None, max_length=253)
    model: str | None = Field(default=None, max_length=200)
    allow_commands: bool = True


@app.get("/")
def page() -> FileResponse:
    return FileResponse(PAGE)


@app.get("/healthz")
def healthz() -> dict[str, object]:
    return {"ok": True, "version": __version__}


@app.get("/api/status")
def status() -> dict[str, object]:
    system = platform.system()
    return {
        "os": {"Darwin": "macOS"}.get(system, system),
        "ollama_available": available(),
        "backend": backend_name(),
        "backend_available": backend_available(),
        "claude_available": claude_code.available(),
        "ollama_host": host(),
        "container": Path("/.dockerenv").exists(),
        "model": analyser_model(),
        "version": __version__,
    }


@app.get("/api/models")
def models() -> dict[str, list[str]]:
    return {"models": list_models()}


@app.get("/api/evidence")
def evidence() -> dict[str, object]:
    return collect_system()


def _public_error(error: Exception) -> str:
    text = str(error)
    text = text.replace("Claude Code", "the model service")
    text = text.replace("CLAUDE_BIN", "the model service")
    default = analyser_model()
    if default:
        text = text.replace(default, "the default model")
    return text


@app.post("/api/diagnose")
async def diagnose(body: DiagnosisRequest) -> dict[str, object]:
    backend = backend_name()
    if not await asyncio.to_thread(backend_available):
        if backend == "claude":
            raise HTTPException(
                503,
                "The configured model service and Ollama must both be available. "
                "Run 'fieldnote doctor' or check the model backend.",
            )
        raise HTTPException(
            503,
            'Ollama is not reachable. Start it and run "ollama signin".',
        )
    if body.dns_host and not re.fullmatch(r"[A-Za-z0-9.-]+", body.dns_host):
        raise HTTPException(422, "Enter a valid test hostname.")

    model = (body.model or analyser_model()).strip()
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,200}", model):
        raise HTTPException(422, "Enter a valid Ollama model name.")

    if LIMIT.locked():
        raise HTTPException(429, "A diagnosis is already running.")

    async with LIMIT:
        observed = await asyncio.to_thread(collect_system)
        observed["dns"] = await asyncio.to_thread(dns_check, body.dns_host) if body.dns_host else "not tested"
        commands: list[dict[str, object]] = []
        try:
            if body.allow_commands:
                outcome = await investigate(model, body.complaint, observed)
                analysis = outcome["analysis"]
                commands = outcome["commands"]
            else:
                analysis = await analyse(model, body.complaint, observed)
        except Exception as error:
            raise HTTPException(503, f"Model request failed: {_public_error(error)}") from error
        return {
            "analysis": analysis,
            "commands": commands,
            "evidence": observed,
            "model": model,
            "backend": backend,
            "version": __version__,
            "repair": "No repair is run from the web interface.",
        }
