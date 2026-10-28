# Fieldnote Diagnostics

Read-only laptop and desktop diagnostics with **any Ollama model**, including cloud models. Windows is the primary target; Linux and macOS are supported for analysis.

Analysis runs through **Claude Code** when the `claude` CLI is installed, using Ollama's Anthropic-compatible endpoint. If Claude Code is not installed, Fieldnote falls back to the direct Ollama API automatically.

Fieldnote collects a bounded snapshot of host evidence (CPU, memory, disks, network, display connectors, battery, and recent Windows System event metadata), sends it and your complaint to an Ollama model, and lets the model request a few diagnostic checks before it answers. The harness runs those checks and feeds the output back to the model. It never hands the model a shell and never runs repairs.

## Install from GitHub

Python 3.10+ and [Ollama](https://ollama.com/download) are required.

```powershell
py -m pip install "git+https://github.com/Jayasuryamahadevan/fieldnote-diagnostics.git"
```

On Linux or macOS:

```bash
python3 -m pip install "git+https://github.com/Jayasuryamahadevan/fieldnote-diagnostics.git"
```

Pin a release if you want reproducible installs:

```bash
pip install "git+https://github.com/Jayasuryamahadevan/fieldnote-diagnostics.git@v0.4.0"
```

To install from a local checkout instead:

```bash
pip install .
```

## Quick start

```bash
ollama signin
fieldnote doctor
fieldnote inspect
fieldnote analyze "The laptop fan is loud and the system feels slow."
```

`fieldnote doctor` reports which analysis backend is active. To use Claude Code, install it from https://code.claude.com/docs/en/setup and confirm `claude --version` works. Fieldnote launches it with no tools, no MCP servers, no saved sessions, and a fixed system prompt, and points it at your Ollama endpoint. The read-only command loop runs in Fieldnote itself, not through Claude Code's tools.

On Windows, use `py -m fieldnote ...` if the `fieldnote` launcher is not on `PATH`.

## One-command start

```bash
fieldnote start
```

This starts Ollama if it is installed but not already running, launches the web interface at `http://127.0.0.1:8000`, and opens it in your browser. Use `--no-browser` to skip opening the browser, or `--port` to choose another port. Ctrl+C stops the web interface; Ollama is left running.

The default model is `beam:cloud`, a low-usage cloud model. Choose **any** model your Ollama daemon can use:

```bash
fieldnote analyze "Wi-Fi says connected but websites do not load" --model gpt-oss:120b-cloud
fieldnote analyze "The PC reboots randomly" --model qwen2.5:3b
```

Cloud models run on Ollama's servers. Local models run on your machine. Pull or run the model first if it is not available:

```bash
ollama pull gpt-oss:120b-cloud
ollama run qwen2.5:3b
```

## Commands

| Command | Purpose |
| --- | --- |
| `fieldnote analyze "..."` | Collect evidence and ask the selected model. |
| `fieldnote inspect` | Print collected evidence without contacting a model. |
| `fieldnote start` | Start Ollama if needed, launch the web UI, and open the browser. |
| `fieldnote serve` | Start the local browser UI at `http://127.0.0.1:8000`. |
| `fieldnote doctor` | Check Ollama connectivity and the configured model. |
| `fieldnote --version` | Show the installed version. |

`analyze` options:

- `--model NAME` selects the model.
- `--dns-host example.com` tests a hostname before and after an approved Windows DNS cache flush.
- `--json` prints machine-readable results and never executes corrective actions.
- `--no-commands` disables the read-only command loop and uses the fixed snapshot only.
- `--timeout SECONDS` controls each model request timeout (default 180).

Environment variables:

| Variable | Meaning |
| --- | --- |
| `DIAG_MODEL` | Default model for all stages. |
| `DIAG_BACKEND` | `claude` or `ollama`. Default: Claude Code when installed, otherwise direct Ollama. |
| `CLAUDE_BIN` | Optional path to the Claude Code executable. |
| `DIAG_ANALYSER_MODEL` | Model used for analysis. |
| `DIAG_RECTIFIER_MODEL` | Model used for the optional DNS action decision. |
| `DIAG_MAX_COMMANDS` | Read-only checks per diagnosis (default 4, maximum 8; `0` disables the loop). |
| `OLLAMA_HOST` | Ollama address (default `http://127.0.0.1:11434`). |
| `OLLAMA_API_KEY` | Optional bearer token for a remote Ollama endpoint. |
| `DIAG_ANTHROPIC_BASE_URL` | Optional override for the endpoint given to Claude Code. Default: `OLLAMA_HOST`. |
| `DIAG_ANTHROPIC_AUTH_TOKEN` | Optional token given to Claude Code. Default: `OLLAMA_API_KEY` or `ollama`. |

## What is collected

- OS family, version and architecture.
- CPU count, current CPU percentage, load average and uptime.
- Memory total/available in GiB and used percentage.
- Disk mount points, filesystem, total/free GiB and used percentage.
- Network interface names, state and IPv4 addresses; default routes.
- Linux display state from `/sys/class/drm` (`connected`, `disconnected`, `enabled`, `dpms`), `xrandr --query` when available, and PCI display devices from `lspci`.
- Windows display adapters from `Win32_VideoController`.
- Battery percentage and whether the laptop is plugged in, when available.
- Windows only: up to 20 recent critical/error System event **metadata** records from the last day (timestamp, provider, event ID, level).

The initial snapshot does not read documents, browser data, process names, event messages or general file contents. The model can request commands whose output may include logs, configuration or files; that output is sent back to the model, so a cloud model receives it too. Do not include secrets in the complaint. Review the answer and its uncertainty; a model can be wrong.

## Read-only command loop

The model can ask for more evidence instead of guessing. Each turn it returns either a final answer or one command. Fieldnote runs diagnostic commands and returns their output to the model, up to four checks by default. This is how questions such as "Is HDMI connected?" are answered from the actual connector state instead of a fixed snapshot alone.

The loop only runs commands directly, without a shell. Most diagnostic tools and ordinary log/config paths are allowed. A denylist blocks destructive and state-changing operations: deleting, moving, editing, installing, service/network/display changes, privilege escalation and shell operators. Credential and private-data paths are also blocked. Model-requested commands and their output are shown in the web UI. The command loop uses POSIX tools on Linux; on Windows the analysis uses the collected snapshot and model-suggested checks without running PowerShell commands.

## Windows behaviour

- Run from PowerShell, Terminal or `cmd.exe`. No administrator rights are required for analysis.
- `fieldnote analyze` reads the System event log through PowerShell. If the log is unavailable, the rest of the analysis still runs.
- The only corrective action is a fixed `ipconfig /flushdns`. It is considered only when:
  - the host is Windows;
  - you supplied `--dns-host`;
  - that hostname fails to resolve;
  - the model proposes exactly `flush_dns_cache`;
  - you type `YES` at the confirmation prompt.
- The command is fixed in code and the hostname is checked again afterwards. A successful lookup does not prove the DNS cache caused the problem.
- The web UI and `--json` mode never execute corrective actions.

## Browser UI

```bash
fieldnote serve
```

Open `http://127.0.0.1:8000`. The interface has a settings sidebar, a chat thread, and an activity panel. The sidebar shows the Ollama provider and lets you switch models without displaying the server default model name. **Read-only checks** is enabled by default; turn it off to use the snapshot only. The activity panel shows every command, exit code and output, plus the evidence JSON. It never runs repairs. Do not bind it to a public interface; it has no authentication beyond a single-diagnosis lock.

### Docker demo

```bash
docker compose up --build
```

The container inspects **the container**, not your host PC. It reaches Ollama on the host through `host.docker.internal` and uses the direct Ollama API (`DIAG_BACKEND=ollama`) because Claude Code is not installed in the image. Override with `OLLAMA_HOST` and `DIAG_MODEL` if needed:

```bash
OLLAMA_HOST=http://192.168.1.10:11434 DIAG_MODEL=gpt-oss:120b-cloud docker compose up --build
```

## Development

```bash
git clone https://github.com/Jayasuryamahadevan/fieldnote-diagnostics.git
cd fieldnote-diagnostics
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m pytest
ruff check .
python -m build
```

CI runs the tests on Ubuntu, Windows and macOS with Python 3.10 and 3.12, lints with Ruff, and builds a wheel and sdist.

## Troubleshooting

- `fieldnote doctor` reports Ollama unreachable: start Ollama and run `ollama signin`.
- Claude Code is installed but not detected: set `CLAUDE_BIN` to its full path, or use `DIAG_BACKEND=ollama`.
- You want the direct Ollama API instead of Claude Code: set `DIAG_BACKEND=ollama`.
- Model not found: `ollama pull MODEL`, or choose another with `--model`.
- Remote Ollama: set `OLLAMA_HOST` and `OLLAMA_API_KEY`.
- Windows console encoding: Fieldnote reconfigures stdout to UTF-8; if your terminal still garbles characters, use Windows Terminal or set `PYTHONUTF8=1`.
- `fieldnote` not found after install: use `python -m fieldnote`.

## License

MIT. See [LICENSE](LICENSE).
