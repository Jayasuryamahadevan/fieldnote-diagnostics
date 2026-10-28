"""Loopback diagnostic API. The web interface never executes corrective actions."""

from __future__ import annotations

import asyncio
import platform
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import __version__
from .analysis import analyse, analyser_model
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


@app.post("/api/diagnose")
async def diagnose(body: DiagnosisRequest) -> dict[str, object]:
    if not await asyncio.to_thread(available):
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
        observed["dns"] = (
            await asyncio.to_thread(dns_check, body.dns_host)
            if body.dns_host
            else "not tested"
        )
        try:
            analysis = await analyse(model, body.complaint, observed)
        except Exception as error:
            raise HTTPException(503, f"Model request failed: {error}") from error
        return {
            "analysis": analysis,
            "evidence": observed,
            "model": model,
            "version": __version__,
            "repair": "No repair is run from the web interface.",
        }
