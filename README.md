# Fieldnote Diagnostics

Read-only laptop and desktop diagnostics with **any Ollama model**, including cloud models. Windows is the primary target; Linux and macOS are supported for analysis.

Fieldnote collects a small, bounded snapshot of host evidence (CPU, memory, disks, network, battery, and recent Windows System event metadata), sends it and your complaint to an Ollama model, and prints the model's analysis. It does not send file contents, process names, or event messages.

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
pip install "git+https://github.com/Jayasuryamahadevan/fieldnote-diagnostics.git@v0.3.0"
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

On Windows, use `py -m fieldnote ...` if the `fieldnote` launcher is not on `PATH`.

The default model is `nemotron-3-nano:30b-cloud`, a low-usage cloud model. Choose **any** model your Ollama daemon can use:

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
| `fieldnote serve` | Start the local browser UI at `http://127.0.0.1:8000`. |
| `fieldnote doctor` | Check Ollama connectivity and the configured model. |
| `fieldnote --version` | Show the installed version. |

`analyze` options:

- `--model NAME` selects the model.
- `--dns-host example.com` tests a hostname before and after an approved Windows DNS cache flush.
- `--json` prints machine-readable results and never executes actions.
- `--timeout SECONDS` controls the model request timeout (default 180).

Environment variables:

| Variable | Meaning |
| --- | --- |
| `DIAG_MODEL` | Default model for all stages. |
| `DIAG_ANALYSER_MODEL` | Model used for analysis. |
| `DIAG_RECTIFIER_MODEL` | Model used for the optional DNS action decision. |
| `OLLAMA_HOST` | Ollama address (default `http://127.0.0.1:11434`). |
| `OLLAMA_API_KEY` | Optional bearer token for a remote Ollama endpoint. |

## What is collected

- OS family, version and architecture.
- CPU count, current CPU percentage, load average and uptime.
- Memory total/available in GiB and used percentage.
- Disk mount points, filesystem, total/free GiB and used percentage.
- Network interface names, state and IPv4 addresses; default routes.
- Battery percentage and whether the laptop is plugged in, when available.
- Windows only: up to 20 recent critical/error System event **metadata** records from the last day (timestamp, provider, event ID, level).

It never reads documents, browser data, process names, event messages or file contents. The complaint and this evidence are sent to the model; for a cloud model that data leaves your computer. Do not include secrets in the complaint. Review the answer and its uncertainty; a model can be wrong.

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

Open `http://127.0.0.1:8000`. The UI never runs repairs. Do not bind it to a public interface; it has no authentication beyond a single-diagnosis lock.

### Docker demo

```bash
docker compose up --build
```

The container inspects **the container**, not your host PC. It reaches Ollama on the host through `host.docker.internal`. Override with `OLLAMA_HOST` and `DIAG_MODEL` if needed:

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
- Model not found: `ollama pull MODEL`, or choose another with `--model`.
- Remote Ollama: set `OLLAMA_HOST` and `OLLAMA_API_KEY`.
- Windows console encoding: Fieldnote reconfigures stdout to UTF-8; if your terminal still garbles characters, use Windows Terminal or set `PYTHONUTF8=1`.
- `fieldnote` not found after install: use `python -m fieldnote`.

## License

MIT. See [LICENSE](LICENSE).
