from fieldnote import commands


def test_runs_simple_read_only_command():
    result = commands.run_read_only("uname -s")
    assert result["allowed"] is True
    assert result["exit_code"] == 0
    assert "Linux" in result["output"]


def test_runs_read_only_pipeline():
    result = commands.run_read_only("cat /proc/version | grep -i linux")
    assert result["allowed"] is True
    assert result["exit_code"] == 0
    assert "linux" in result["output"].lower()


def test_denies_shell_operators():
    result = commands.run_read_only("uname -s; id")
    assert result["allowed"] is False
    assert "metacharacters" in result["reason"]


def test_denies_destructive_executables():
    for command in ("rm -rf /", "mv /tmp/a /tmp/b", "cp /tmp/a /tmp/b", "touch /tmp/new"):
        result = commands.run_read_only(command)
        assert result["allowed"] is False
        assert "blocked" in result["reason"]


def test_denies_privilege_escalation():
    result = commands.run_read_only("sudo cat /sys/class/drm/card0/status")
    assert result["allowed"] is False


def test_denies_sensitive_paths():
    assert commands.run_read_only("cat /etc/shadow")["allowed"] is False
    assert commands.run_read_only("cat /sys/../etc/shadow")["allowed"] is False
    assert commands.run_read_only("cat /proc/self/environ")["allowed"] is False
    assert commands.run_read_only("cat .env")["allowed"] is False
    assert commands.run_read_only("cat ~/.ssh/id_rsa")["allowed"] is False
    assert commands.run_read_only("ls /root")["allowed"] is False


def test_allows_general_read_only_paths(tmp_path):
    note = tmp_path / "diagnostic.log"
    note.write_text("adapter present\n", encoding="utf-8")
    result = commands.run_read_only(f"cat {note}")
    assert result["allowed"] is True
    assert "adapter present" in result["output"]


def test_denies_state_changes():
    assert commands.run_read_only("systemctl restart ssh")["allowed"] is False
    assert commands.run_read_only("ip link set wlo1 down")["allowed"] is False
    assert commands.run_read_only("xrandr --output HDMI-1 --off")["allowed"] is False


def test_denies_find_actions():
    result = commands.run_read_only("find /sys -exec rm {} ;")
    assert result["allowed"] is False


def test_reports_missing_executable(monkeypatch):
    monkeypatch.setattr(commands.shutil, "which", lambda name: None)
    result = commands.run_read_only("uname -s")
    assert result["allowed"] is False
    assert "not found" in result["reason"]


def test_uses_existing_display_evidence():
    result = commands.run_read_only("ls /sys/class/drm")
    assert result["allowed"] is True
    assert result["exit_code"] == 0


def test_denies_other_state_changes():
    assert commands.run_read_only("date -s 2026-01-01")["allowed"] is False
    assert commands.run_read_only("hostname new-name")["allowed"] is False
    assert commands.run_read_only("sort -o /sys/class/drm/out")["allowed"] is False
    assert commands.run_read_only("ss -K")["allowed"] is False
    assert commands.run_read_only("resolvectl flush-caches")["allowed"] is False


def test_allows_journal_and_service_queries():
    assert commands.run_read_only("journalctl -b")["allowed"] is True
    assert commands.run_read_only("journalctl -k -n 1")["allowed"] is True
    assert commands.run_read_only("systemctl status ssh")["allowed"] is True
    assert commands.run_read_only("systemctl show ssh")["allowed"] is True


def test_denies_mutating_subcommands():
    assert commands.run_read_only("journalctl --vacuum-size=1G")["allowed"] is False
    assert commands.run_read_only("nmcli connection show --show-secrets")["allowed"] is False
    assert commands.run_read_only("sysctl -w kernel.hostname=test")["allowed"] is False
    assert commands.run_read_only("git checkout main")["allowed"] is False
    assert commands.run_read_only("git config user.name value")["allowed"] is False


def test_denies_interpreters_and_downloads():
    assert commands.run_read_only("python3 -c 'print(1)'")["allowed"] is False
    assert commands.run_read_only("bash -c uname")["allowed"] is False
    assert commands.run_read_only("wget http://example.com")["allowed"] is False
    assert commands.run_read_only("curl -o /tmp/page http://example.com")["allowed"] is False


def test_allows_read_only_git_and_curl():
    assert commands.run_read_only("git status --porcelain")["allowed"] is True
    assert commands.run_read_only("git branch -a")["allowed"] is True
    assert commands.run_read_only("curl --version")["allowed"] is True


def test_tar_only_lists_archives():
    assert commands.run_read_only("tar -tf /tmp/missing.tar")["allowed"] is True
    assert commands.run_read_only("tar -ctf /tmp/new.tar /tmp")["allowed"] is False


def test_file_readers_cannot_open_raw_disks():
    assert commands.run_read_only("cat /dev/nvme0")["allowed"] is False
