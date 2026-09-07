from __future__ import annotations

from types import SimpleNamespace

from missus_tom.services.resource_monitor import ResourceMonitor
from missus_tom.services.resources import GIB, HostResources


def _host(*, total_gib: int = 64, available_gib: float = 32) -> HostResources:
    return HostResources(
        logical_cpus=8,
        total_memory_bytes=total_gib * GIB,
        available_memory_bytes=int(available_gib * GIB),
    )


def test_returns_reason_after_three_consecutive_ram_breaches(tmp_path) -> None:
    monitor = ResourceMonitor(
        tmp_path / "project",
        host_inspector=lambda: _host(available_gib=0.4),
        disk_usage_inspector=lambda _: SimpleNamespace(free=20 * GIB),
    )

    assert monitor.check() is None
    assert monitor.check() is None
    reason = monitor.check()

    assert reason is not None
    assert "available RAM" in reason
    assert "output filesystem" not in reason


def test_returns_reason_after_three_consecutive_disk_breaches(tmp_path) -> None:
    monitor = ResourceMonitor(
        tmp_path / "project",
        host_inspector=_host,
        disk_usage_inspector=lambda _: SimpleNamespace(free=GIB // 2),
    )

    assert monitor.check() is None
    assert monitor.check() is None
    reason = monitor.check()

    assert reason is not None
    assert "output filesystem free space" in reason
    assert "below 1.0 GiB" in reason


def test_recovery_resets_unhealthy_sample_count(tmp_path) -> None:
    samples = iter(
        [
            _host(available_gib=0.4),
            _host(available_gib=0.4),
            _host(available_gib=8),
            _host(available_gib=0.4),
            _host(available_gib=0.4),
            _host(available_gib=0.4),
        ]
    )
    monitor = ResourceMonitor(
        tmp_path / "project",
        host_inspector=lambda: next(samples),
        disk_usage_inspector=lambda _: SimpleNamespace(free=20 * GIB),
    )

    assert [monitor.check() for _ in range(5)] == [None, None, None, None, None]
    assert monitor.check() is not None


def test_unknown_or_failed_metrics_do_not_trigger_or_preserve_a_breach(tmp_path) -> None:
    samples = iter(
        [
            _host(available_gib=0.4),
            _host(available_gib=0.4),
            HostResources(logical_cpus=8, total_memory_bytes=None, available_memory_bytes=None),
            _host(available_gib=0.4),
        ]
    )
    monitor = ResourceMonitor(
        tmp_path / "project",
        host_inspector=lambda: next(samples),
        disk_usage_inspector=lambda _: (_ for _ in ()).throw(OSError("unavailable")),
    )

    assert [monitor.check() for _ in range(4)] == [None, None, None, None]


def test_probe_errors_are_safe(tmp_path) -> None:
    def failed_host_probe() -> HostResources:
        raise OSError("unavailable")

    def failed_disk_probe(_):
        raise OSError("unavailable")

    monitor = ResourceMonitor(
        tmp_path / "project",
        host_inspector=failed_host_probe,
        disk_usage_inspector=failed_disk_probe,
    )

    assert [monitor.check() for _ in range(4)] == [None, None, None, None]
