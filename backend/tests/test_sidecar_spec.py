from __future__ import annotations

import runpy
import sys
from pathlib import Path
from types import ModuleType

import pytest


def test_sidecar_spec_resolves_source_paths_from_spec_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_calls: list[tuple[list[str], dict[str, object]]] = []

    class FakeAnalysis:
        def __init__(self, scripts: list[str], **common: object) -> None:
            analysis_calls.append((scripts, common))
            self.pure: list[object] = []
            self.scripts: list[object] = []
            self.binaries: list[object] = []
            self.zipfiles: list[object] = []
            self.datas: list[object] = []

    class FakePYZ:
        def __init__(self, _: list[object]) -> None:
            pass

    def fake_exe(*_: object, **__: object) -> None:
        pass

    pyinstaller = ModuleType("PyInstaller")
    pyinstaller.__path__ = []
    building = ModuleType("PyInstaller.building")
    building.__path__ = []
    build_main = ModuleType("PyInstaller.building.build_main")
    build_main.Analysis = FakeAnalysis
    build_main.EXE = fake_exe
    build_main.PYZ = FakePYZ
    monkeypatch.setitem(sys.modules, "PyInstaller", pyinstaller)
    monkeypatch.setitem(sys.modules, "PyInstaller.building", building)
    monkeypatch.setitem(sys.modules, "PyInstaller.building.build_main", build_main)

    resource_stage = tmp_path / "resources"
    resource_stage.mkdir()
    monkeypatch.setenv("MISSUS_TOM_SIDECAR_TARGET", "x86_64-unknown-linux-gnu")
    monkeypatch.setenv("MISSUS_TOM_SIDECAR_RESOURCE_STAGE", str(resource_stage))
    repository_root = Path(__file__).resolve().parents[2]
    spec = repository_root / "backend" / "packaging" / "missus_tom_sidecars.spec"

    runpy.run_path(str(spec), init_globals={"SPECPATH": str(spec.parent)})

    source_root = repository_root / "backend" / "src"
    assert [scripts for scripts, _ in analysis_calls] == [
        [str(source_root / "missus_tom" / "main.py")],
        [str(source_root / "missus_tom" / "ont_runner.py")],
    ]
    assert all(common["pathex"] == [str(source_root)] for _, common in analysis_calls)
