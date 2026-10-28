"""Fixed, pre-approved corrective actions.

The model never supplies commands. Only the operations in this module can run.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

from .collector import dns_check


def action_supported(evidence: dict[str, Any]) -> bool:
    return evidence.get("os") == "Windows"


def flush_dns_cache() -> dict[str, Any]:
    """Run the fixed Windows DNS cache flush and return its result."""
    command = shutil.which("ipconfig.exe") or shutil.which("ipconfig")
    if not command:
        raise RuntimeError("ipconfig was not found; cannot flush the DNS cache.")
    try:
        completed = subprocess.run(
            [command, "/flushdns"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"DNS cache flush failed: {error}") from error
    return {
        "exit_code": completed.returncode,
        "stdout": (completed.stdout or "").strip()[:1000],
        "stderr": (completed.stderr or "").strip()[:1000],
    }


def verify_dns(hostname: str) -> dict[str, Any] | None:
    return dns_check(hostname)
