import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from missus_tom.pipeline_adapters import ont_analysis
from missus_tom.services import dependencies, preflight


def test_ont_execution_checks_r_libraries_in_pipeline_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = {"PATH": "/managed/ont/bin"}
    monkeypatch.setattr(ont_analysis, "runtime_tool", lambda *_: "/managed/ont/bin/tool")
    monkeypatch.setattr(ont_analysis, "runtime_environment", lambda _: environment)
    run = Mock(return_value=SimpleNamespace(returncode=1))
    monkeypatch.setattr(ont_analysis.subprocess, "run", run)

    assert ont_analysis.OntAnalysisAdapter.missing_runtime_tools() == ["required ONT R packages"]
    assert run.call_args.kwargs["env"] == environment
    assert "requireNamespace" in run.call_args.args[0][-1]
    assert "rtracklayer" in run.call_args.args[0][-1]


def test_preflight_uses_resolved_pipeline_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    environment = {"PATH": "/managed/bulk/bin"}
    monkeypatch.setattr(preflight, "runtime_tool", lambda *_: "/managed/bulk/bin/nextflow")
    monkeypatch.setattr(preflight, "runtime_environment", lambda _: environment)
    run = Mock(return_value=SimpleNamespace(returncode=0, stdout="24.04.4", stderr=""))
    monkeypatch.setattr(preflight.subprocess, "run", run)

    result = preflight._version_check(
        "nextflow", "Nextflow", "nextflow", ["-version"], optional=True
    )
    assert result.status.value == "passed"
    assert run.call_args.args[0] == ["/managed/bulk/bin/nextflow", "-version"]
    assert run.call_args.kwargs["env"] == environment


def test_runtime_environment_excludes_host_runtime_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("PATH", "/custom/bin")
    for key in (
        "R_HOME",
        "R_LIBS",
        "R_LIBS_SITE",
        "R_LIBS_USER",
        "R_DEFAULT_PACKAGES",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "CONDA_PREFIX",
        "JAVA_HOME",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
    ):
        monkeypatch.setenv(key, f"/host/{key.lower()}")

    environment = dependencies.runtime_environment("ont-analysis")
    assert environment["PATH"] == (
        f"{tmp_path / 'dependencies/ont-analysis/environment/bin'}:/usr/bin:/bin"
    )
    assert environment["R_LIBS_USER"] == str(
        tmp_path / "dependencies/ont-analysis/environment/lib/R/library"
    )
    assert environment["LD_LIBRARY_PATH"] == str(
        tmp_path / "dependencies/ont-analysis/environment/lib"
    )
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["R_ENVIRON_USER"] == os.devnull
    assert environment["R_PROFILE_USER"] == os.devnull
    assert environment["R_LIBS_SITE"] == str(
        tmp_path / "dependencies/ont-analysis/environment/lib/R/site-library"
    )
    for key in (
        "R_HOME",
        "R_LIBS",
        "R_DEFAULT_PACKAGES",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONUSERBASE",
        "CONDA_PREFIX",
        "JAVA_HOME",
        "LD_PRELOAD",
    ):
        assert key not in environment
    assert (
        dependencies._environment_for_prefix(
            "ont-analysis", tmp_path / "dependencies/ont-analysis/environment"
        )
        == environment
    )


def test_runtime_tool_never_falls_back_to_system_or_escaping_symlink(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    system_bin = tmp_path / "system-bin"
    system_bin.mkdir()
    system_tool = system_bin / "samtools"
    system_tool.write_text("#!/bin/sh\n", encoding="utf-8")
    system_tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(system_bin))

    root = tmp_path / "dependencies/ont-analysis"
    prefix = root / "environments/generation/environment"
    managed_bin = prefix / "bin"
    managed_bin.mkdir(parents=True)
    (root / "active.json").write_text(
        json.dumps({"environment": "environments/generation/environment"}), encoding="utf-8"
    )

    assert dependencies.runtime_tool("samtools", "ont-analysis") is None

    managed_tool = managed_bin / "samtools"
    managed_tool.symlink_to(system_tool)
    assert dependencies.runtime_tool("samtools", "ont-analysis") is None

    managed_tool.unlink()
    managed_tool.write_text("#!/bin/sh\n", encoding="utf-8")
    managed_tool.chmod(0o755)
    assert dependencies.runtime_tool("samtools", "ont-analysis") == str(managed_tool)


def test_runtime_tool_allows_dorado_link_within_managed_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    root = tmp_path / "dependencies/ont-analysis"
    prefix = root / "environments/generation/environment"
    managed_bin = prefix / "bin"
    managed_bin.mkdir(parents=True)
    (root / "active.json").write_text(
        json.dumps({"environment": "environments/generation/environment"}), encoding="utf-8"
    )
    dorado_distribution = prefix.parent / "dorado/dorado-2.1.2-linux-x64/bin"
    dorado_distribution.mkdir(parents=True)
    (dorado_distribution.parent / "lib").mkdir()
    dorado_executable = dorado_distribution / "dorado"
    dorado_executable.write_text("#!/bin/sh\n", encoding="utf-8")
    dorado_executable.chmod(0o755)
    (managed_bin / "dorado").symlink_to(os.path.relpath(dorado_executable, managed_bin))

    assert dependencies.runtime_tool("dorado", "ont-analysis") == str(managed_bin / "dorado")
    assert dependencies.runtime_environment("ont-analysis")["LD_LIBRARY_PATH"] == os.pathsep.join(
        (str(prefix / "lib"), str(dorado_distribution.parent / "lib"))
    )


def test_docker_remains_an_explicit_system_prerequisite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(dependencies.shutil, "which", lambda name: f"/system/bin/{name}")
    assert dependencies.runtime_tool("docker", "bulk-rnaseq") == "/system/bin/docker"
