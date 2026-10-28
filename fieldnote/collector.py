"""Read-only, bounded host evidence collection for Windows, Linux and macOS.

Windows is the primary target. The collector uses psutil for portable metrics
and one short PowerShell call for System event metadata and default routes.
No event messages, process names, file contents or user documents are read.
"""

from __future__ import annotations

import glob
import json
import os
import platform
import shutil
import socket
import subprocess
import time
from typing import Any

import psutil

GIB = 1024**3

PSEUDO_FILESYSTEMS = {
    "autofs",
    "cgroup",
    "cgroup2",
    "devfs",
    "devtmpfs",
    "proc",
    "ramfs",
    "squashfs",
    "sysfs",
    "tmpfs",
}

WINDOWS_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$OutputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$result = [ordered]@{}
try {
  $filter = @{LogName='System'; Level=1,2; StartTime=(Get-Date).AddDays(-1)}
  $result.system_events = @(Get-WinEvent -FilterHashtable $filter -MaxEvents 20 -ErrorAction Stop |
    ForEach-Object { [ordered]@{ time = $_.TimeCreated.ToString('o');
      provider = $_.ProviderName; id = $_.Id; level = $_.LevelDisplayName } })
} catch { $result.system_events = @() }
try {
  $result.default_routes = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0' -ErrorAction Stop |
    Select-Object -First 10 InterfaceAlias,NextHop,RouteMetric)
} catch { $result.default_routes = @() }
try {
  $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
  $result.os_caption = $os.Caption
  $result.os_version = $os.Version
  $result.last_boot = $os.LastBootUpTime.ToString('o')
} catch {}
try {
  $result.video_controllers = @(Get-CimInstance Win32_VideoController -ErrorAction Stop |
    Select-Object -First 10 Name,Status,VideoModeDescription,CurrentHorizontalResolution,CurrentVerticalResolution)
} catch {}
$result | ConvertTo-Json -Depth 5 -Compress
"""


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    options: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "check": False,
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(command, **options)


def _windows_evidence() -> dict[str, Any]:
    shell = (
        shutil.which("powershell.exe")
        or shutil.which("powershell")
        or shutil.which("pwsh")
    )
    if not shell:
        return {"unavailable": "PowerShell was not found; event metadata is unavailable."}
    try:
        result = _run(
            [
                shell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                WINDOWS_SCRIPT,
            ],
            30,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"unavailable": f"PowerShell failed: {error}"}

    text = (result.stdout or "").lstrip("\ufeff").strip()
    if not text:
        return {"unavailable": "PowerShell returned no data."}
    try:
        data = json.loads(text)
    except ValueError:
        return {"unavailable": "PowerShell returned invalid JSON."}
    if not isinstance(data, dict):
        return {"unavailable": "PowerShell returned unexpected data."}

    if not isinstance(data.get("system_events"), list):
        data["system_events"] = []
    if not isinstance(data.get("default_routes"), list):
        data["default_routes"] = []
    return data


def _base_evidence() -> dict[str, Any]:
    system = platform.system()
    os_name = {"Darwin": "macOS", "Windows": "Windows", "Linux": "Linux"}.get(system, system)
    evidence: dict[str, Any] = {
        "os": os_name,
        "os_version": platform.platform(),
        "architecture": platform.machine(),
        "cpu_count": psutil.cpu_count(logical=True),
        "cpu_percent": None,
        "memory": "unavailable",
        "disks": [],
        "load_average": [],
        "uptime_hours": None,
    }

    try:
        evidence["cpu_percent"] = psutil.cpu_percent(interval=0.3)
    except (OSError, RuntimeError):
        pass

    try:
        memory = psutil.virtual_memory()
        evidence["memory"] = {
            "total_gib": round(memory.total / GIB, 1),
            "available_gib": round(memory.available / GIB, 1),
            "used_percent": memory.percent,
        }
    except (OSError, RuntimeError):
        pass

    try:
        evidence["load_average"] = [round(value, 2) for value in psutil.getloadavg()]
    except (AttributeError, OSError, NotImplementedError):
        pass

    try:
        evidence["uptime_hours"] = round((time.time() - psutil.boot_time()) / 3600, 1)
    except (OSError, RuntimeError):
        pass

    try:
        evidence["process_count"] = len(psutil.pids())
    except (OSError, RuntimeError):
        pass

    try:
        battery = psutil.sensors_battery()
        if battery is not None:
            evidence["battery"] = {
                "percent": round(battery.percent),
                "plugged_in": bool(battery.power_plugged),
            }
    except (AttributeError, OSError, RuntimeError):
        pass

    disks: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        partitions = psutil.disk_partitions(all=False)
    except (OSError, RuntimeError):
        partitions = []
    for partition in partitions[:20]:
        if partition.mountpoint in seen:
            continue
        if (partition.fstype or "").lower() in PSEUDO_FILESYSTEMS:
            continue
        seen.add(partition.mountpoint)
        try:
            usage = psutil.disk_usage(partition.mountpoint)
        except (OSError, PermissionError):
            continue
        disks.append(
            {
                "mount": partition.mountpoint,
                "filesystem": partition.fstype or "unknown",
                "total_gib": round(usage.total / GIB, 1),
                "free_gib": round(usage.free / GIB, 1),
                "used_percent": usage.percent,
            }
        )
    evidence["disks"] = disks
    return evidence


def _linux_display() -> dict[str, Any]:
    display: dict[str, Any] = {}
    connectors: list[dict[str, str]] = []
    for status_path in sorted(glob.glob("/sys/class/drm/card*-*/status"))[:20]:
        connector = os.path.basename(os.path.dirname(status_path))
        try:
            with open(status_path, encoding="ascii") as status_file:
                status = status_file.read().strip()
        except OSError:
            continue
        entry = {"connector": connector, "status": status}
        for field in ("enabled", "dpms"):
            field_path = os.path.join(os.path.dirname(status_path), field)
            try:
                with open(field_path, encoding="ascii") as field_file:
                    value = field_file.read().strip()
            except OSError:
                continue
            if value:
                entry[field] = value
        connectors.append(entry)
    if connectors:
        display["drm_connectors"] = connectors

    xrandr = shutil.which("xrandr")
    if xrandr:
        try:
            result = _run([xrandr, "--query"], 5)
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0 and result.stdout.strip():
            display["xrandr"] = result.stdout.strip()[:6000]

    lspci = shutil.which("lspci")
    if lspci:
        try:
            result = _run([lspci], 5)
        except (OSError, subprocess.SubprocessError):
            result = None
        if result is not None and result.returncode == 0:
            lines = [
                line
                for line in result.stdout.splitlines()
                if any(name in line for name in ("VGA", "3D", "Display"))
            ]
            if lines:
                display["pci_display"] = lines[:10]

    if display:
        return display
    return {"unavailable": "No display information was found in /sys/class/drm or xrandr."}


def _interfaces() -> list[dict[str, Any]]:
    try:
        addresses = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except (OSError, RuntimeError):
        return []

    interfaces: list[dict[str, Any]] = []
    for name in sorted(addresses)[:20]:
        ipv4 = [
            address.address
            for address in addresses[name]
            if address.family == socket.AF_INET
        ]
        state = "unknown"
        if name in stats:
            state = "up" if stats[name].isup else "down"
        if not ipv4 and state == "unknown":
            continue
        interfaces.append({"name": name, "state": state, "ipv4": ipv4[:4]})
    return interfaces


def _linux_routes() -> list[dict[str, Any]] | str:
    try:
        result = _run(["ip", "-j", "route"], 5)
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, list):
                return [
                    {
                        "destination": item.get("dst"),
                        "gateway": item.get("gateway"),
                        "interface": item.get("dev"),
                    }
                    for item in data[:20]
                ]
    except (OSError, subprocess.SubprocessError, ValueError):
        pass

    try:
        with open("/proc/net/route", encoding="ascii") as route_file:
            routes = []
            for line in list(route_file)[1:21]:
                fields = line.split()
                if len(fields) >= 3:
                    routes.append(
                        {
                            "destination_hex": fields[1],
                            "gateway_hex": fields[2],
                            "interface": fields[0],
                        }
                    )
            return routes
    except OSError:
        return "unavailable"


def _macos_routes() -> list[dict[str, Any]] | str:
    try:
        result = _run(["route", "-n", "get", "default"], 5)
        if result.returncode == 0:
            route: dict[str, str] = {}
            for line in result.stdout.splitlines():
                key, separator, value = line.partition(":")
                if separator and key.strip() in {"destination", "gateway", "interface"}:
                    route[key.strip()] = value.strip()
            if route:
                return [route]
    except (OSError, subprocess.SubprocessError):
        pass
    return "unavailable"


def collect_system() -> dict[str, Any]:
    """Collect a bounded, read-only snapshot of the local host."""
    evidence = _base_evidence()
    evidence["network"] = {"interfaces": _interfaces(), "routes": "unavailable"}

    if evidence["os"] == "Windows":
        windows = _windows_evidence()
        evidence["windows"] = windows
        if isinstance(windows, dict):
            routes = windows.get("default_routes")
            if isinstance(routes, list) and routes:
                evidence["network"]["routes"] = routes
    elif evidence["os"] == "Linux":
        evidence["network"]["routes"] = _linux_routes()
        evidence["display"] = _linux_display()
    elif evidence["os"] == "macOS":
        evidence["network"]["routes"] = _macos_routes()

    return evidence


def dns_check(hostname: str | None) -> dict[str, Any] | None:
    """Resolve a hostname without using the model."""
    if not hostname:
        return None
    try:
        socket.getaddrinfo(hostname, None)
        return {"hostname": hostname, "resolved": True}
    except socket.gaierror:
        return {"hostname": hostname, "resolved": False}
