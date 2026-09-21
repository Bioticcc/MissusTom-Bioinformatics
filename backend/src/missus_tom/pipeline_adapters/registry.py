from __future__ import annotations

from collections.abc import Iterable

from missus_tom.models.manifest import ProjectManifest
from missus_tom.pipeline_adapters.base import PipelineAdapter
from missus_tom.pipeline_adapters.bulk_rnaseq import BulkRnaSeqAdapter
from missus_tom.pipeline_adapters.ont_analysis import OntAnalysisAdapter


class PipelineRegistry:
    def __init__(self, adapters: Iterable[PipelineAdapter]) -> None:
        self._adapters = {adapter.pipeline_identifier: adapter for adapter in adapters}
        if not self._adapters:
            raise ValueError("at least one pipeline adapter is required")

    def get(self, pipeline_identifier: str) -> PipelineAdapter:
        try:
            return self._adapters[pipeline_identifier]
        except KeyError as exc:
            raise ValueError(f"unsupported pipeline identifier: {pipeline_identifier}") from exc

    def for_manifest(self, manifest: ProjectManifest) -> PipelineAdapter:
        return self.get(manifest.pipeline_identifier)

    def all(self) -> list[PipelineAdapter]:
        return list(self._adapters.values())


def default_pipeline_registry() -> PipelineRegistry:
    return PipelineRegistry([BulkRnaSeqAdapter(), OntAnalysisAdapter()])
