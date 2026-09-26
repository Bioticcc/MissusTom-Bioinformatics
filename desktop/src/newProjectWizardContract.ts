import type { Comparison, ProjectManifest, RunStartStage } from "./types";

export const BULK_MANIFEST_SCHEMA_VERSION = "1.1.0" as const;
export const BULK_PIPELINE_VERSION = "0.5.0" as const;
export const ONT_MANIFEST_SCHEMA_VERSION = "1.0.0" as const;
export const ONT_PIPELINE_VERSION = "0.1.0" as const;

export type BulkReferenceMode = "build" | "existing-index";
export type BulkStrandedness = "unstranded" | "forward" | "reverse";

export const DEFAULT_ADAPTER_R1 = "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA";
export const DEFAULT_ADAPTER_R2 = "AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT";

export const STRANDEDNESS_UI_OPTIONS: ReadonlyArray<{
  value: BulkStrandedness;
  label: string;
  mappingNote: string;
}> = [
  {
    value: "unstranded",
    label: "Unstranded",
    mappingNote: "Recorded as unstranded; Kallisto runs without a strandedness flag.",
  },
  {
    value: "forward",
    label: "Forward (FR / first-strand)",
    mappingNote: "Recorded as forward; Kallisto uses --fr-stranded.",
  },
  {
    value: "reverse",
    label: "Reverse (RF / second-strand)",
    mappingNote: "Recorded as reverse; Kallisto uses --rf-stranded.",
  },
];

export interface BulkReferenceInputs {
  transcriptomeFasta: string;
  annotationGtf: string;
  kallistoIndex: string;
  transcriptToGene: string;
}

export function resolveBulkReferenceMode(
  startStage: RunStartStage,
  quantificationReferenceMode: BulkReferenceMode,
): BulkReferenceMode {
  if (startStage === "analysis") {
    return "existing-index";
  }
  return quantificationReferenceMode;
}

export function buildBulkReferenceResources(
  startStage: RunStartStage,
  referenceMode: BulkReferenceMode,
  inputs: BulkReferenceInputs,
): Record<string, string> {
  const resources: Record<string, string> = {};
  if (startStage === "quantification" && referenceMode === "build") {
    const fasta = inputs.transcriptomeFasta.trim();
    const gtf = inputs.annotationGtf.trim();
    if (fasta) resources.transcriptome_fasta = fasta;
    if (gtf) resources.annotation_gtf = gtf;
    return resources;
  }
  if (startStage === "quantification" && referenceMode === "existing-index") {
    const index = inputs.kallistoIndex.trim();
    const gtf = inputs.annotationGtf.trim();
    const t2g = inputs.transcriptToGene.trim();
    if (index) resources.kallisto_index = index;
    if (gtf) resources.annotation_gtf = gtf;
    else if (t2g) resources.transcript_to_gene = t2g;
    return resources;
  }
  if (startStage === "analysis") {
    const gtf = inputs.annotationGtf.trim();
    const t2g = inputs.transcriptToGene.trim();
    if (gtf) resources.annotation_gtf = gtf;
    else if (t2g) resources.transcript_to_gene = t2g;
  }
  return resources;
}

export function includedConditionGroups(
  samples: ReadonlyArray<{ included: boolean; condition: string }>,
): string[] {
  return [...new Set(
    samples
      .filter((sample) => sample.included)
      .map((sample) => sample.condition.trim())
      .filter(Boolean),
  )].sort();
}

export function validateComparisonSelection(
  numerator: string,
  denominator: string,
  groups: readonly string[],
): string | null {
  if (!numerator.trim() || !denominator.trim()) {
    return "Choose both a numerator and a denominator condition.";
  }
  if (numerator === denominator) {
    return "Choose two different groups for the comparison.";
  }
  if (!groups.includes(numerator)) {
    return `Numerator "${numerator}" is not an included sample condition.`;
  }
  if (!groups.includes(denominator)) {
    return `Denominator "${denominator}" is not an included sample condition.`;
  }
  return null;
}

export function comparisonLabel(numerator: string, denominator: string, intervention: string | null): string {
  const base = `${numerator} (test) vs ${denominator} (reference); positive log2FC means higher expression in ${numerator}`;
  return intervention ? `${base} within ${intervention}` : base;
}

export function normalizeBulkStrandedness(value: unknown): BulkStrandedness {
  if (value === "unstranded" || value === "forward" || value === "reverse") {
    return value;
  }
  return "reverse";
}

export function normalizeBulkReferenceMode(value: unknown): BulkReferenceMode {
  return value === "build" ? "build" : "existing-index";
}

export function normalizeMaxParallelTasks(value: unknown, fallback = 1): number {
  const parsed = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) return fallback;
  return Math.floor(parsed);
}

export interface DebugExportWizardSlice {
  pipeline_identifier: "bulk-rnaseq" | "ont-analysis";
  start_stage?: RunStartStage;
  options?: Record<string, unknown>;
}

export function mergeImportedBulkOptions(
  current: Record<string, unknown>,
  imported: Record<string, unknown>,
  pipeline: "bulk-rnaseq" | "ont-analysis",
): Record<string, unknown> {
  if (pipeline !== "bulk-rnaseq") {
    return { ...current, ...imported, executionProfile: "local" };
  }
  const executionProfile =
    imported.executionProfile === "docker" || imported.executionProfile === "local"
      ? imported.executionProfile
      : "local";
  return {
    ...current,
    ...imported,
    executionProfile,
    readLayout: "paired-end",
    strandedness: normalizeBulkStrandedness(imported.strandedness ?? current.strandedness),
    referenceMode: normalizeBulkReferenceMode(imported.referenceMode ?? current.referenceMode),
    maxParallelTasks: normalizeMaxParallelTasks(
      imported.maxParallelTasks ?? current.maxParallelTasks,
      normalizeMaxParallelTasks(current.maxParallelTasks),
    ),
    adapterR1: typeof imported.adapterR1 === "string" && imported.adapterR1.trim()
      ? imported.adapterR1
      : (typeof current.adapterR1 === "string" ? current.adapterR1 : DEFAULT_ADAPTER_R1),
    adapterR2: typeof imported.adapterR2 === "string" && imported.adapterR2.trim()
      ? imported.adapterR2
      : (typeof current.adapterR2 === "string" ? current.adapterR2 : DEFAULT_ADAPTER_R2),
    transcriptToGene: typeof imported.transcriptToGene === "string" ? imported.transcriptToGene : "",
  };
}

export function manifestUsesBulkProductionContract(manifest: Pick<ProjectManifest, "schema_version" | "pipeline_version" | "pipeline_identifier">): boolean {
  return manifest.pipeline_identifier === "bulk-rnaseq"
    && manifest.schema_version === BULK_MANIFEST_SCHEMA_VERSION
    && manifest.pipeline_version === BULK_PIPELINE_VERSION;
}

export function comparisonIds(comparisons: Comparison[]): string[] {
  return comparisons.map((comparison) => comparison.comparison_id);
}
