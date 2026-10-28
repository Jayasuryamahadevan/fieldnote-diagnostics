# Architecture

## Goals

- Read-only diagnosis that works on Windows, Linux and macOS.
- Any Ollama model, local or cloud, selected by the user.
- No model-authored commands. A tiny fixed action catalog is enforced by Python.
- A single pip-installable package with no repository-specific setup.

## Components

| Module | Responsibility |
| --- | --- |
| `fieldnote.collector` | Bounded evidence collection with psutil plus one Windows PowerShell call for event metadata and routes. |
| `fieldnote.ollama_client` | Standard-library HTTP client for `/api/chat`, `/api/tags`; model selection and readable errors. |
| `fieldnote.analysis` | Analysis prompt, rectifier prompt, JSON validation and model selection. |
| `fieldnote.actions` | Fixed corrective operations; currently only Windows DNS cache flush. |
| `fieldnote.cli` | `analyze`, `inspect`, `serve`, `doctor` commands. |
| `fieldnote.app` | FastAPI loopback API and browser UI; analysis only. |

## Pipeline

1. Collect a bounded, read-only snapshot in `collect_system`.
2. Add the optional DNS resolution result for a user-supplied hostname.
3. Send the complaint and evidence to the analyser model.
4. Display the analysis. The web UI and `--json` mode stop here.
5. Windows interactive CLI only: if the DNS check failed, ask the rectifier for exactly `flush_dns_cache` or `none`.
6. Reject unknown actions. Show the fixed action and its impact. Require `YES` on a terminal.
7. Run the fixed command, recheck the hostname, and report that success does not prove root cause.

## Evidence boundaries

Collected data is deliberately small and non-content:

- Portable metrics: CPU, load, memory, disks, uptime, battery, process count.
- Network: interface names/state/IPv4 and default routes.
- Windows: recent critical/error System event metadata only (time, provider, ID, level).
- No process names, event messages, file contents, documents or browser data.

The complaint and evidence are sent to the configured model. For a cloud model this leaves the machine; the README states this.

## Action boundaries

The model cannot supply commands. `flush_dns_cache` is a fixed `ipconfig /flushdns` invocation with:

- Windows-only enforcement;
- a user-supplied hostname that failed before the action;
- model output constrained to an allowed action and validated as JSON;
- an interactive `YES` confirmation;
- a post-action DNS check;
- honest reporting when the result is unverified.

Adding another action requires a fixed implementation, documented preconditions, a verification step, and review of the disruption and permissions involved.

## Packaging and delivery

- `pyproject.toml` is the single source of truth; `pip install .` and `pip install "git+https://...git"` both work.
- `index.html` and `system_prompt.txt` are declared package data.
- Console scripts: `fieldnote` and `fieldnote-diagnostics`.
- Root `diagnose.py`, `antigravity_diagnose.py`, `app.py` and `ollama_client.py` are thin compatibility launchers for older instructions.
- CI tests on Windows, Linux and macOS, lints with Ruff, and builds a wheel/sdist.
- Docker installs the same package from `pyproject.toml` and runs `fieldnote.app:app`.

## Security posture

- The web server binds to loopback by default and allows one active diagnosis.
- No secrets are stored in the repository; `OLLAMA_API_KEY` is read from the environment.
- The container runs as a non-root user with a read-only root filesystem and `no-new-privileges`.
- Analysis output is untrusted text and is never executed.
