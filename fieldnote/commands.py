"""Shell-free diagnostic command execution for the agent.

Commands are never passed through a shell. Each pipeline stage is parsed with
``shlex``. Most diagnostics are allowed; a denylist blocks destructive and
state-changing executables, and targeted validators reject mutating options on
tools that can both inspect and change the host. File arguments are screened
for credentials, private data and raw memory devices.
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from typing import Any

DEFAULT_TIMEOUT = 10
MAX_COMMAND_LENGTH = 500
MAX_OUTPUT = 8000
MAX_PIPELINE = 4

BLOCKED_TOKENS = frozenset({";", "&&", "||", "&", ">", ">>", "<", "<<", "|&", "2>", "2>>", "&>", "&>>", "`"})

DENIED_EXECUTABLES = frozenset(
    {
        "uv",
        "updatedb",
        "toybox",
        "taskset",
        "stdbuf",
        "sqlite3",
        "setpriv",
        "redis-cli",
        "qdbus",
        "poetry",
        "micromamba",
        "mamba",
        "gdbus",
        "gdb",
        "flock",
        "deno",
        "dbus-send",
        "conda",
        "chrt",
        "capsh",
        "bun",
        "zsh",
        "wpa_cli",
        "tcsh",
        "subl",
        "setsebool",
        "semanage",
        "setfacl",
        "setcap",
        "scoop",
        "restorecon",
        "port",
        "nvim",
        "nmtui",
        "lftp",
        "ksh",
        "iwconfig",
        "hciconfig",
        "gvim",
        "ftp",
        "fish",
        "dash",
        "csh",
        "cp",
        "code",
        "choco",
        "chcon",
        "blockdev",
        "bash",
        "axel",
        "aria2c",
        "at",
        "apt",
        "apt-get",
        "aptitude",
        "awk",
        "badblocks",
        "batch",
        "blkdiscard",
        "busybox",
        "cargo",
        "cfdisk",
        "chage",
        "chattr",
        "chmod",
        "chown",
        "chgrp",
        "chpasswd",
        "chroot",
        "cmake",
        "crontab",
        "cryptsetup",
        "ctr",
        "dd",
        "depmod",
        "dmsetup",
        "docker",
        "doas",
        "dpkg",
        "dnf",
        "ebtables",
        "ed",
        "emacs",
        "env",
        "fallocate",
        "fdisk",
        "firewall-cmd",
        "flatpak",
        "fsck",
        "gdisk",
        "gedit",
        "gpg",
        "gpg2",
        "groupadd",
        "groupdel",
        "groupmod",
        "halt",
        "helm",
        "init",
        "insmod",
        "install",
        "ionice",
        "ip6tables",
        "ipset",
        "iptables",
        "iptables-restore",
        "joe",
        "kate",
        "kexec",
        "kill",
        "killall",
        "kubectl",
        "less",
        "link",
        "ln",
        "logger",
        "losetup",
        "lvchange",
        "lvcreate",
        "lvextend",
        "lvreduce",
        "lvremove",
        "make",
        "mdadm",
        "micro",
        "mkfifo",
        "mkfs",
        "mknod",
        "modprobe",
        "more",
        "most",
        "mount",
        "mv",
        "nano",
        "nc",
        "ncat",
        "nerdctl",
        "netcat",
        "nft",
        "nice",
        "ninja",
        "nohup",
        "nsenter",
        "openssl",
        "pacman",
        "parallel",
        "parted",
        "passwd",
        "pico",
        "pkexec",
        "podman",
        "poweroff",
        "prlimit",
        "pvchange",
        "pvcreate",
        "pvmove",
        "pvremove",
        "reboot",
        "rename",
        "renice",
        "rm",
        "rmdir",
        "rpm",
        "rsync",
        "runuser",
        "scp",
        "sed",
        "setsid",
        "sfdisk",
        "sftp",
        "sgdisk",
        "sh",
        "shred",
        "shutdown",
        "smbclient",
        "snap",
        "socat",
        "srm",
        "ssh",
        "ssh-add",
        "ssh-keygen",
        "su",
        "sudo",
        "swapoff",
        "swapon",
        "systemd-run",
        "tee",
        "telinit",
        "telnet",
        "timeout",
        "touch",
        "trash",
        "truncate",
        "ufw",
        "umount",
        "unlink",
        "unshare",
        "useradd",
        "userdel",
        "usermod",
        "vgchange",
        "vgcreate",
        "vgextend",
        "vgreduce",
        "vgremove",
        "view",
        "vim",
        "visudo",
        "watch",
        "wget",
        "winget",
        "wipe",
        "wipefs",
        "xargs",
        "zfs",
        "zpool",
        "zypper",
    }
)

DENIED_PREFIXES = (
    "cc",
    "clang",
    "dotnet",
    "g++",
    "gcc",
    "go",
    "java",
    "julia",
    "lua",
    "luajit",
    "mkfs",
    "node",
    "nodejs",
    "npm",
    "php",
    "pip",
    "pnpm",
    "python",
    "Rscript",
    "ruby",
    "rustc",
    "swift",
    "yarn",
)

SENSITIVE_PATH_MARKERS = (
    "/.aws",
    "/.azure",
    "/.config/gh",
    "/.config/gcloud",
    "/.config/google-chrome",
    "/.config/chromium",
    "/.config/microsoft-edge",
    "/.docker",
    "/.gnupg",
    "/.kube",
    "/.local/share/keyrings",
    "/.mozilla",
    "/.password-store",
    "/.ssh",
    "/dev/input",
    "/dev/kmsg",
    "/dev/kmem",
    "/dev/mem",
    "/dev/port",
    "/etc/ssh",
    "/etc/ssl/private",
    "/proc/kcore",
    "/proc/key-users",
    "/proc/keys",
    "/proc/sysrq-trigger",
    "/sys/kernel/debug",
    "/var/lib/private",
)

SENSITIVE_EXACT_PATHS = frozenset(
    {
        "/etc/gshadow",
        "/etc/gshadow-",
        "/etc/master.passwd",
        "/etc/security/opasswd",
        "/etc/shadow",
        "/etc/shadow-",
        "/etc/sudoers",
        "/proc/kcore",
        "/proc/sched_debug",
        "/proc/timer_list",
    }
)

SENSITIVE_BASENAMES = frozenset(
    {
        ".env",
        ".git-credentials",
        ".netrc",
        ".npmrc",
        ".pypirc",
        "credentials",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
        "kdbx",
        "secrets",
        "shadow",
        "gshadow",
        "sudoers",
    }
)

SENSITIVE_SUFFIXES = (".jks", ".kdbx", ".keystore", ".key", ".p12", ".pfx")

RAW_DEVICE_PREFIXES = ("/dev/disk/", "/dev/mmcblk", "/dev/nvme", "/dev/sd", "/dev/vd", "/dev/xvd")
RAW_DEVICE_COMMANDS = frozenset({"blkid", "hdparm", "lsblk", "nvme", "sdparm", "smartctl"})

SYSTEMCTL_BLOCKED = frozenset(
    {
        "add-wants",
        "add-requires",
        "bind",
        "clean",
        "daemon-reexec",
        "daemon-reload",
        "disable",
        "edit",
        "enable",
        "freeze",
        "halt",
        "isolate",
        "kill",
        "link",
        "mask",
        "poweroff",
        "preset",
        "reboot",
        "reload",
        "reload-or-restart",
        "reset-failed",
        "restart",
        "revert",
        "set-default",
        "set-environment",
        "set-property",
        "start",
        "stop",
        "switch-root",
        "thaw",
        "try-restart",
        "unmask",
    }
)
IP_BLOCKED = frozenset(
    {
        "add",
        "append",
        "change",
        "del",
        "delete",
        "down",
        "flush",
        "prepend",
        "replace",
        "restore",
        "save",
        "set",
        "up",
    }
)
NMCLI_BLOCKED = frozenset(
    {"add", "connect", "delete", "disable", "disconnect", "down", "enable", "modify", "off", "on", "reload", "up"}
)
XRANDR_BLOCKED = frozenset(
    {
        "--addmode",
        "--auto",
        "--delmode",
        "--dpi",
        "--fb",
        "--fbmm",
        "--mode",
        "--newmode",
        "--noprimary",
        "--off",
        "--output",
        "--panning",
        "--primary",
        "--rate",
        "--reflect",
        "--rmmode",
        "--rotate",
        "--scale",
        "--set",
        "--transform",
    }
)
FIND_BLOCKED = frozenset(
    {
        "-delete",
        "-exec",
        "-execdir",
        "-fls",
        "-follow",
        "-fprint",
        "-fprint0",
        "-fprintf",
        "-h",
        "-l",
        "-ok",
        "-okdir",
    }
)
ETHTOOL_BLOCKED = frozenset(
    {
        "-A",
        "-C",
        "-E",
        "-G",
        "-K",
        "-L",
        "-N",
        "-P",
        "-W",
        "-f",
        "-p",
        "-r",
        "-s",
        "-t",
        "--change",
        "--flash",
        "--identify",
        "--reset",
        "--set-channels",
        "--set-coalesce",
        "--set-features",
        "--set-pause",
        "--set-ring",
        "--set-wol",
        "--test",
    }
)
HDparm_ALLOWED = frozenset({"-C", "-I", "-g", "-i", "-T", "-t", "-v", "--direct", "--help", "--version"})
SMARTCTL_BLOCKED = frozenset(
    {
        "-n",
        "-o",
        "-P",
        "-s",
        "-S",
        "-t",
        "-W",
        "-X",
        "--abort",
        "--offlineauto",
        "--saveauto",
        "--set",
        "--smart",
        "--test",
        "--update",
        "--writecache",
    }
)
NVME_READ_ONLY = frozenset(
    {
        "effects-log",
        "error-log",
        "fw-log",
        "get-feature",
        "get-log",
        "get-property",
        "id-ctrl",
        "id-ns",
        "id-ns-lba-format",
        "list",
        "list-subsys",
        "show-regs",
        "smart-log",
        "smart-log-add",
        "version",
    }
)
GIT_READ_ONLY = frozenset(
    {
        "blame",
        "branch",
        "config",
        "describe",
        "diff",
        "log",
        "ls-files",
        "ls-tree",
        "remote",
        "rev-parse",
        "show",
        "shortlog",
        "status",
        "tag",
    }
)
GIT_BLOCKED = frozenset(
    {
        "add",
        "am",
        "apply",
        "checkout",
        "cherry-pick",
        "clean",
        "clone",
        "commit",
        "fetch",
        "gc",
        "init",
        "merge",
        "mv",
        "prune",
        "pull",
        "push",
        "rebase",
        "reset",
        "restore",
        "revert",
        "rm",
        "stash",
        "switch",
        "worktree",
    }
)
TAR_BLOCKED = frozenset(
    {
        "-A",
        "-c",
        "-d",
        "-r",
        "-u",
        "--append",
        "--concatenate",
        "--create",
        "--delete",
        "--diff",
        "--extract",
        "--get",
        "--update",
    }
)
CURL_BLOCKED = frozenset(
    {
        "-F",
        "-O",
        "-T",
        "-c",
        "-d",
        "-o",
        "--cookie-jar",
        "--create-file-mode",
        "--data",
        "--data-ascii",
        "--data-binary",
        "--data-raw",
        "--data-urlencode",
        "--dump-header",
        "--form",
        "--output",
        "--output-dir",
        "--remote-header-name",
        "--remote-name",
        "--request-target",
        "--stderr",
        "--trace",
        "--trace-ascii",
        "--upload-file",
    }
)
CURL_UNSAFE_SCHEMES = ("dict://", "file://", "ftp://", "gopher://", "scp://", "sftp://", "smb://", "telnet://")
BARE_PATH_COMMANDS = frozenset(
    {
        "base64",
        "cat",
        "cmp",
        "cut",
        "diff",
        "file",
        "head",
        "hexdump",
        "md5sum",
        "od",
        "readlink",
        "realpath",
        "sha1sum",
        "sha256sum",
        "stat",
        "strings",
        "tail",
        "tr",
        "uniq",
        "wc",
        "xxd",
    }
)


def _cap(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= MAX_OUTPUT:
        return text
    return text[:MAX_OUTPUT] + "\n...[output truncated]"


def _denied(command: str, reason: str) -> dict[str, Any]:
    return {
        "command": command,
        "allowed": False,
        "exit_code": None,
        "output": "",
        "reason": reason,
    }


def _split_pipeline(tokens: list[str]) -> list[list[str]] | str:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in BLOCKED_TOKENS:
            return f"Shell operator {token!r} is not allowed."
        if token == "|":
            if not current:
                return "Empty pipeline stage."
            segments.append(current)
            current = []
            continue
        current.append(token)
    if current:
        segments.append(current)
    if not segments:
        return "No command was provided."
    if len(segments) > MAX_PIPELINE:
        return f"At most {MAX_PIPELINE} pipeline stages are allowed."
    return segments


def _executable_denied(name: str) -> bool:
    lowered = name.lower()
    if lowered in DENIED_EXECUTABLES:
        return True
    return any(lowered.startswith(prefix) for prefix in DENIED_PREFIXES)


def _option(token: str) -> str:
    return token.split("=", 1)[0].lower()


def _path_candidates(tokens: list[str]) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    for token in tokens:
        values = [token]
        if "=" in token:
            values.append(token.split("=", 1)[1])
        for value in values:
            if not value or "://" in value:
                continue
            if value.startswith("-") and "/" in value:
                values.append(value[value.find("/") :])
                continue
            if value.startswith("-"):
                continue
            if value.startswith(("/", "./", "../")) or "/" in value or "\\" in value:
                if value not in seen:
                    seen.add(value)
                    candidates.append(value)
                embedded = value[value.find("/") :]
                if embedded != value and embedded not in seen:
                    seen.add(embedded)
                    candidates.append(embedded)
    return candidates


def _resolved_path(path: str) -> tuple[str, str]:
    expanded = os.path.expanduser(path)
    if not os.path.isabs(expanded):
        expanded = os.path.join(os.getcwd(), expanded)
    normalized = os.path.normpath(expanded)
    real = os.path.realpath(normalized)
    return normalized, real


def _proc_is_private(candidate: str) -> bool:
    if not candidate.startswith("/proc/"):
        return False
    parts = candidate[len("/proc/") :].split("/")
    if parts and parts[0] in {"kcore", "key-users", "keys", "sched_debug", "sysrq-trigger", "timer_list"}:
        return True
    return len(parts) >= 2 and parts[1] in {
        "cmdline",
        "cwd",
        "environ",
        "fd",
        "maps",
        "mem",
        "root",
        "smaps",
        "task",
    }


def _sensitive_path(path: str) -> bool:
    normalized, real = _resolved_path(path)
    for candidate in {normalized, real}:
        if candidate in SENSITIVE_EXACT_PATHS:
            return True
        if candidate == "/root" or candidate.startswith("/root/"):
            return True
        if candidate.startswith(("/etc/shadow", "/etc/gshadow", "/etc/sudoers", "/etc/ssl/private")):
            return True
        if any(marker in candidate for marker in SENSITIVE_PATH_MARKERS):
            return True
        if _proc_is_private(candidate):
            return True
        base = os.path.basename(candidate)
        if base == ".env" or base.startswith(".env."):
            return True
        if base in SENSITIVE_BASENAMES or base.endswith(SENSITIVE_SUFFIXES):
            return True
    return False


def _raw_device(path: str) -> bool:
    normalized, real = _resolved_path(path)
    return any(candidate.startswith(RAW_DEVICE_PREFIXES) for candidate in {normalized, real})


def _validate_paths(name: str, tokens: list[str]) -> str | None:
    for path in _path_candidates(tokens):
        if _sensitive_path(path):
            return f"Path {path!r} is private or can expose credentials."
        if _raw_device(path) and name not in RAW_DEVICE_COMMANDS:
            return f"Raw device {path!r} can only be inspected with a disk-info tool."
    if name in BARE_PATH_COMMANDS:
        for token in tokens[1:]:
            if token.startswith("-") or "://" in token or "/" in token or "\\" in token:
                continue
            if _sensitive_path(token):
                return f"Path {token!r} is private or can expose credentials."
    return None


def _first(tokens: list[str], default: str = "") -> str:
    return tokens[0].lower() if tokens else default


def _validate_segment(tokens: list[str]) -> str | None:
    name = tokens[0].lower()
    args = tokens[1:]
    lowered = [token.lower() for token in args]

    if "/" in name or "\\" in name:
        return "Executable paths are not allowed; use a command name."
    if _executable_denied(name):
        return f"{name!r} is blocked because it can modify the system or read private data."
    for token in tokens:
        if any(character in token for character in (";", "&", ">", "<", "`")):
            return "Shell metacharacters are not allowed."

    path_error = _validate_paths(name, tokens)
    if path_error:
        return path_error

    if name == "journalctl":
        blocked = {
            "-f",
            "--follow",
            "--flush",
            "--relinquish-var",
            "--rotate",
            "--setup-keys",
            "--smart-relinquish-var",
            "--sync",
            "--update-catalog",
            "--vacuum-files",
            "--vacuum-size",
            "--vacuum-time",
        }
        if any(_option(token) in blocked for token in lowered):
            return "journalctl follow, vacuum and maintenance options are not allowed."
    elif name == "dmesg":
        blocked = {"-c", "-w", "--clear", "--console-off", "--console-on", "--follow"}
        if any(_option(token) in blocked for token in lowered) or any(
            token.startswith("--console-level") for token in lowered
        ):
            return "dmesg clear, follow and console options are not allowed."
    elif name == "tail":
        if any(token in {"-f", "-F", "--follow", "--retry"} for token in lowered):
            return "tail follow mode is not allowed."
    elif name == "date":
        if any(token in {"-s", "--set", "-f", "--file"} for token in lowered) or any(
            token.startswith(("--set=", "-s")) for token in lowered
        ):
            return "date state changes and file input are not allowed."
    elif name == "hostname":
        safe = {"-f", "-s", "-d", "-i", "-I", "--fqdn", "--short", "--domain", "--ip-address", "--all-ip-addresses"}
        if any(token not in safe for token in lowered if token):
            return "hostname arguments that change the name are not allowed."
    elif name == "ss":
        if any(token in {"-k", "--kill"} for token in lowered):
            return "ss kill mode is not allowed."
    elif name == "resolvectl":
        if any(token.startswith(("flush-", "reset-", "set-", "revert")) for token in lowered):
            return "resolvectl state changes are not allowed."
    elif name == "sort":
        if any(_option(token) in {"-o", "--output", "--compress-program"} for token in lowered):
            return "sort output files and compressors are not allowed."
    elif name == "system_profiler":
        if any(_option(token) in {"-o", "--output"} for token in lowered):
            return "system_profiler file output is not allowed."
    elif name == "find":
        if any(token in FIND_BLOCKED for token in lowered):
            return "find actions and symlink following are not allowed."
    elif name == "systemctl":
        queries = {"status", "list-units", "list-unit-files", "is-active", "is-enabled", "is-failed", "show"}
        if any(token in SYSTEMCTL_BLOCKED for token in lowered):
            return "systemctl state-changing verbs are not allowed."
        if "--version" not in lowered and not any(token in queries for token in lowered):
            return "systemctl is limited to status, show and list queries."
        if "show" in lowered and any(token in {"--property", "-p"} for token in lowered):
            return "systemctl show property filtering is allowed, but not state changes."
    elif name == "ip":
        if any(token in IP_BLOCKED for token in lowered) or any(
            _option(token) in {"-b", "-batch", "-force"} for token in lowered
        ):
            return "ip state-changing verbs and batch mode are not allowed."
    elif name == "nmcli":
        if any(token in {"-s", "--show-secrets"} for token in lowered):
            return "nmcli secret display is not allowed."
        if any(token in NMCLI_BLOCKED for token in lowered):
            return "nmcli state-changing verbs are not allowed."
    elif name == "xrandr":
        if any(_option(token) in XRANDR_BLOCKED for token in lowered):
            return "xrandr mode/output changes are not allowed; use --query."
    elif name == "rfkill":
        if any(token in {"block", "unblock", "toggle", "soft", "hard"} for token in lowered):
            return "rfkill changes are not allowed; use 'rfkill list'."
    elif name == "upower":
        if any(token in {"--monitor", "--monitor-detail"} for token in lowered):
            return "upower monitor mode is not allowed."
    elif name == "service":
        if "--status-all" in lowered or "status" in lowered:
            if any(token in {"start", "stop", "restart", "reload", "force-reload", "try-restart"} for token in lowered):
                return "service start/stop/restart is not allowed."
        else:
            return "service is limited to status queries."
    elif name == "ifconfig":
        mutations = {
            "add",
            "arp",
            "broadcast",
            "del",
            "delete",
            "down",
            "dstaddr",
            "hw",
            "media",
            "mediaopt",
            "metric",
            "mtu",
            "netmask",
            "promisc",
            "txqueuelen",
            "tunnel",
            "up",
        }
        if any(token in mutations for token in lowered):
            return "ifconfig state-changing options are not allowed."
    elif name == "route":
        if any(token in {"add", "change", "del", "delete", "flush", "-f"} for token in lowered):
            return "route changes are not allowed."
    elif name == "arp":
        if any(token in {"-d", "-s", "-f", "delete", "set"} for token in lowered):
            return "arp changes are not allowed."
    elif name == "ipconfig":
        if any(
            token in {"/release", "/renew", "/flushdns", "/registerdns", "/setclassid", "/set"} for token in lowered
        ):
            return "ipconfig state changes are not allowed."
    elif name == "pmset":
        changes = {
            "autopoweroff",
            "displaysleep",
            "disksleep",
            "halfdim",
            "hibernate",
            "lessbright",
            "panicrestart",
            "power",
            "repeat",
            "schedule",
            "sleep",
            "sleepnow",
            "standby",
            "wake",
        }
        if _first(args) not in {"-g", "--get"} or any(token in changes for token in lowered):
            return "pmset is limited to read-only -g queries."
    elif name == "ethtool":
        if any(token in ETHTOOL_BLOCKED for token in args) or any(
            token.startswith("--") and _option(token) in ETHTOOL_BLOCKED for token in lowered
        ):
            return "ethtool state-changing options are not allowed."
    elif name == "iw":
        blocked = {
            "add",
            "connect",
            "del",
            "delete",
            "disconnect",
            "down",
            "event",
            "join",
            "leave",
            "monitor",
            "set",
            "start",
            "stop",
            "up",
        }
        if any(token in blocked for token in lowered):
            return "iw state-changing and streaming modes are not allowed."
    elif name == "smartctl":
        if any(token in SMARTCTL_BLOCKED for token in args) or any(
            token.startswith("--") and _option(token) in SMARTCTL_BLOCKED for token in lowered
        ):
            return "smartctl tests and settings changes are not allowed."
    elif name == "nvme":
        if args and _first(args) not in NVME_READ_ONLY:
            return "nvme is limited to read-only information subcommands."
    elif name == "hdparm":
        if any(token not in HDparm_ALLOWED for token in args if token.startswith("-")):
            return "hdparm is limited to read-only information flags."
    elif name == "fuser":
        if any(token in {"-i", "-k", "-K"} for token in lowered):
            return "fuser kill and interactive modes are not allowed."
    elif name == "sysctl":
        if any(token in {"-p", "--system", "-w", "--write"} for token in lowered) or any(
            "=" in token for token in args
        ):
            return "sysctl writes are not allowed; read variables only."
    elif name == "loginctl":
        allowed = {
            "list-sessions",
            "list-users",
            "session-status",
            "show-session",
            "show-seat",
            "show-user",
            "user-status",
        }
        if not args or _first(args) not in allowed:
            return "loginctl is limited to list, status and show queries."
    elif name == "timedatectl":
        allowed = {"list-timezones", "show", "show-timesync", "status", "timesync-status"}
        if args and _first(args).startswith("set-"):
            return "timedatectl state changes are not allowed."
        if args and _first(args) not in allowed:
            return "timedatectl is limited to status and list queries."
    elif name == "hostnamectl":
        allowed = {"hostname", "show", "status"}
        if args and _first(args).startswith("set-"):
            return "hostnamectl state changes are not allowed."
        if args and _first(args) not in allowed:
            return "hostnamectl is limited to status and show queries."
    elif name == "localectl":
        allowed = {
            "list-keymaps",
            "list-locales",
            "list-x11-keymap-layouts",
            "list-x11-keymap-models",
            "list-x11-keymap-options",
            "list-x11-keymap-variants",
            "show",
            "status",
        }
        if args and _first(args).startswith("set-"):
            return "localectl state changes are not allowed."
        if args and _first(args) not in allowed:
            return "localectl is limited to status and list queries."
    elif name == "networkctl":
        allowed = {"list", "lldp", "status"}
        if not args or _first(args) not in allowed:
            return "networkctl is limited to list and status queries."
    elif name == "bluetoothctl":
        allowed = {"devices", "info", "list", "paired-devices", "show"}
        if not args or _first(args) not in allowed:
            return "bluetoothctl is limited to list, show and info queries."
    elif name == "busctl":
        allowed = {"get-property", "introspect", "list", "status", "tree"}
        if not args or _first(args) not in allowed:
            return "busctl is limited to list, tree, introspect and get-property queries."
    elif name == "pactl":
        allowed = {
            "get-default-sink",
            "get-default-source",
            "get-sink-mute",
            "get-sink-volume",
            "get-source-mute",
            "get-source-volume",
            "info",
            "list",
            "stat",
        }
        if not args or _first(args) not in allowed:
            return "pactl is limited to list, info and get queries."
    elif name == "xinput":
        allowed = {"get-button-map", "list", "list-props"}
        if not args or _first(args) not in allowed:
            return "xinput is limited to list and get queries."
    elif name == "v4l2-ctl":
        if any(
            token.startswith(("--set-", "--stream-", "--overlay", "--out-device", "--in-device")) for token in lowered
        ):
            return "v4l2-ctl state changes and streaming are not allowed."
    elif name == "udevadm":
        if not args or _first(args) not in {"info"}:
            return "udevadm is limited to info queries."
    elif name == "tar":
        listing = any(
            token == "--list" or (token.startswith("-") and not token.startswith("--") and "t" in token[1:])
            for token in args
        )
        changes = any(
            token.startswith("-")
            and not token.startswith("--")
            and any(character in token[1:] for character in "crdxuA")
            for token in args
        )
        if not listing or changes or any(token in TAR_BLOCKED for token in args):
            return "tar is limited to listing archives with -t."
    elif name == "unzip":
        if not args or args[0] not in {"-l", "-t", "-v", "-Z"}:
            return "unzip is limited to listing and testing archives."
    elif name == "curl":
        blocked_options = CURL_BLOCKED | {"--cookie", "--config", "--netrc", "--netrc-file"}
        if any(_option(token) in blocked_options for token in args):
            return "curl downloads, uploads, forms, cookies and file output are not allowed."
        if any(
            token.startswith("-")
            and not token.startswith("--")
            and any(character in token[1:] for character in "oOTdFcDbX")
            for token in args
        ):
            return "curl output, upload and cookie options are not allowed."
        if any(token.startswith("@") or "=@" in token or token.startswith("-H@") for token in args):
            return "curl file references are not allowed."
        if any("://" in token and token.lower().startswith(CURL_UNSAFE_SCHEMES) for token in args):
            return "curl local-file and remote-shell protocols are not allowed."
        if any(
            token.upper() in {"PUT", "POST", "PATCH", "DELETE"}
            or token.split("=", 1)[-1].upper() in {"PUT", "POST", "PATCH", "DELETE"}
            for token in args
        ):
            return "curl is limited to read-only HTTP requests."
    elif name == "git":
        if not args or _first(args) not in GIT_READ_ONLY:
            return "git is limited to status, log, diff, show and other read-only queries."
        if any(token in GIT_BLOCKED for token in lowered):
            return "git is limited to read-only inspection."
        if _first(args) == "config":
            positionals = [token for token in args[1:] if not token.startswith("-")]
            if (
                any(
                    token
                    in {"--unset", "--unset-all", "--replace-all", "--add", "--rename-section", "--remove-section"}
                    for token in lowered
                )
                or len(positionals) >= 2
            ):
                return "git config writes are not allowed."
        if _first(args) == "branch":
            positionals = [token for token in args[1:] if not token.startswith("-")]
            if any(
                token
                in {
                    "-d",
                    "-D",
                    "-m",
                    "-M",
                    "--delete",
                    "--move",
                    "--copy",
                    "-c",
                    "--create",
                    "--set-upstream-to",
                    "--unset-upstream",
                    "--edit-description",
                }
                for token in args
            ) or (positionals and not any(token in {"--list", "-a", "-r", "--all", "--remotes"} for token in args)):
                return "git branch changes are not allowed."
        if _first(args) == "tag":
            positionals = [token for token in args[1:] if not token.startswith("-")]
            if any(
                token in {"-d", "-a", "-s", "-f", "--delete", "--annotate", "--sign", "--force"} for token in args
            ) or (positionals and not any(token in {"--list", "-l"} for token in args)):
                return "git tag changes are not allowed."
        if _first(args) == "remote":
            positionals = [token for token in args[1:] if not token.startswith("-")]
            if positionals and positionals[0] in {
                "add",
                "remove",
                "rename",
                "set-head",
                "set-branches",
                "set-url",
                "prune",
                "update",
            }:
                return "git remote changes are not allowed."
    return None


def _pipeline(tokens: list[str]) -> list[list[str]] | str:
    segments = _split_pipeline(tokens)
    if isinstance(segments, str):
        return segments
    for segment in segments:
        error = _validate_segment(segment)
        if error:
            return error
    return segments


def _run_stage(command: list[str], timeout: float, previous: str | None) -> subprocess.CompletedProcess[str]:
    options: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "timeout": timeout,
        "check": False,
        "env": {**os.environ, "LC_ALL": "C", "LANG": "C"},
    }
    if previous is None:
        options["stdin"] = subprocess.DEVNULL
    else:
        options["input"] = previous
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(command, **options)


def run_read_only(command: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Run one diagnostic command (or a small pipeline) without a shell."""
    command = (command or "").strip()
    if not command:
        return _denied(command, "No command was provided.")
    if len(command) > MAX_COMMAND_LENGTH:
        return _denied(command, f"Command is longer than {MAX_COMMAND_LENGTH} characters.")
    if "\n" in command or "\r" in command or "\x00" in command:
        return _denied(command, "Command must be a single line.")

    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as error:
        return _denied(command, f"Command could not be parsed: {error}")

    segments = _pipeline(tokens)
    if isinstance(segments, str):
        return _denied(command, segments)

    resolved: list[list[str]] = []
    for segment in segments:
        executable = shutil.which(segment[0])
        if not executable:
            return _denied(command, f"Command {segment[0]!r} was not found on this system.")
        resolved.append([executable, *segment[1:]])

    previous: str | None = None
    stderr_notes: list[str] = []
    for stage in resolved:
        try:
            completed = _run_stage(stage, timeout, previous)
        except subprocess.TimeoutExpired:
            return {
                "command": command,
                "allowed": True,
                "exit_code": None,
                "output": "",
                "reason": f"Command timed out after {timeout:g}s.",
            }
        except OSError as error:
            return {
                "command": command,
                "allowed": True,
                "exit_code": None,
                "output": "",
                "reason": f"Command could not start: {error}",
            }
        previous = completed.stdout or ""
        if completed.stderr:
            stderr_notes.append(completed.stderr.strip())
        if completed.returncode != 0:
            combined = previous
            if stderr_notes:
                combined = (combined + "\n[stderr]\n" + "\n".join(stderr_notes)).strip()
            return {
                "command": command,
                "allowed": True,
                "exit_code": completed.returncode,
                "output": _cap(combined),
                "reason": f"Command exited with code {completed.returncode}.",
            }

    output = previous or ""
    if stderr_notes:
        output = (output + "\n[stderr]\n" + "\n".join(stderr_notes)).strip()
    return {
        "command": command,
        "allowed": True,
        "exit_code": 0,
        "output": _cap(output),
        "reason": None,
    }
