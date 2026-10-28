"""Command-line interface for Fieldnote Diagnostics."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from urllib import parse, request

from . import __version__, claude_code
from .actions import action_supported, flush_dns_cache, verify_dns
from .agent import investigate
from .analysis import (
    analyse,
    analyser_model,
    backend_name,
    propose_rectification,
    rectifier_model,
)
from .collector import collect_system, dns_check
from .ollama_client import (
    default_model,
    host,
    list_models,
    server_status,
)


def _reconfigure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fieldnote",
        description="Read-only host diagnostics with Ollama (local or cloud models).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze = subparsers.add_parser(
        "analyze",
        aliases=["diagnose"],
        help="Collect evidence and ask the model to analyse a complaint.",
    )
    analyze.add_argument("complaint", help="Describe the problem in a few sentences.")
    analyze.add_argument(
        "--model",
        help=f"Any Ollama model available to your account (default: {default_model()}).",
    )
    analyze.add_argument(
        "--dns-host",
        help="Hostname to resolve before and after an approved Windows DNS cache flush.",
    )
    analyze.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON. Never executes corrective actions.",
    )
    analyze.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Model request timeout in seconds (default: 180).",
    )
    analyze.add_argument(
        "--no-commands",
        action="store_true",
        help="Do not let the model request read-only diagnostic checks.",
    )

    subparsers.add_parser(
        "inspect",
        help="Print collected host evidence without contacting a model.",
    )

    serve = subparsers.add_parser("serve", help="Start the local browser interface.")
    serve.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
    serve.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")

    start = subparsers.add_parser(
        "start",
        help="Start Ollama if needed, launch the browser interface, and open it.",
    )
    start.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
    start.add_argument("--port", type=int, default=8000, help="Port (default: 8000).")
    start.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open the browser automatically.",
    )

    doctor = subparsers.add_parser(
        "doctor",
        help="Check Ollama connectivity and model configuration.",
    )
    doctor.add_argument("--model", help="Model to report.")

    return parser


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdio()
    args = build_parser().parse_args(argv)

    try:
        if args.command == "inspect":
            print(json.dumps(collect_system(), indent=2))
            return 0
        if args.command == "serve":
            return _serve(args)
        if args.command == "start":
            return _start(args)
        if args.command == "doctor":
            return _doctor(args)
        return asyncio.run(_analyze(args))
    except KeyboardInterrupt:
        print("Stopped.", file=sys.stderr)
        return 130
    except (RuntimeError, ValueError) as error:
        print(f"Stopped: {error}", file=sys.stderr)
        return 1


def _serve(args: argparse.Namespace) -> int:
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "Warning: this interface has no authentication. Bind it to localhost only.",
            file=sys.stderr,
        )
    import uvicorn

    uvicorn.run("fieldnote.app:app", host=args.host, port=args.port)
    return 0


def _ensure_ollama() -> bool:
    if server_status(timeout=1)[0]:
        return True

    endpoint = host()
    parsed = parse.urlparse(endpoint)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        print(
            f"Ollama is not reachable at {endpoint}. Start it or check OLLAMA_HOST.",
            file=sys.stderr,
        )
        return False

    executable = shutil.which("ollama")
    if not executable:
        print(
            "Ollama is not installed. Install it from https://ollama.com/download, "
            "then run this command again.",
            file=sys.stderr,
        )
        return False

    log_path = Path(tempfile.gettempdir()) / "fieldnote-ollama.log"
    print("Starting Ollama...", flush=True)
    options = {
        "stdin": subprocess.DEVNULL,
        "stdout": None,
        "stderr": subprocess.STDOUT,
    }
    try:
        with log_path.open("ab") as log:
            options["stdout"] = log
            if os.name == "nt":
                options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            else:
                options["start_new_session"] = True
            process = subprocess.Popen([executable, "serve"], **options)
    except OSError as error:
        print(f"Could not start Ollama: {error}", file=sys.stderr)
        return False

    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if server_status(timeout=1)[0]:
            print(f"Ollama started (PID {process.pid}).", flush=True)
            return True
        if process.poll() is not None:
            break
        time.sleep(0.5)

    print(f"Ollama did not become ready. See {log_path} for details.", file=sys.stderr)
    return False


def _open_browser_when_ready(url: str, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    health = f"{url}/healthz"
    while time.monotonic() < deadline:
        try:
            with request.urlopen(health, timeout=1):
                pass
        except OSError:
            time.sleep(0.25)
            continue
        if not webbrowser.open(url):
            print(f"Open {url} in your browser.", file=sys.stderr)
        return
    print(f"Open {url} in your browser.", file=sys.stderr)


def _schedule_browser(url: str) -> None:
    thread = threading.Thread(target=_open_browser_when_ready, args=(url,), daemon=True)
    thread.start()


def _display_host(value: str) -> str:
    if value in {"0.0.0.0", "::"}:
        return "127.0.0.1"
    if ":" in value:
        return f"[{value}]"
    return value


def _start(args: argparse.Namespace) -> int:
    if not _ensure_ollama():
        return 1

    url = f"http://{_display_host(args.host)}:{args.port}"
    print(f"Fieldnote: {url}", flush=True)
    print("Press Ctrl+C to stop the web interface.", flush=True)
    if not args.no_browser:
        _schedule_browser(url)
    return _serve(args)


def _doctor(args: argparse.Namespace) -> int:
    model = args.model or analyser_model()
    reachable, message = server_status()
    print(f"Fieldnote {__version__}")
    print(f"OS: {platform.system()} {platform.release()}")
    print(f"Python: {platform.python_version()}")
    print(f"Ollama: {host()}")
    print(f"Reachable: {'yes' if reachable else 'no'}")
    if not reachable:
        print(f"Detail: {message}", file=sys.stderr)
        return 1

    backend = backend_name()
    print(f"Analysis backend: {backend}")
    if backend == "claude":
        found = claude_code.available()
        print(f"Claude Code: {'found' if found else 'not found'}")
        if not found:
            print(
                "Install Claude Code or set DIAG_BACKEND=ollama.",
                file=sys.stderr,
            )
            return 1
    models = list_models()
    print(f"Local models: {', '.join(models) if models else 'none listed'}")
    print(f"Selected model: {model}")
    print(
        "Verify model access with "
        f"'ollama run {model}'."
    )
    return 0


async def _analyze(args: argparse.Namespace) -> int:
    complaint = args.complaint.strip()
    if not 1 <= len(complaint) <= 4000:
        raise ValueError("complaint must contain 1 to 4000 characters")
    if args.timeout < 5:
        raise ValueError("timeout must be at least 5 seconds")
    if args.dns_host and (
        len(args.dns_host) > 253 or not re.fullmatch(r"[A-Za-z0-9.-]+", args.dns_host)
    ):
        raise ValueError("dns-host must be a hostname")

    model = args.model or analyser_model()
    backend = backend_name()
    evidence = collect_system()
    evidence["dns"] = (
        dns_check(args.dns_host)
        if args.dns_host
        else "not tested; no test hostname configured"
    )

    commands: list[dict[str, object]] = []
    if getattr(args, "no_commands", False):
        analysis = await analyse(model, complaint, evidence, timeout=args.timeout)
    else:
        outcome = await investigate(model, complaint, evidence, timeout=args.timeout)
        analysis = outcome["analysis"]
        commands = outcome["commands"]
    action_possible = bool(
        action_supported(evidence)
        and args.dns_host
        and evidence["dns"].get("resolved") is False
    )

    if args.json:
        print(
            json.dumps(
                {
                    "version": __version__,
                    "model": model,
                    "backend": backend,
                    "complaint": complaint,
                    "evidence": evidence,
                    "analysis": analysis,
                    "commands": commands,
                    "action_supported": action_possible,
                    "action": None,
                    "action_note": "Corrective actions are never run in --json mode.",
                },
                indent=2,
                ensure_ascii=True,
            )
        )
        return 0

    print(f"Detected system: {evidence['os']}", flush=True)
    print(f"Backend: {backend}", flush=True)
    print(f"Model: {model}", flush=True)
    if commands:
        print("\nRead-only checks:", flush=True)
        for item in commands:
            status = "ok" if item.get("allowed") and item.get("exit_code") == 0 else "not run"
            print(f"  $ {item.get('command')} ({status})", flush=True)
            if item.get("reason"):
                print(f"    {item['reason']}", flush=True)
    print("\nAnalysis:\n" + analysis, flush=True)

    if not action_possible:
        print("\nNo supported corrective action for these observations on this system.")
        return 0

    decision = await propose_rectification(
        rectifier_model(),
        complaint,
        evidence,
        analysis,
    )
    print(f"\nProposed action: {decision['action']}")
    print(f"Reason: {decision['reason']}")
    if decision["action"] != "flush_dns_cache":
        return 0

    print(
        "This clears the Windows DNS client cache. It can temporarily affect name "
        "lookup performance and does not repair all DNS failures."
    )
    if not sys.stdin.isatty():
        print("\nNo interactive terminal available; action skipped.")
        return 0
    if input("Run ipconfig /flushdns? Type YES to approve: ").strip() != "YES":
        print("No change made.")
        return 0

    outcome = flush_dns_cache()
    print(f"Command exit code: {outcome['exit_code']}")
    if outcome["exit_code"] != 0:
        print("Action failed; the issue is not verified as fixed.")
        return 1

    after = verify_dns(args.dns_host)
    resolved = bool(after and after.get("resolved"))
    print("DNS test after action:", "resolved" if resolved else "still failed")
    if resolved:
        print(
            "A successful lookup suggests improvement; it does not prove the cache "
            "caused the problem."
        )
    else:
        print("The issue is not verified as fixed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
