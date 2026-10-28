# Architecture

## Goals

- Read-only diagnosis that works on Windows, Linux and macOS.
- Any Ollama model, local or cloud, selected by the user.
- No shell for the model. The model may request diagnostic checks, but Python blocks destructive or state-changing commands before execution.
- A single pip-installable package with no repository-specific setup.

## Components

| Module | Responsibility |
| --- | --- |
| `fieldnote.collector` | Bounded evidence collection with psutil plus one Windows PowerShell call for event metadata and routes. |
| `fieldnote.ollama_client` | Standard-library HTTP client for `/api/chat`, `/api/tags`; model selection and readable errors. |
| `fieldnote.claude_code` | Runs the Claude Code CLI with no tools/MCP/sessions and routes it to Ollama's Anthropic-compatible endpoint. |
| `fieldnote.analysis` | Backend selection, analysis prompt, rectifier prompt, JSON validation and model selection. |
| `fieldnote.commands` | Shell-free diagnostic execution with a destructive-command denylist, state-change validators and private-path checks. |
| `fieldnote.agent` | Bounded investigate loop: model requests a command, harness runs it, output is fed back, then the model answers. |
| `fieldnote.actions` | Fixed corrective operations; currently only Windows DNS cache flush. |
| `fieldnote.cli` | `analyze`, `inspect`, `serve`, `start`, `doctor` commands. |
| `fieldnote.app` | FastAPI loopback API and browser UI; analysis only. |

## Pipeline

1. Collect a bounded, read-only snapshot in `collect_system`.
2. Add the optional DNS resolution result for a user-supplied hostname.
3. If the command loop is enabled, ask the analyser model for either one diagnostic command or a final answer. Validate and run permitted commands, append their output, and repeat up to `DIAG_MAX_COMMANDS` (default 4). On Windows the loop is skipped and the collected snapshot is analysed directly because the validators and execution path are POSIX-oriented. By default analysis goes through Claude Code when `claude` is installed, targeting Ollama; otherwise it uses the direct Ollama `/api/chat` client.
4. Display the analysis and every command run. The web UI and `--json` mode stop here.
5. Windows interactive CLI only: if the DNS check failed, ask the rectifier for exactly `flush_dns_cache` or `none`.
6. Reject unknown actions. Show the fixed action and its impact. Require `YES` on a terminal.
7. Run the fixed command, recheck the hostname, and report that success does not prove root cause.

## Evidence boundaries

Collected data is deliberately small and non-content:

- Portable metrics: CPU, load, memory, disks, uptime, battery, process count.
- Network: interface names/state/IPv4 and default routes.
- Linux: DRM connector state from `/sys/class/drm`, `xrandr --query` when available, and PCI display devices.
- Windows: recent critical/error System event metadata only (time, provider, ID, level) and video-controller metadata.
- Command-loop output comes from ordinary diagnostic tools and paths. Destructive commands, state-changing options, raw memory devices and private credential paths are blocked.
- No process names, event messages, documents, browser data or general file contents.

The complaint and evidence are sent to the configured model. For a cloud model this leaves the machine; the README states this.

## Claude Code boundary

Claude Code is used strictly as a local model client:

- launched with `--tools ""`, `--strict-mcp-config`, `--setting-sources ""` and `--no-session-persistence`;
- given a fixed system prompt file from the package;
- routed to `OLLAMA_HOST` through `ANTHROPIC_BASE_URL`, with `ANTHROPIC_API_KEY` removed;
- given only the complaint and evidence/history on stdin;
- never used for the rectifier or for executing actions. The command loop runs in Python, not through Claude Code's tools.

If Claude Code is missing or `DIAG_BACKEND=ollama`, analysis falls back to the direct Ollama API.

## Command and action boundaries

The model can suggest diagnostic commands, but it cannot run a shell. `fieldnote.commands` parses each request with `shlex`, rejects shell operators and executable paths, blocks destructive tools, validates state-changing subcommands, and screens file arguments for credentials and private data. Pipelines are limited to four stages and output is capped.

Corrective actions remain separate. `flush_dns_cache` is a fixed `ipconfig /flushdns` invocation with:

- Windows-only enforcement;
- a user-supplied hostname that failed before the action;
- model output constrained to an allowed action and validated as JSON;
- an interactive `YES` confirmation;
- a post-action DNS check;
- honest reporting when the result is unverified.

Adding another action requires a fixed implementation, documented preconditions, a verification step, and review of the disruption and permissions involved.

## Packaging and delivery

- `pyproject.toml` is the single source of truth; `pip install .` and `pip install "git+https://...git"` both work.
- `index.html`, `system_prompt.txt` and `agent_prompt.txt` are declared package data.
- Console scripts: `fieldnote` and `fieldnote-diagnostics`.
- Root `diagnose.py`, `antigravity_diagnose.py`, `app.py` and `ollama_client.py` are thin compatibility launchers for older instructions.
- CI tests on Windows, Linux and macOS, lints with Ruff, and builds a wheel/sdist.
- Claude Code is an optional runtime dependency, not a Python package dependency; the direct Ollama client keeps the tool usable without it.
- Docker installs the same package from `pyproject.toml` and runs `fieldnote.app:app`.

## Security posture

- The web server binds to loopback by default and allows one active diagnosis.
- No secrets are stored in the repository; `OLLAMA_API_KEY` is read from the environment.
- The container runs as a non-root user with a read-only root filesystem and `no-new-privileges`.
- Analysis output is untrusted text and is never executed.
- Agent commands are untrusted input. They are executed without a shell, only after denylist/path/state-change validation, with a timeout and output cap; command output is treated as untrusted data by the next model turn.
