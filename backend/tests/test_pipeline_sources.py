from __future__ import annotations

import stat

import pytest

from missus_tom.services.pipeline_sources import PipelineSourceService


@pytest.mark.parametrize("pipeline_identifier", ["bulk-rnaseq", "ont-analysis"])
def test_start_here_guide_is_first(
    pipeline_identifier: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    status = PipelineSourceService().status(pipeline_identifier)
    assert status.files[0].path == "START_HERE.md"
    assert status.files[0].language == "markdown"


def test_custom_revision_never_changes_official_source(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    service = PipelineSourceService()
    official = service.read("bulk-rnaseq", "main.nf")

    revision = service.save("bulk-rnaseq", "main.nf", "// harmless custom source\n", None)
    active = service.activate("bulk-rnaseq", revision.revision_id)

    assert active.source_type == "custom"
    assert service.read("bulk-rnaseq", "main.nf").content == "// harmless custom source\n"
    assert (
        service.official_root("bulk-rnaseq").joinpath("main.nf").read_text(encoding="utf-8")
        == official.content
    )
    assert service.restore("bulk-rnaseq").source_type == "official"


def test_saving_executable_script_preserves_execution_permission(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    service = PipelineSourceService()

    revision = service.save("bulk-rnaseq", "bin/bulk_rnaseq_analysis.R", "", None)
    saved = (
        service._revision_root("bulk-rnaseq", revision.revision_id)
        / "bin"
        / "bulk_rnaseq_analysis.R"
    )

    assert stat.S_IMODE(saved.stat().st_mode) == 0o700


@pytest.mark.parametrize("path", ["../main.nf", "/etc/passwd", "revision.json"])
def test_source_paths_are_allowlisted(tmp_path, monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    monkeypatch.setenv("MISSUS_TOM_STATE_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        PipelineSourceService().read("bulk-rnaseq", path)
