from fieldnote import collector


def test_dns_check_resolves_localhost():
    result = collector.dns_check("localhost")
    assert result == {"hostname": "localhost", "resolved": True}


def test_dns_check_reports_failure():
    result = collector.dns_check("nonexistent.invalid")
    assert result == {"hostname": "nonexistent.invalid", "resolved": False}


def test_dns_check_without_hostname():
    assert collector.dns_check(None) is None


def test_collect_system_shape():
    evidence = collector.collect_system()
    assert evidence["os"] in {"Windows", "Linux", "macOS"}
    assert evidence["cpu_count"] is not None
    assert isinstance(evidence["memory"], dict)
    assert evidence["memory"]["total_gib"] > 0
    assert isinstance(evidence["disks"], list)
    assert isinstance(evidence["network"], dict)
    assert isinstance(evidence["network"]["interfaces"], list)


def test_windows_evidence_is_merged(monkeypatch):
    monkeypatch.setattr(collector.platform, "system", lambda: "Windows")
    monkeypatch.setattr(collector, "_interfaces", lambda: [])
    monkeypatch.setattr(
        collector,
        "_windows_evidence",
        lambda: {
            "system_events": [{"id": 41, "provider": "Kernel-Power"}],
            "default_routes": [{"InterfaceAlias": "Wi-Fi", "NextHop": "192.168.1.1"}],
        },
    )
    evidence = collector.collect_system()
    assert evidence["os"] == "Windows"
    assert evidence["windows"]["system_events"][0]["id"] == 41
    assert evidence["network"]["routes"][0]["InterfaceAlias"] == "Wi-Fi"


def test_pseudo_filesystems_are_filtered(monkeypatch):
    class Partition:
        def __init__(self, mountpoint, fstype):
            self.mountpoint = mountpoint
            self.fstype = fstype

    class Usage:
        total = 10 * 1024**3
        free = 5 * 1024**3
        percent = 50

    monkeypatch.setattr(
        collector.psutil,
        "disk_partitions",
        lambda all=False: [Partition("/", "ext4"), Partition("/snap/thing", "squashfs")],
    )
    monkeypatch.setattr(collector.psutil, "disk_usage", lambda mount: Usage())
    evidence = collector.collect_system()
    assert [disk["mount"] for disk in evidence["disks"]] == ["/"]
