from __future__ import annotations

import pytest

from missus_tom.models.dependencies import DependencyStatus
from missus_tom.models.preflight import CheckStatus, PreflightCheck
from missus_tom.services import preflight
from missus_tom.services.resources import GIB, HostResources, StorageInspection


def test_system_preflight_excludes_container_runtime_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        preflight,
        "inspect_host_resources",
        lambda: HostResources(8, 16 * GIB, 8 * GIB),
    )
    monkeypatch.setattr(
        preflight,
        "inspect_storage",
        lambda path: StorageInspection(
            path=str(path),
            filesystem_type="ext4",
            free_bytes=50 * GIB,
            total_bytes=100 * GIB,
            host_free_bytes=None,
            measurement="linux",
            warning=None,
        ),
    )
    monkeypatch.setattr(
        preflight,
        "_version_check",
        lambda check_id, label, *args, **kwargs: PreflightCheck(
            check_id=check_id,
            label=label,
            status=CheckStatus.PASSED,
            message="ok",
        ),
    )
    monkeypatch.setattr(
        preflight.dependency_installer,
        "status",
        lambda pipeline_identifier: DependencyStatus(
            pipeline_identifier=pipeline_identifier,
            requirements=[],
            installable=True,
        ),
    )

    result = preflight.system_preflight()
    check_ids = {check.check_id for check in result.checks}

    assert "docker" not in check_ids
    assert "apptainer" not in check_ids
    assert "disk_state" in check_ids
    assert "disk_home" in check_ids
    disk_home = next(check for check in result.checks if check.check_id == "disk_home")
    assert "measurement=linux" in disk_home.message
