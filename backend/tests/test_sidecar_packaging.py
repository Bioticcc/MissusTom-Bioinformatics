from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


def _copy_build_script(tmp_path: Path) -> tuple[Path, Path]:
    repository_root = tmp_path / "repository"
    script = repository_root / "scripts" / "build-linux-sidecars.sh"
    script.parent.mkdir(parents=True)
    source = Path(__file__).resolve().parents[2] / "scripts" / "build-linux-sidecars.sh"
    shutil.copy2(source, script)
    return repository_root, script


def _fake_python(path: Path, import_succeeds: bool = False) -> None:
    path.parent.mkdir(parents=True)
    import_exit_code = "0" if import_succeeds else "1"
    path.write_text(
        "#!/usr/bin/env bash\n"
        'printf \'%s\\n\' "$0" "$@" >> "${MISSUS_TOM_SIDECAR_TEST_LOG}"\n'
        'if [[ "$1" == "-c" && "$2" == "import PyInstaller" ]]; then\n'
        f"  exit {import_exit_code}\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _run_script(
    script: Path, cwd: Path, environment: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        cwd=cwd,
        env=os.environ | environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_sidecar_build_defaults_to_backend_venv_and_stops_without_pyinstaller(
    tmp_path: Path,
) -> None:
    repository_root, script = _copy_build_script(tmp_path)
    python = repository_root / "backend" / ".venv" / "bin" / "python"
    invocation_log = tmp_path / "default-python.log"
    _fake_python(python)

    result = _run_script(
        script,
        tmp_path,
        {"MISSUS_TOM_SIDECAR_TEST_LOG": str(invocation_log)},
    )

    assert result.returncode == 1
    assert f"PyInstaller is not installed for {python}" in result.stderr
    assert invocation_log.read_text(encoding="utf-8").splitlines() == [
        str(python),
        "-c",
        "import PyInstaller",
    ]
    assert not (repository_root / "backend" / "build").exists()


def test_sidecar_build_resolves_relative_python_override_before_changing_directory(
    tmp_path: Path,
) -> None:
    repository_root, script = _copy_build_script(tmp_path)
    launch_directory = tmp_path / "launch"
    launch_directory.mkdir()
    python = launch_directory / "relative" / "python"
    invocation_log = tmp_path / "override-python.log"
    _fake_python(python)

    result = _run_script(
        script,
        launch_directory,
        {
            "MISSUS_TOM_SIDECAR_PYTHON": "relative/python",
            "MISSUS_TOM_SIDECAR_TEST_LOG": str(invocation_log),
        },
    )

    assert result.returncode == 1
    assert f"PyInstaller is not installed for {python}" in result.stderr
    assert invocation_log.read_text(encoding="utf-8").splitlines()[0] == str(python)
    assert not (repository_root / "backend" / "build").exists()


def test_sidecar_build_invokes_pyinstaller_through_checked_interpreter(tmp_path: Path) -> None:
    repository_root, script = _copy_build_script(tmp_path)
    python = repository_root / "backend" / ".venv" / "bin" / "python"
    invocation_log = tmp_path / "pyinstaller-python.log"
    _fake_python(python, import_succeeds=True)
    (repository_root / "workflows").mkdir()
    resource_script = repository_root / "scripts" / "build-analysis-image.sh"
    resource_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    result = _run_script(
        script,
        tmp_path,
        {"MISSUS_TOM_SIDECAR_TEST_LOG": str(invocation_log)},
    )

    assert result.returncode == 1
    assert invocation_log.read_text(encoding="utf-8").splitlines() == [
        str(python),
        "-c",
        "import PyInstaller",
        str(python),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(repository_root / "backend" / "dist" / "sidecars"),
        "--workpath",
        str(repository_root / "backend" / "build" / "pyinstaller"),
        str(repository_root / "backend" / "packaging" / "missus_tom_sidecars.spec"),
    ]
    assert not (repository_root / "desktop" / "src-tauri" / "binaries").exists()


def test_sidecar_build_reports_missing_python_before_staging_resources(tmp_path: Path) -> None:
    repository_root, script = _copy_build_script(tmp_path)
    missing_python = tmp_path / "missing" / "python"

    result = _run_script(
        script,
        tmp_path,
        {"MISSUS_TOM_SIDECAR_PYTHON": str(missing_python)},
    )

    assert result.returncode == 1
    assert f"executable backend Python interpreter at {missing_python}" in result.stderr
    assert not (repository_root / "backend" / "build").exists()
