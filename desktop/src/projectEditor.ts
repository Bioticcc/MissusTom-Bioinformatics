import type { BulkReferenceMode, BulkStrandedness, Comparison, FigureConfiguration, ProjectManifest, ProposedSample, RunStartStage } from "./types";

export interface EditorOptions {
  organism: string;
  referenceGenome: string;
  annotationSource: string;
  transcriptomeFasta: string;
  annotationGtf: string;
  transcriptToGene: string;
  kallistoIndex: string;
  referenceMode: BulkReferenceMode;
  referenceFasta: string;
  referenceFai: string;
  minimap2Index: string;
  gencodeGff3: string;
  cpgIslands: string;
  ccreTable: string;
  intergenicBed: string;
  ontInstrumentReport: string;
  libraryType: string;
  strandedness: BulkStrandedness;
  executionProfile: "local" | "docker" | "apptainer";
  cpus: number;
  memoryGb: number;
  maxParallelTasks: number;
  minimumReadLength: number;
  trimQuality: number;
  adapterR1: string;
  adapterR2: string;
  minimumGroupSize: number;
  adjustedPValue: number;
  absoluteLog2FoldChange: number;
  experimentalDesignType: "independent" | "paired";
  adjustForBatchEffects: boolean;
  coverageWindowSize: number;
  modkitFilterPercentile: number;
  modkitMaxDepth: number;
  explorationMinValidCoverage: number;
  explorationMinFeatureCpgs: number;
}

const editableResources = new Set([
  "transcriptome_fasta", "annotation_gtf", "transcript_to_gene", "kallisto_index",
  "reference_fasta", "reference_fai", "minimap2_index", "gencode_gff3",
  "cpg_islands", "ccre_table", "intergenic_bed", "ont_instrument_report",
]);

const editableParameters = new Set([
  "start_stage", "coverage_window_size", "methylation_window_size", "modkit_filter_percentile",
  "modkit_max_depth", "exploration_min_valid_coverage", "exploration_min_feature_cpgs",
  "expected_pass_bam_count", "adapter_r1", "adapter_r2", "trim_quality",
  "trim_minimum_length", "differential_expression", "minimum_group_size",
  "adjusted_p_value", "absolute_log2_fold_change",
  "experimental_design_type",
  "adjust_for_batch_effects",
]);

function numberOr(value: ProjectManifest["parameters"][string], fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function stringOr(value: ProjectManifest["parameters"][string], fallback: string): string {
  return typeof value === "string" ? value : fallback;
}

export function loadProjectEditor(manifest: ProjectManifest, defaults: EditorOptions): {
  details: { projectName: string; inputDirectory: string; outputDirectory: string };
  options: EditorOptions;
  samples: ProposedSample[];
  comparisons: Comparison[];
  figureConfiguration: FigureConfiguration;
  startStage: RunStartStage;
} {
  const resources = manifest.reference_resources;
  const parameters = manifest.parameters;
  return {
    details: {
      projectName: manifest.project_name,
      inputDirectory: manifest.input_directory,
      outputDirectory: manifest.output_directory,
    },
    options: {
      ...defaults,
      organism: manifest.organism,
      referenceGenome: manifest.reference_genome,
      annotationSource: manifest.annotation_source,
      transcriptomeFasta: resources.transcriptome_fasta ?? "",
      annotationGtf: resources.annotation_gtf ?? "",
      transcriptToGene: resources.transcript_to_gene ?? "",
      kallistoIndex: resources.kallisto_index ?? "",
      referenceMode: manifest.reference_mode ?? (resources.kallisto_index ? "existing-index" : "build"),
      referenceFasta: resources.reference_fasta ?? "",
      referenceFai: resources.reference_fai ?? "",
      minimap2Index: resources.minimap2_index ?? "",
      gencodeGff3: resources.gencode_gff3 ?? "",
      cpgIslands: resources.cpg_islands ?? "",
      ccreTable: resources.ccre_table ?? "",
      intergenicBed: resources.intergenic_bed ?? "",
      ontInstrumentReport: resources.ont_instrument_report ?? "",
      libraryType: manifest.library_type,
      strandedness: manifest.strandedness === "unknown" ? defaults.strandedness : manifest.strandedness,
      executionProfile: manifest.execution_profile,
      cpus: manifest.resource_profile.cpus,
      memoryGb: manifest.resource_profile.memory_gb,
      maxParallelTasks: manifest.resource_profile.max_parallel_tasks,
      minimumReadLength: numberOr(parameters.trim_minimum_length, defaults.minimumReadLength),
      trimQuality: numberOr(parameters.trim_quality, defaults.trimQuality),
      adapterR1: stringOr(parameters.adapter_r1, defaults.adapterR1),
      adapterR2: stringOr(parameters.adapter_r2, defaults.adapterR2),
      minimumGroupSize: numberOr(parameters.minimum_group_size, defaults.minimumGroupSize),
      adjustedPValue: numberOr(parameters.adjusted_p_value, defaults.adjustedPValue),
      absoluteLog2FoldChange: numberOr(parameters.absolute_log2_fold_change, defaults.absoluteLog2FoldChange),
      experimentalDesignType: parameters.experimental_design_type === "paired" ? "paired" : "independent",
      adjustForBatchEffects: parameters.adjust_for_batch_effects === true,
      coverageWindowSize: numberOr(parameters.coverage_window_size, defaults.coverageWindowSize),
      modkitFilterPercentile: numberOr(parameters.modkit_filter_percentile, defaults.modkitFilterPercentile),
      modkitMaxDepth: numberOr(parameters.modkit_max_depth, defaults.modkitMaxDepth),
      explorationMinValidCoverage: numberOr(parameters.exploration_min_valid_coverage, defaults.explorationMinValidCoverage),
      explorationMinFeatureCpgs: numberOr(parameters.exploration_min_feature_cpgs, defaults.explorationMinFeatureCpgs),
    },
    samples: manifest.samples.map((sample) => ({
      ...sample,
      r1_files: [...sample.r1_files],
      r2_files: [...sample.r2_files],
      ont_bam_files: [...sample.ont_bam_files],
      covariates: { ...sample.covariates },
      lanes: [],
      pairing_status: sample.abundance_tsv ? "quantified" : sample.r2_files.length ? "paired" : "single",
      warnings: [],
    })),
    comparisons: manifest.comparisons.map((comparison) => ({ ...comparison })),
    figureConfiguration: manifest.figure_configuration ?? { version: 1, custom_figures: [] },
    startStage: parameters.start_stage === "analysis" ? "analysis" : "quantification",
  };
}

export function preserveExistingProject(original: ProjectManifest, edited: ProjectManifest): ProjectManifest {
  const samePipeline = original.pipeline_identifier === edited.pipeline_identifier;
  const referenceResources = samePipeline
    ? Object.fromEntries([
      ...Object.entries(original.reference_resources).filter(([key]) => !editableResources.has(key)),
      ...Object.entries(edited.reference_resources),
    ])
    : edited.reference_resources;
  const unchangedReferences = Object.keys(referenceResources).length === Object.keys(original.reference_resources).length
    && Object.entries(referenceResources).every(([key, value]) => original.reference_resources[key] === value);
  return {
    ...original,
    ...edited,
    project_identifier: original.project_identifier,
    created_at: original.created_at,
    reference_resources: referenceResources,
    reference_provenance: unchangedReferences ? original.reference_provenance : null,
    parameters: samePipeline
      ? { ...Object.fromEntries(Object.entries(original.parameters).filter(([key]) => !editableParameters.has(key))), ...edited.parameters }
      : edited.parameters,
    pipeline_status: "draft",
  };
}
