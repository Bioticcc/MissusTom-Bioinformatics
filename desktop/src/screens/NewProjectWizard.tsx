import { useMemo, useState } from "react";
import { apiRequest } from "../api";
import { CheckList } from "../components/CheckList";
import { FolderPreview } from "../components/FolderPreview";
import { PipelineDependencies } from "../components/PipelineDependencies";
import { readTextFile, saveTextFile, selectDirectory, selectFiles } from "../native";
import { loadProjectDefaults } from "../preferences";
import type {
  Comparison,
  DirectoryPreview,
  FastqDiscoveryResult,
  MetadataCsvResult,
  ProjectManifest,
  ProjectValidation,
  ProposedSample,
  QuantificationDiscoveryResult,
  RunPlan,
  RunStartStage,
} from "../types";

const bulkSteps = [
  "Project & directories",
  "FASTQ discovery",
  "Sample review",
  "Experimental design",
  "Comparisons",
  "Pipeline options",
  "Preflight validation",
  "Review & save",
];

const ontSteps = [
  "Project & directories",
  "BAM selection",
  "Sample review",
  "ONT pipeline options",
  "Stage 05 annotation resources",
  "Preflight validation",
  "Review & save",
];

type PipelineIdentifier = "bulk-rnaseq" | "ont-analysis";

type InputDiscoveryResult = FastqDiscoveryResult | QuantificationDiscoveryResult;

interface DetailsState {
  projectName: string;
  inputDirectory: string;
  outputDirectory: string;
}

interface OptionsState {
  organism: string;
  referenceGenome: string;
  annotationSource: string;
  transcriptomeFasta: string;
  annotationGtf: string;
  kallistoIndex: string;
  biomart: string;
  referenceFasta: string;
  referenceFai: string;
  minimap2Index: string;
  gencodeGff3: string;
  cpgIslands: string;
  ccreTable: string;
  intergenicBed: string;
  ontInstrumentReport: string;
  libraryType: string;
  readLayout: "paired-end" | "single-end";
  strandedness: "unstranded" | "forward" | "reverse" | "unknown";
  executionProfile: "local" | "docker" | "apptainer";
  cpus: number;
  memoryGb: number;
  minimumReadLength: number;
  trimQuality: number;
  adapterR1: string;
  adapterR2: string;
  minimumGroupSize: number;
  adjustedPValue: number;
  absoluteLog2FoldChange: number;
  coverageWindowSize: number;
  modkitFilterPercentile: number;
  modkitMaxDepth: number;
  explorationMinValidCoverage: number;
  explorationMinFeatureCpgs: number;
}

interface MetadataImportStatus {
  path: string;
  matched: number;
  unmatchedSamples: string[];
  unusedRows: string[];
  warnings: string[];
}

interface AssignmentHistoryEntry {
  timestamp: string;
  action: string;
  matched: number;
  details: Record<string, string>;
}

function toSafeId(value: string) {
  return value.trim().replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[_\-.]+|[_\-.]+$/g, "");
}

function formatBytes(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 2 ? 1 : 0)} ${units[index]}`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function normalizeSearchText(value: string) {
  return value.toLocaleLowerCase().replace(/[\s._-]+/g, "");
}

function normalizeDiscoveredSample(sample: ProposedSample): ProposedSample {
  return {
    ...sample,
    r1_files: Array.isArray(sample.r1_files) ? sample.r1_files : [],
    r2_files: Array.isArray(sample.r2_files) ? sample.r2_files : [],
    ont_bam_files: Array.isArray(sample.ont_bam_files) ? sample.ont_bam_files : [],
    abundance_tsv: typeof sample.abundance_tsv === "string" ? sample.abundance_tsv : null,
    lanes: Array.isArray(sample.lanes) ? sample.lanes : [],
    warnings: Array.isArray(sample.warnings) ? sample.warnings : [],
    condition: typeof sample.condition === "string" ? sample.condition : "",
    biological_replicate:
      typeof sample.biological_replicate === "string" ? sample.biological_replicate : "",
    batch: typeof sample.batch === "string" ? sample.batch : null,
    covariates: isRecord(sample.covariates) ? sample.covariates : {},
    included: typeof sample.included === "boolean" ? sample.included : true,
  };
}

export function NewProjectWizard({
  onProjectReady,
}: {
  onProjectReady: (manifest: ProjectManifest, plan: RunPlan) => void;
}) {
  const [projectDefaults] = useState(loadProjectDefaults);
  const [step, setStep] = useState(0);
  const [pipelineIdentifier, setPipelineIdentifier] = useState<PipelineIdentifier>("bulk-rnaseq");
  const [startStage, setStartStage] = useState<RunStartStage>("quantification");
  const [details, setDetails] = useState<DetailsState>({
    projectName: "",
    inputDirectory: "",
    outputDirectory: projectDefaults.projectParentDirectory ? `${projectDefaults.projectParentDirectory.replace(/[\\/]+$/, "")}/untitled-project` : "",
  });
  const [options, setOptions] = useState<OptionsState>({
    organism: "Homo sapiens",
    referenceGenome: "GRCh38",
    annotationSource: "GENCODE",
    transcriptomeFasta: "",
    annotationGtf: "",
    kallistoIndex: "",
    biomart: "",
    referenceFasta: "",
    referenceFai: "",
    minimap2Index: "",
    gencodeGff3: "",
    cpgIslands: "",
    ccreTable: "",
    intergenicBed: "",
    ontInstrumentReport: "",
    libraryType: "total RNA",
    readLayout: "paired-end",
    strandedness: "reverse",
    executionProfile: "local",
    cpus: projectDefaults.cpus,
    memoryGb: projectDefaults.memoryGb,
    minimumReadLength: 20,
    trimQuality: 20,
    adapterR1: "AGATCGGAAGAGCACACGTCTGAACTCCAGTCA",
    adapterR2: "AGATCGGAAGAGCGTCGTGTAGGGAAAGAGTGT",
    minimumGroupSize: 2,
    adjustedPValue: 0.05,
    absoluteLog2FoldChange: 0.3,
    coverageWindowSize: 100000,
    modkitFilterPercentile: 0.1,
    modkitMaxDepth: 60000,
    explorationMinValidCoverage: 10,
    explorationMinFeatureCpgs: 5,
  });
  const [discovery, setDiscovery] = useState<InputDiscoveryResult | null>(null);
  const [samples, setSamples] = useState<ProposedSample[]>([]);
  const [comparisons, setComparisons] = useState<Comparison[]>([]);
  const [numerator, setNumerator] = useState("");
  const [denominator, setDenominator] = useState("");
  const [comparisonIntervention, setComparisonIntervention] = useState("");
  const [assignmentSearch, setAssignmentSearch] = useState("");
  const [assignmentCondition, setAssignmentCondition] = useState("");
  const [assignmentReplicate, setAssignmentReplicate] = useState("");
  const [assignmentBatch, setAssignmentBatch] = useState("");
  const [assignmentIntervention, setAssignmentIntervention] = useState("");
  const [validation, setValidation] = useState<ProjectValidation | null>(null);
  const [validatedManifest, setValidatedManifest] = useState<ProjectManifest | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [savedPath, setSavedPath] = useState("");
  const [exportPath, setExportPath] = useState("");
  const [importPath, setImportPath] = useState("");
  const [inputPreview, setInputPreview] = useState<DirectoryPreview | null>(null);
  const [outputPreview, setOutputPreview] = useState<DirectoryPreview | null>(null);
  const [metadataImport, setMetadataImport] = useState<MetadataImportStatus | null>(null);
  const [assignmentHistory, setAssignmentHistory] = useState<AssignmentHistoryEntry[]>([]);
  const [projectId, setProjectId] = useState<string>(() => crypto.randomUUID());
  const [createdAt, setCreatedAt] = useState(() => new Date().toISOString());
  const isOntPipeline = pipelineIdentifier === "ont-analysis";
  const steps = useMemo(
    () => (isOntPipeline ? ontSteps : bulkSteps).map((label, index) => (
      !isOntPipeline && index === 1 ? (startStage === "analysis" ? "Kallisto discovery" : "FASTQ discovery") : label
    )),
    [isOntPipeline, startStage],
  );

  const groups = useMemo(
    () =>
      [...new Set(samples.filter((sample) => sample.included).map((sample) => sample.condition.trim()))]
        .filter(Boolean)
        .sort(),
    [samples],
  );
  const interventions = useMemo(
    () => [...new Set(samples
      .filter((sample) => sample.included)
      .map((sample) => sample.covariates.intervention)
      .filter((value): value is string => typeof value === "string" && Boolean(value.trim())))]
      .sort(),
    [samples],
  );
  const assignmentMatchCount = useMemo(() => {
    const match = normalizeSearchText(assignmentSearch.trim());
    if (!match) return 0;
    return samples.filter(
      (sample) => sample.included && normalizeSearchText(sample.sample_id).includes(match),
    ).length;
  }, [assignmentSearch, samples]);

  const invalidateValidation = () => {
    setValidation(null);
    setValidatedManifest(null);
    setSavedPath("");
  };

  const updateStartStage = (value: RunStartStage) => {
    setStartStage(value);
    setDetails((current) => ({ ...current, inputDirectory: "" }));
    setInputPreview(null);
    setDiscovery(null);
    setSamples([]);
    setMetadataImport(null);
    setComparisons([]);
    invalidateValidation();
  };

  const updatePipeline = (value: PipelineIdentifier) => {
    if (value === pipelineIdentifier) return;
    setPipelineIdentifier(value);
    setStep(0);
    setStartStage("quantification");
    setDetails((current) => ({ ...current, inputDirectory: "" }));
    setInputPreview(null);
    setDiscovery(null);
    setSamples([]);
    setComparisons([]);
    setMetadataImport(null);
    setOptions((current) => value === "ont-analysis"
      ? {
          ...current,
          organism: "Mus musculus",
          referenceGenome: "GRCm38p6",
          annotationSource: "GENCODE",
          libraryType: "ONT long-read",
          readLayout: "single-end",
          strandedness: "unknown",
          executionProfile: "local",
        }
      : {
          ...current,
          organism: "Homo sapiens",
          referenceGenome: "GRCh38",
          annotationSource: "GENCODE",
          libraryType: "total RNA",
          readLayout: "paired-end",
          strandedness: "reverse",
          executionProfile: "local",
        });
    invalidateValidation();
  };

  const updateDetails = (key: keyof DetailsState, value: string) => {
    setDetails((current) => {
      if (key === "projectName" && projectDefaults.projectParentDirectory) {
        const parent = projectDefaults.projectParentDirectory.replace(/[\\/]+$/, "");
        const currentDefault = `${parent}/${toSafeId(current.projectName) || "untitled-project"}`;
        if (current.outputDirectory === currentDefault) return { ...current, projectName: value, outputDirectory: `${parent}/${toSafeId(value) || "untitled-project"}` };
      }
      return { ...current, [key]: value };
    });
    if (key === "inputDirectory") setInputPreview(null);
    if (key === "outputDirectory") setOutputPreview(null);
    invalidateValidation();
  };

  const loadFolderPreview = async (kind: "input" | "output", directory: string) => {
    if (!directory.trim()) return;
    setBusy(`${kind}-preview`);
    setError("");
    try {
      const preview = await apiRequest<DirectoryPreview>("/api/v1/directories/preview", {
        method: "POST",
        body: JSON.stringify({ directory }),
      });
      if (kind === "input") setInputPreview(preview);
      else setOutputPreview(preview);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The folder could not be previewed.");
    } finally {
      setBusy("");
    }
  };

  const chooseFolder = async (kind: "input" | "output") => {
    setBusy(`${kind}-select`);
    setError("");
    try {
      const directory = await selectDirectory(
        kind === "input"
          ? (isOntPipeline ? "Select ONT BAM source folder" : startStage === "analysis" ? "Select Kallisto results folder" : "Select input FASTQ folder")
          : "Select project output folder",
      );
      if (!directory) return;
      const key = kind === "input" ? "inputDirectory" : "outputDirectory";
      setDetails((current) => ({ ...current, [key]: directory }));
      invalidateValidation();
      await loadFolderPreview(kind, directory);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The folder could not be selected.");
    } finally {
      setBusy("");
    }
  };

  const updateOptions = <K extends keyof OptionsState>(key: K, value: OptionsState[K]) => {
    setOptions((current) => ({ ...current, [key]: value }));
    invalidateValidation();
  };

  const updateSample = <K extends keyof ProposedSample>(
    index: number,
    key: K,
    value: ProposedSample[K],
  ) => {
    setSamples((current) =>
      current.map((sample, sampleIndex) =>
        sampleIndex === index ? { ...sample, [key]: value } : sample,
      ),
    );
    setMetadataImport(null);
    invalidateValidation();
  };

  const chooseReferenceFile = async (
    key: "kallistoIndex" | "biomart" | "transcriptomeFasta" | "annotationGtf" | "referenceFasta" | "referenceFai" | "minimap2Index" | "gencodeGff3" | "cpgIslands" | "ccreTable" | "intergenicBed" | "ontInstrumentReport",
    title: string,
  ) => {
    const busyKey = `reference-${key}`;
    setBusy(busyKey);
    setError("");
    try {
      const selected = await selectFiles(title);
      if (selected?.[0]) updateOptions(key, selected[0]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The file could not be selected.");
    } finally {
      setBusy("");
    }
  };

  const chooseSampleInput = async (
    index: number,
    key: "r1_files" | "r2_files" | "abundance_tsv" | "ont_bam_files",
  ) => {
    const multiple = key !== "abundance_tsv";
    const busyKey = `sample-${index}-${key}`;
    setBusy(busyKey);
    setError("");
    try {
      const selected = await selectFiles(
        key === "abundance_tsv"
          ? "Select Kallisto abundance.tsv"
          : key === "ont_bam_files"
            ? "Select ONT BAM file(s)"
            : `Select ${key === "r1_files" ? "R1" : "R2"} FASTQ file(s)`,
        multiple,
      );
      if (!selected) return;
      if (key === "abundance_tsv") updateSample(index, key, selected[0] ?? null);
      else updateSample(index, key, selected);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The file could not be selected.");
    } finally {
      setBusy("");
    }
  };

  const addOntBamSamples = async () => {
    setBusy("ont-bam-select");
    setError("");
    try {
      const selected = await selectFiles("Select ONT BAM file(s)", true);
      if (!selected?.length) return;
      setSamples((current) => {
        const existing = current[0];
        if (existing) return [{ ...existing, ont_bam_files: [...new Set([...existing.ont_bam_files, ...selected])] }];
        return [{
          sample_id: "ont_sample",
          r1_files: [],
          r2_files: [],
          ont_bam_files: selected,
          abundance_tsv: null,
          lanes: [],
          pairing_status: "single" as const,
          warnings: [],
          condition: "",
          biological_replicate: "",
          batch: null,
          covariates: {},
          included: true,
        }];
      });
      invalidateValidation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "ONT BAM files could not be selected.");
    } finally {
      setBusy("");
    }
  };

  const importMetadataCsv = async () => {
    setBusy("metadata-csv");
    setError("");
    try {
      const selected = await selectFiles("Select experimental metadata CSV");
      if (!selected?.[0]) return;
      const result = await apiRequest<MetadataCsvResult>("/api/v1/metadata/csv", {
        method: "POST",
        body: JSON.stringify({ path: selected[0], sample_ids: samples.map((sample) => sample.sample_id) }),
      });
      const rowsBySample = new Map(result.rows
        .filter((row) => row.matched_sample_id)
        .map((row) => [row.matched_sample_id as string, row]));
      const matched = rowsBySample.size;
      const updatedSamples = samples.map((sample) => {
        const row = rowsBySample.get(sample.sample_id);
        if (!row) return sample;
        return {
          ...sample,
          condition: row.condition,
          batch: row.batch,
          biological_replicate: row.biological_replicate ?? sample.biological_replicate,
          covariates: {
            ...sample.covariates,
            ...(row.intervention ? { intervention: row.intervention } : {}),
          },
        };
      });
      setSamples(updatedSamples);
      setMetadataImport({
        path: result.path,
        matched,
        unmatchedSamples: result.unmatched_samples,
        unusedRows: result.unused_rows,
        warnings: result.warnings,
      });
      setAssignmentHistory((current) => [...current, {
        timestamp: new Date().toISOString(),
        action: "metadata_csv_import",
        matched,
        details: { path: result.path },
      }]);
      if (matched > 0) {
        setComparisons([]);
        setNumerator("");
        setDenominator("");
        setComparisonIntervention("");
      }
      invalidateValidation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The metadata CSV could not be imported.");
    } finally {
      setBusy("");
    }
  };

  const referenceFileField = (
    label: string,
    key: "kallistoIndex" | "biomart" | "transcriptomeFasta" | "annotationGtf" | "referenceFasta" | "referenceFai" | "minimap2Index" | "gencodeGff3" | "cpgIslands" | "ccreTable" | "intergenicBed" | "ontInstrumentReport",
    placeholder: string,
    required = false,
  ) => (
    <div className="path-file-field"><label htmlFor={`reference-${key}`}>{label} {required && <span aria-hidden="true">*</span>}</label><div className="path-input-row"><input id={`reference-${key}`} value={options[key]} onChange={(event) => updateOptions(key, event.target.value)} placeholder={placeholder} /><button className="button secondary" type="button" onClick={() => void chooseReferenceFile(key, `Select ${label}`)} disabled={busy === `reference-${key}`}>{busy === `reference-${key}` ? "Selecting…" : "Browse…"}</button></div></div>
  );

  const discover = async () => {
    setBusy("discover");
    setError("");
    try {
      const endpoint = startStage === "analysis"
        ? "/api/v1/quantifications/discover"
        : "/api/v1/fastq/discover";
      const result = await apiRequest<InputDiscoveryResult>(endpoint, {
        method: "POST",
        body: JSON.stringify({ directory: details.inputDirectory, recursive: true }),
      });
      const discoveredSamples = result.samples.map(normalizeDiscoveredSample);
      setDiscovery({ ...result, samples: discoveredSamples });
      const previousById = new Map(samples.map((sample) => [sample.sample_id, sample]));
      const mergedSamples = discoveredSamples.map((sample) => {
        const previous = previousById.get(sample.sample_id);
        return previous
          ? {
              ...sample,
              condition: typeof previous.condition === "string" ? previous.condition : "",
              biological_replicate:
                typeof previous.biological_replicate === "string"
                  ? previous.biological_replicate
                  : "",
              batch: typeof previous.batch === "string" ? previous.batch : null,
              covariates: isRecord(previous.covariates) ? previous.covariates : {},
              included: typeof previous.included === "boolean" ? previous.included : true,
            }
          : sample;
      });
      const remainingGroups = new Set(mergedSamples
        .filter((sample) => sample.included && sample.condition.trim())
        .map((sample) => sample.condition.trim()));
      setSamples(mergedSamples);
      setAssignmentHistory((current) => [...current, {
        timestamp: new Date().toISOString(),
        action: "input_rediscovery",
        matched: mergedSamples.filter((sample) => Boolean(previousById.get(sample.sample_id))).length,
        details: { preserved_existing_design: "true" },
      }]);
      setComparisons((current) => current.filter((comparison) =>
        remainingGroups.has(comparison.numerator) && remainingGroups.has(comparison.denominator),
      ));
      setMetadataImport(null);
      invalidateValidation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "FASTQ discovery failed");
    } finally {
      setBusy("");
    }
  };

  const buildManifest = (): ProjectManifest => {
    const referenceResources: Record<string, string> = {};
    if (!isOntPipeline && startStage === "quantification") {
      if (options.transcriptomeFasta.trim()) referenceResources.transcriptome_fasta = options.transcriptomeFasta;
      if (options.annotationGtf.trim()) referenceResources.annotation_gtf = options.annotationGtf;
      if (options.kallistoIndex.trim()) referenceResources.kallisto_index = options.kallistoIndex;
    }
    if (!isOntPipeline && options.biomart.trim()) referenceResources.biomart = options.biomart;
    if (isOntPipeline) {
      if (options.referenceFasta.trim()) referenceResources.reference_fasta = options.referenceFasta;
      if (options.referenceFai.trim()) referenceResources.reference_fai = options.referenceFai;
      if (options.minimap2Index.trim()) referenceResources.minimap2_index = options.minimap2Index;
      if (options.gencodeGff3.trim()) referenceResources.gencode_gff3 = options.gencodeGff3;
      if (options.cpgIslands.trim()) referenceResources.cpg_islands = options.cpgIslands;
      if (options.ccreTable.trim()) referenceResources.ccre_table = options.ccreTable;
      if (options.intergenicBed.trim()) referenceResources.intergenic_bed = options.intergenicBed;
      if (options.ontInstrumentReport.trim()) referenceResources.ont_instrument_report = options.ontInstrumentReport;
    }

    return {
      schema_version: "1.0.0",
      project_name: details.projectName,
      project_identifier: projectId,
      created_at: createdAt,
      input_directory: details.inputDirectory,
      output_directory: details.outputDirectory,
      pipeline_identifier: pipelineIdentifier,
      pipeline_version: isOntPipeline ? "0.1.0" : "0.4.0",
      organism: options.organism,
      reference_genome: options.referenceGenome,
      annotation_source: options.annotationSource,
      reference_resources: referenceResources,
      library_type: options.libraryType,
      read_layout: isOntPipeline ? "single-end" : options.readLayout,
      strandedness: isOntPipeline ? "unknown" : options.strandedness,
      samples: samples.map((sample) => ({
        sample_id: sample.sample_id,
        r1_files: sample.r1_files,
        r2_files: isOntPipeline || options.readLayout === "single-end" ? [] : sample.r2_files,
        ont_bam_files: sample.ont_bam_files,
        abundance_tsv: isOntPipeline ? null : sample.abundance_tsv,
        condition: sample.condition,
        biological_replicate: sample.biological_replicate,
        batch: sample.batch,
        covariates: sample.covariates,
        included: sample.included,
      })),
      comparisons: isOntPipeline ? [] : comparisons,
      parameters: {
        ...(isOntPipeline ? {} : { start_stage: startStage }),
        ...(isOntPipeline ? {
          coverage_window_size: options.coverageWindowSize,
          methylation_window_size: options.coverageWindowSize,
          modkit_filter_percentile: options.modkitFilterPercentile,
          modkit_max_depth: options.modkitMaxDepth,
          exploration_min_valid_coverage: options.explorationMinValidCoverage,
          exploration_min_feature_cpgs: options.explorationMinFeatureCpgs,
          expected_pass_bam_count: samples
            .filter((sample) => sample.included)
            .reduce((total, sample) => total + sample.ont_bam_files.length, 0),
        } : {}),
        ...(!isOntPipeline && startStage === "quantification" ? {
          adapter_r1: options.adapterR1,
          adapter_r2: options.adapterR2,
          trim_quality: options.trimQuality,
          trim_minimum_length: options.minimumReadLength,
        } : {}),
        ...(!isOntPipeline ? {
          differential_expression: true,
          minimum_group_size: options.minimumGroupSize,
          adjusted_p_value: options.adjustedPValue,
          absolute_log2_fold_change: options.absoluteLog2FoldChange,
        } : {}),
      },
      resource_profile: { cpus: options.cpus, memory_gb: options.memoryGb, max_parallel_tasks: 1 },
      execution_profile: options.executionProfile,
      application_version: "0.3.0",
      pipeline_status: "draft",
    };
  };

  const exportSettings = async () => {
    setBusy("export-settings");
    setError("");
    setExportPath("");
    try {
      const payload = {
        export_format: "missus-tom-project-debug",
        export_version: 2,
        exported_at: new Date().toISOString(),
        warning: "Contains local file paths and sample identifiers. Review before sharing.",
        wizard: {
          current_step: step + 1,
          current_step_label: steps[step],
          pipeline_identifier: pipelineIdentifier,
          start_stage: startStage,
          details,
          options,
          samples,
          comparisons,
          discovery,
          metadata_import: metadataImport,
          pending_assignment: {
            search: assignmentSearch,
            condition: assignmentCondition,
            biological_replicate: assignmentReplicate,
            batch: assignmentBatch,
            intervention: assignmentIntervention,
          },
          pending_comparison: { numerator, denominator, intervention: comparisonIntervention },
          assignment_history: assignmentHistory,
          validation,
        },
        manifest_draft: buildManifest(),
      };
      const baseName = toSafeId(details.projectName) || "untitled-project";
      const path = await saveTextFile(
        "Export Missus Tom project settings",
        `${baseName}-debug-settings.json`,
        `${JSON.stringify(payload, null, 2)}\n`,
      );
      if (path) setExportPath(path);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Project settings could not be exported.");
    } finally {
      setBusy("");
    }
  };

  const importSettings = async () => {
    setBusy("import-settings");
    setError("");
    setImportPath("");
    try {
      const selected = await selectFiles("Import Missus Tom project settings");
      if (!selected?.[0]) return;
      const parsed: unknown = JSON.parse(await readTextFile(selected[0]));
      if (!isRecord(parsed) || parsed.export_format !== "missus-tom-project-debug") {
        throw new Error("This is not a Missus Tom project-settings export.");
      }
      if (!isRecord(parsed.wizard)) {
        throw new Error("The settings export does not contain wizard state.");
      }
      const imported = parsed.wizard;
      const importedPipeline: PipelineIdentifier = imported.pipeline_identifier === "ont-analysis"
        || (isRecord(parsed.manifest_draft) && parsed.manifest_draft.pipeline_identifier === "ont-analysis")
        ? "ont-analysis"
        : "bulk-rnaseq";
      if (
        !isRecord(imported.details)
        || !isRecord(imported.options)
        || !Array.isArray(imported.samples)
        || !Array.isArray(imported.comparisons)
        || (importedPipeline === "bulk-rnaseq" && imported.start_stage !== "quantification" && imported.start_stage !== "analysis")
      ) {
        throw new Error("The settings export is incomplete or malformed.");
      }
      const samplesAreValid = imported.samples.every((sample) =>
        isRecord(sample)
        && typeof sample.sample_id === "string"
        && Array.isArray(sample.r1_files)
        && Array.isArray(sample.r2_files)
        && typeof sample.condition === "string"
        && typeof sample.biological_replicate === "string"
        && typeof sample.included === "boolean");
      const comparisonsAreValid = imported.comparisons.every((comparison) =>
        isRecord(comparison)
        && typeof comparison.comparison_id === "string"
        && typeof comparison.numerator === "string"
        && typeof comparison.denominator === "string");
      if (!samplesAreValid || !comparisonsAreValid) {
        throw new Error("The settings export contains malformed samples or comparisons.");
      }

      const importedSamples = (imported.samples as ProposedSample[]).map((sample) => ({
        ...sample,
        ont_bam_files: Array.isArray(sample.ont_bam_files) ? sample.ont_bam_files : [],
        abundance_tsv: typeof sample.abundance_tsv === "string" ? sample.abundance_tsv : null,
        lanes: Array.isArray(sample.lanes) ? sample.lanes : [],
        warnings: Array.isArray(sample.warnings) ? sample.warnings : [],
        pairing_status: sample.pairing_status ?? "single",
        covariates: isRecord(sample.covariates) ? sample.covariates : {},
      }));
      const importedComparisons = (imported.comparisons as Comparison[]).map((comparison) => ({
        ...comparison,
        intervention: comparison.intervention ?? null,
      }));
      const pendingAssignment = isRecord(imported.pending_assignment)
        ? imported.pending_assignment
        : {};
      const pendingComparison = isRecord(imported.pending_comparison)
        ? imported.pending_comparison
        : {};
      const manifestDraft = isRecord(parsed.manifest_draft) ? parsed.manifest_draft : {};

      setPipelineIdentifier(importedPipeline);
      setStartStage(imported.start_stage === "analysis" ? "analysis" : "quantification");
      setDetails(imported.details as unknown as DetailsState);
      setOptions((current) => {
        const importedOptions = imported.options as Partial<OptionsState>;
        const importedProfile = importedOptions.executionProfile;
        const executionProfile =
          importedPipeline === "ont-analysis"
            ? "local"
            : importedProfile === "docker" || importedProfile === "local"
              ? importedProfile
              : "local";
        return { ...current, ...importedOptions, executionProfile };
      });
      setSamples(importedSamples);
      setComparisons(importedComparisons);
      setDiscovery((imported.discovery as InputDiscoveryResult | null) ?? null);
      setMetadataImport((imported.metadata_import as MetadataImportStatus | null) ?? null);
      setAssignmentSearch(typeof pendingAssignment.search === "string" ? pendingAssignment.search : "");
      setAssignmentCondition(typeof pendingAssignment.condition === "string" ? pendingAssignment.condition : "");
      setAssignmentReplicate(typeof pendingAssignment.biological_replicate === "string" ? pendingAssignment.biological_replicate : "");
      setAssignmentBatch(typeof pendingAssignment.batch === "string" ? pendingAssignment.batch : "");
      setAssignmentIntervention(typeof pendingAssignment.intervention === "string" ? pendingAssignment.intervention : "");
      setNumerator(typeof pendingComparison.numerator === "string" ? pendingComparison.numerator : "");
      setDenominator(typeof pendingComparison.denominator === "string" ? pendingComparison.denominator : "");
      setComparisonIntervention(typeof pendingComparison.intervention === "string" ? pendingComparison.intervention : "");
      setAssignmentHistory(Array.isArray(imported.assignment_history)
        ? imported.assignment_history as AssignmentHistoryEntry[]
        : []);
      if (typeof manifestDraft.project_identifier === "string") {
        setProjectId(manifestDraft.project_identifier);
      }
      if (typeof manifestDraft.created_at === "string") setCreatedAt(manifestDraft.created_at);
      if (typeof imported.current_step === "number") {
        const importedSteps = importedPipeline === "ont-analysis" ? ontSteps : bulkSteps;
        setStep(Math.max(0, Math.min(importedSteps.length - 1, imported.current_step - 1)));
      }
      setValidation(null);
      setValidatedManifest(null);
      setInputPreview(null);
      setOutputPreview(null);
      setSavedPath("");
      setExportPath("");
      setImportPath(selected[0]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Project settings could not be imported.");
    } finally {
      setBusy("");
    }
  };

  const validate = async () => {
    setBusy("validate");
    setError("");
    try {
      const result = await apiRequest<ProjectValidation>("/api/v1/projects/validate", {
        method: "POST",
        body: JSON.stringify(buildManifest()),
      });
      setValidation(result);
      setValidatedManifest(result.valid ? result.manifest : null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Project validation failed");
    } finally {
      setBusy("");
    }
  };

  const saveAndPlan = async () => {
    if (!validatedManifest) return;
    setBusy("save");
    setError("");
    try {
      const plannedManifest = { ...validatedManifest, pipeline_status: "planned" as const };
      const saved = await apiRequest<{ manifest_path: string }>("/api/v1/projects/save", {
        method: "POST",
        body: JSON.stringify(plannedManifest),
      });
      const plan = await apiRequest<RunPlan>("/api/v1/runs/plan", {
        method: "POST",
        body: JSON.stringify({ manifest: plannedManifest }),
      });
      setSavedPath(saved.manifest_path);
      onProjectReady(plannedManifest, plan);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Project save failed");
    } finally {
      setBusy("");
    }
  };

  const applyDesignAssignment = () => {
    const search = assignmentSearch.trim();
    const condition = assignmentCondition.trim();
    const replicate = assignmentReplicate.trim();
    const batch = assignmentBatch.trim();
    const intervention = assignmentIntervention.trim();
    if (!search) {
      setError("Enter text to find in the sample identifiers.");
      return;
    }
    if (!condition && !replicate && !batch && !intervention) {
      setError("Enter a condition, biological replicate, batch, or intervention to assign.");
      return;
    }
    if (assignmentMatchCount === 0) {
      setError(`No included sample identifiers contain "${search}".`);
      return;
    }
    const match = normalizeSearchText(search);
    setSamples((current) => current.map((sample) =>
      sample.included && normalizeSearchText(sample.sample_id).includes(match)
        ? {
            ...sample,
            condition: condition || sample.condition,
            biological_replicate: replicate || sample.biological_replicate,
            batch: batch || sample.batch,
            covariates: {
              ...sample.covariates,
              ...(intervention ? { intervention } : {}),
            },
          }
        : sample,
    ));
    setAssignmentSearch("");
    setAssignmentCondition("");
    setAssignmentReplicate("");
    setAssignmentBatch("");
    setAssignmentIntervention("");
    setComparisons([]);
    setNumerator("");
    setDenominator("");
    setComparisonIntervention("");
    setMetadataImport(null);
    setAssignmentHistory((current) => [...current, {
      timestamp: new Date().toISOString(),
      action: "bulk_design_assignment",
      matched: assignmentMatchCount,
      details: { search, condition, biological_replicate: replicate, batch, intervention },
    }]);
    setError("");
    invalidateValidation();
  };

  const useSampleIdsAsReplicates = () => {
    setSamples((current) => current.map((sample) =>
      sample.included ? { ...sample, biological_replicate: sample.sample_id } : sample,
    ));
    setMetadataImport(null);
    setAssignmentHistory((current) => [...current, {
      timestamp: new Date().toISOString(),
      action: "sample_ids_as_replicates",
      matched: samples.filter((sample) => sample.included).length,
      details: {},
    }]);
    setError("");
    invalidateValidation();
  };

  const addComparison = () => {
    if (!numerator || !denominator || numerator === denominator) {
      setError("Choose two different groups for the comparison.");
      return;
    }
    const comparisonId = toSafeId(
      `${numerator}_vs_${denominator}${comparisonIntervention ? `_within_${comparisonIntervention}` : ""}`,
    );
    if (comparisons.some((comparison) => comparison.comparison_id === comparisonId)) {
      setError("That comparison has already been added.");
      return;
    }
    setComparisons((current) => [
      ...current,
      {
        comparison_id: comparisonId,
        numerator,
        denominator,
        label: `${numerator} (test) vs ${denominator} (reference)${comparisonIntervention ? ` within ${comparisonIntervention}` : ""}`,
        intervention: comparisonIntervention || null,
      },
    ]);
    setError("");
    invalidateValidation();
  };

  const removeComparison = (comparisonId: string) => {
    setComparisons((current) =>
      current.filter((comparison) => comparison.comparison_id !== comparisonId),
    );
    invalidateValidation();
  };

  const renderStep = () => {
    switch (step) {
      case 0:
        return (
          <section className="wizard-card form-stack">
            <div className="section-heading"><div><p className="eyebrow">Step 1</p><h2>Project details</h2></div></div>
            <p className="helper-copy">Choose where this project starts before selecting its input folder.</p>
            <fieldset className="run-mode-panel setup-mode-panel">
              <legend>Pipeline</legend>
              <label className={`run-mode-option${pipelineIdentifier === "bulk-rnaseq" ? " selected" : ""}`}><input type="radio" name="pipeline" checked={pipelineIdentifier === "bulk-rnaseq"} onChange={() => updatePipeline("bulk-rnaseq")} /><span><strong>Bulk RNA-seq (human)</strong><small>Paired-end FASTQ quantification or existing Kallisto results with differential-expression analysis.</small></span></label>
              <label className={`run-mode-option${pipelineIdentifier === "ont-analysis" ? " selected" : ""}`}><input type="radio" name="pipeline" checked={pipelineIdentifier === "ont-analysis"} onChange={() => updatePipeline("ont-analysis")} /><span><strong>ONT (Oxford Nanopore) Analysis (mouse)</strong><small>Configure mouse long-read BAM inputs, alignment references, and Stage 05 annotation resources.</small></span></label>
            </fieldset>
            <PipelineDependencies pipelineIdentifier={pipelineIdentifier} />
            {!isOntPipeline && <fieldset className="run-mode-panel setup-mode-panel">
              <legend>Starting point</legend>
              <label className={`run-mode-option${startStage === "quantification" ? " selected" : ""}`}><input type="radio" name="setup-start-stage" checked={startStage === "quantification"} onChange={() => updateStartStage("quantification")} /><span><strong>Start with FASTQ files</strong><small>Run raw QC, trimming, Kallisto quantification, and analysis. Select a folder containing paired R1/R2 FASTQs.</small></span></label>
              <label className={`run-mode-option${startStage === "analysis" ? " selected" : ""}`}><input type="radio" name="setup-start-stage" checked={startStage === "analysis"} onChange={() => updateStartStage("analysis")} /><span><strong>Skip quantification</strong><small>Run analysis from existing Kallisto results. Select a folder containing one abundance.tsv file per sample.</small></span></label>
              {startStage === "analysis" && <p className="run-mode-note input-warning"><strong>Different inputs required:</strong> a Kallisto <code>abundance.tsv</code> for every sample, normally arranged as <code>&lt;input&gt;/&lt;sample_id&gt;/abundance.tsv</code>, plus a matching human BioMart table. The tables must come from a compatible human transcript index whose target identifiers retain Ensembl gene metadata. FASTQs and the index file itself are not required.</p>}
            </fieldset>}
            <label>Project name <span aria-hidden="true">*</span><input value={details.projectName} onChange={(event) => updateDetails("projectName", event.target.value)} placeholder="e.g. Human intervention study" /></label>
            <div className="directory-field">
              <label>{isOntPipeline ? "ONT BAM source directory" : startStage === "analysis" ? "Kallisto results directory" : "Input FASTQ directory"} <span aria-hidden="true">*</span><input value={details.inputDirectory} onChange={(event) => updateDetails("inputDirectory", event.target.value)} placeholder={isOntPipeline ? "/data/ont-alignment" : startStage === "analysis" ? "/data/kallisto-results" : "/data/sequencing/run-01"} /></label>
              <div className="directory-actions"><button className="button secondary" type="button" onClick={() => void chooseFolder("input")} disabled={busy.startsWith("input-")}>Select {isOntPipeline ? "ONT BAM" : startStage === "analysis" ? "Kallisto results" : "FASTQ"} folder</button><button className="text-button" type="button" onClick={() => void loadFolderPreview("input", details.inputDirectory)} disabled={!details.inputDirectory || busy === "input-preview"}>Preview typed path</button></div>
            </div>
            {inputPreview && <FolderPreview label="Input folder" preview={inputPreview} />}
            <div className="directory-field">
              <label>Project output directory <span aria-hidden="true">*</span><input value={details.outputDirectory} onChange={(event) => updateDetails("outputDirectory", event.target.value)} placeholder="/data/projects/human-intervention-study" /></label>
              <div className="directory-actions"><button className="button secondary" type="button" onClick={() => void chooseFolder("output")} disabled={busy.startsWith("output-")}>Select output folder</button><button className="text-button" type="button" onClick={() => void loadFolderPreview("output", details.outputDirectory)} disabled={!details.outputDirectory || busy === "output-preview"}>Preview typed path</button></div>
            </div>
            {outputPreview && <FolderPreview label="Output folder" preview={outputPreview} />}
            <div className="safety-note"><strong>Files created</strong><span>Manifest, configuration directories, and empty result directories only.</span></div>
          </section>
        );
      case 1:
        if (isOntPipeline) return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 2</p><h2>Select ONT BAM files</h2></div><button className="button primary" type="button" onClick={() => void addOntBamSamples()} disabled={busy === "ont-bam-select"}>{busy === "ont-bam-select" ? "Selecting…" : "Select BAM files…"}</button></div>
            <p className="helper-copy">Select the BAM chunks for the single mouse sample. Additional selections add files to the editable <code>ont_bam_files</code> list.</p>
            {samples.length === 0 ? <div className="empty-state compact"><div className="empty-orbit" aria-hidden="true">⌁</div><h3>No ONT BAM samples</h3><p>Select the BAM files for a sample to continue.</p></div> : <div className="file-preview"><h3>Selected BAM samples</h3><div className="file-preview-list">{samples.map((sample) => <div key={sample.sample_id}><span className="read-chip">BAM</span><code>{sample.sample_id}</code><small>{sample.ont_bam_files.length} file(s)</small></div>)}</div></div>}
          </section>
        );
        return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 2</p><h2>{startStage === "analysis" ? "Discover Kallisto results" : "Discover FASTQ files"}</h2></div><button className="button primary" type="button" onClick={discover} disabled={busy === "discover" || !details.inputDirectory}>{busy === "discover" ? "Scanning…" : "Scan directory"}</button></div>
            <p className="helper-copy">{startStage === "analysis" ? "The scanner finds Kallisto abundance.tsv files and proposes the parent folder as each sample identifier." : "The scanner reads names and file metadata only."} Symlinked directories are skipped.</p>
            {discovery ? (
              <>
                <div className="summary-grid three"><article className="metric-card"><span>{startStage === "analysis" ? "Abundance tables" : "FASTQs"}</span><strong>{discovery.total_files}</strong></article><article className="metric-card"><span>Proposed samples</span><strong>{discovery.samples.length}</strong></article><article className="metric-card"><span>Total size</span><strong>{formatBytes(discovery.total_bytes)}</strong></article></div>
                {discovery.warnings.length > 0 && <div className="warning-list"><strong>Discovery notes</strong><ul>{discovery.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
                <div className="file-preview"><h3>Detected files</h3><div className="file-preview-list">{discovery.files.slice(0, 12).map((file) => <div key={file.path}>{"read" in file ? <span className={`read-chip read-${file.read.toLowerCase()}`}>{file.read}</span> : <span className="read-chip">Kallisto</span>}<code>{file.path}</code><small>{formatBytes(file.size_bytes)}</small></div>)}</div>{discovery.files.length > 12 && <p>+ {discovery.files.length - 12} more files</p>}</div>
              </>
            ) : <div className="empty-state compact"><div className="empty-orbit" aria-hidden="true">⌁</div><h3>No scan results</h3><p>Enter an input directory in step 1.</p></div>}
          </section>
        );
      case 2:
        if (isOntPipeline) return (
          <section className="wizard-card wide-card">
            <div className="section-heading"><div><p className="eyebrow">Step 3</p><h2>Review ONT BAM samples</h2></div><span className="count-pill">{samples.length}</span></div>
            <p className="helper-copy">Review the biological sample identifiers and their explicitly selected BAM chunks.</p>
            {samples.length === 0 ? <p className="empty-copy">No BAM samples selected. Return to BAM selection first.</p> : <div className="table-scroll"><table className="sample-table analysis-input-table"><thead><tr><th>Use</th><th>Sample identifier</th><th>ONT BAM files</th><th>Status</th></tr></thead><tbody>{samples.map((sample, index) => <tr key={`${sample.sample_id}-${index}`}><td><input type="checkbox" checked={sample.included} onChange={(event) => updateSample(index, "included", event.target.checked)} aria-label={`Include ${sample.sample_id}`} /></td><td><input value={sample.sample_id} onChange={(event) => updateSample(index, "sample_id", event.target.value)} aria-label={`Sample identifier row ${index + 1}`} /></td><td><div className="sample-path-editor"><textarea rows={3} value={sample.ont_bam_files.join("\n")} onChange={(event) => updateSample(index, "ont_bam_files", event.target.value.split("\n").map((value) => value.trim()).filter(Boolean))} aria-label={`ONT BAM files for ${sample.sample_id}`} /><button className="text-button" type="button" onClick={() => void chooseSampleInput(index, "ont_bam_files")}>Browse…</button></div></td><td><span className="pair-status pair-single">BAM input</span></td></tr>)}</tbody></table></div>}
          </section>
        );
        return (
          <section className="wizard-card wide-card">
            <div className="section-heading"><div><p className="eyebrow">Step 3</p><h2>{startStage === "analysis" ? "Review samples and abundance tables" : "Review samples and read pairs"}</h2></div><span className="count-pill">{samples.length}</span></div>
            <p className="helper-copy">Review file assignments and sample identifiers. Experimental settings are configured in the next step.</p>
            {samples.length === 0 ? <p className="empty-copy">No sample proposals. Return to input discovery first.</p> : (
              <div className="table-scroll"><table className={`sample-table${startStage === "analysis" ? " analysis-input-table" : ""}`}><thead><tr><th>Use</th><th>Sample identifier</th>{startStage === "analysis" ? <th>abundance.tsv</th> : <><th>R1 files</th><th>R2 files</th></>}<th>Status</th></tr></thead><tbody>{samples.map((sample, index) => <tr key={`${sample.sample_id}-${index}`}><td><input type="checkbox" checked={sample.included} onChange={(event) => updateSample(index, "included", event.target.checked)} aria-label={`Include ${sample.sample_id}`} /></td><td><input value={sample.sample_id} onChange={(event) => updateSample(index, "sample_id", event.target.value)} aria-label={`Sample identifier row ${index + 1}`} /></td>{startStage === "analysis" ? <td><div className="sample-path-editor"><textarea rows={2} value={sample.abundance_tsv ?? ""} onChange={(event) => updateSample(index, "abundance_tsv", event.target.value.trim() || null)} aria-label={`Abundance table for ${sample.sample_id}`} /><button className="text-button" type="button" onClick={() => void chooseSampleInput(index, "abundance_tsv")}>Browse…</button></div></td> : <><td><div className="sample-path-editor"><textarea rows={2} value={sample.r1_files.join("\n")} onChange={(event) => updateSample(index, "r1_files", event.target.value.split("\n").map((value) => value.trim()).filter(Boolean))} aria-label={`R1 files for ${sample.sample_id}`} /><button className="text-button" type="button" onClick={() => void chooseSampleInput(index, "r1_files")}>Browse…</button></div></td><td><div className="sample-path-editor"><textarea rows={2} value={sample.r2_files.join("\n")} onChange={(event) => updateSample(index, "r2_files", event.target.value.split("\n").map((value) => value.trim()).filter(Boolean))} aria-label={`R2 files for ${sample.sample_id}`} /><button className="text-button" type="button" onClick={() => void chooseSampleInput(index, "r2_files")}>Browse…</button></div></td></>}<td><span className={`pair-status pair-${sample.pairing_status}`}>{sample.pairing_status}</span>{sample.warnings.map((warning) => <small className="cell-warning" key={warning}>{warning}</small>)}</td></tr>)}</tbody></table></div>
            )}
          </section>
        );
      case 3:
        if (isOntPipeline) return (
          <section className="wizard-card form-stack">
            <div className="section-heading"><div><p className="eyebrow">Step 4</p><h2>ONT pipeline options</h2></div></div>
            <p className="helper-copy">ONT analysis uses mouse long-read BAM inputs. Library layout and strandedness are recorded as single-end and unknown; no Kallisto or differential-expression settings apply.</p>
            <div className="field-pair"><label>Organism<input value={options.organism} onChange={(event) => updateOptions("organism", event.target.value)} /></label><label>Reference genome<input value={options.referenceGenome} onChange={(event) => updateOptions("referenceGenome", event.target.value)} /></label></div>
            <div className="field-pair"><label>Annotation source<input value={options.annotationSource} onChange={(event) => updateOptions("annotationSource", event.target.value)} /></label><label>Library type<input value={options.libraryType} onChange={(event) => updateOptions("libraryType", event.target.value)} /></label></div>
            <fieldset><legend>Alignment reference paths</legend><p className="helper-copy">Reference FASTA, its separately supplied FASTA index, and a matching minimap2 index are required for the ONT workflow.</p>{referenceFileField("Reference FASTA", "referenceFasta", "/references/GRCm38p6.fa", true)}{referenceFileField("Reference FASTA index (.fai)", "referenceFai", "/references/GRCm38p6.fa.fai", true)}{referenceFileField("minimap2 index", "minimap2Index", "/references/GRCm38p6.mmi", true)}</fieldset>
            <fieldset><legend>Coverage and methylation parameters</legend><p className="helper-copy">These settings are saved in the manifest. Changing them invalidates the affected stage outputs; scientific interpretation remains single-sample and descriptive.</p><div className="field-triple"><label>Window size (bases)<input type="number" min="1" step="1" value={options.coverageWindowSize} onChange={(event) => updateOptions("coverageWindowSize", Number(event.target.value))} /></label><label>Modkit filter percentile (less than 1)<input type="number" min="0" max="0.99" step="0.01" value={options.modkitFilterPercentile} onChange={(event) => updateOptions("modkitFilterPercentile", Number(event.target.value))} /></label><label>Maximum pileup depth<input type="number" min="1" max="60000" step="1" value={options.modkitMaxDepth} onChange={(event) => updateOptions("modkitMaxDepth", Number(event.target.value))} /></label></div><div className="field-pair"><label>Minimum valid CpG coverage<input type="number" min="1" step="1" value={options.explorationMinValidCoverage} onChange={(event) => updateOptions("explorationMinValidCoverage", Number(event.target.value))} /></label><label>Minimum measured CpGs per feature<input type="number" min="1" step="1" value={options.explorationMinFeatureCpgs} onChange={(event) => updateOptions("explorationMinFeatureCpgs", Number(event.target.value))} /></label></div></fieldset>
            <div className="field-triple"><label>Profile<select value={options.executionProfile} onChange={(event) => updateOptions("executionProfile", event.target.value as OptionsState["executionProfile"])}><option value="local">Local tools</option></select></label><label>Total workflow CPU budget<input type="number" min="1" value={options.cpus} onChange={(event) => updateOptions("cpus", Number(event.target.value))} /></label><label>Total workflow RAM budget (GiB)<input type="number" min="1" value={options.memoryGb} onChange={(event) => updateOptions("memoryGb", Number(event.target.value))} /></label></div>
          </section>
        );
        return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 4</p><h2>Confirm experimental design</h2></div></div>
            <div className="concept-explainer"><p><strong>Experimental design</strong> tells the analysis which biological group each sample belongs to.</p><ul><li><strong>Condition:</strong> the required group being studied, such as Control or Treated.</li><li><strong>Biological replicate:</strong> optional subject/specimen metadata retained for future paired analyses. The current unpaired analysis does not use it.</li><li><strong>Batch:</strong> optional provenance for when or where a sample was processed. It is recorded, but the current analysis does not adjust for batch.</li></ul><p>Missus Tom never guesses these biological facts from filenames.</p></div>
            <div className="category-assignment-panel">
              <div className="category-assignment-heading"><div><strong>Bulk-assign experimental settings</strong><p>Find included samples by text in their identifiers, then assign any combination of condition, biological replicate, batch, and intervention. Matching ignores letter case and separators such as <code>_</code> and <code>-</code>.</p></div><button className="text-button" type="button" onClick={useSampleIdsAsReplicates}>Use each sample ID as its replicate ID</button></div>
              <div className="table-scroll"><table className="category-assignment-table"><thead><tr><th>Sample ID contains</th><th>Condition</th><th>Biological replicate (optional)</th><th>Batch</th><th>Intervention</th><th>Matches</th><th></th></tr></thead><tbody><tr><td><input value={assignmentSearch} onChange={(event) => setAssignmentSearch(event.target.value)} placeholder="e.g. O_D1" /></td><td><input value={assignmentCondition} onChange={(event) => setAssignmentCondition(event.target.value)} placeholder="Optional" /></td><td><input value={assignmentReplicate} onChange={(event) => setAssignmentReplicate(event.target.value)} placeholder="Optional" /></td><td><input value={assignmentBatch} onChange={(event) => setAssignmentBatch(event.target.value)} placeholder="Optional" /></td><td><input value={assignmentIntervention} onChange={(event) => setAssignmentIntervention(event.target.value)} placeholder="Optional" /></td><td><strong>{assignmentMatchCount}</strong></td><td><button className="button primary" type="button" onClick={applyDesignAssignment} disabled={!assignmentSearch.trim() || assignmentMatchCount === 0 || (!assignmentCondition.trim() && !assignmentReplicate.trim() && !assignmentBatch.trim() && !assignmentIntervention.trim())}>Apply</button></td></tr></tbody></table></div>
              <p className="helper-copy">Example: search for <code>OD1</code> and enter condition <code>OD1</code>. For replicates, search for a replicate-specific name fragment and enter its replicate ID. New values overwrite those fields for matching samples, so review the assignments below. Use the sample-ID shortcut only when every sample represents a separate biological specimen.</p>
            </div>
            <div className="metadata-import-panel">
              <div><strong>Import experimental metadata</strong><p><strong>CSV requirement:</strong> the file MUST include <code>SampleID</code>, <code>Condition</code>, and <code>Batch</code> columns.</p><small><code>Patient</code> maps to biological replicate, and <code>Intervention</code> is imported for filtered comparisons. Column matching ignores letter case; legacy sample-ID separators and suffixes are normalized and reported.</small></div>
              <button className="button secondary" type="button" onClick={() => void importMetadataCsv()} disabled={busy === "metadata-csv" || samples.length === 0}>{busy === "metadata-csv" ? "Importing…" : "Select metadata CSV…"}</button>
            </div>
            {metadataImport && <div className={metadataImport.unmatchedSamples.length || metadataImport.unusedRows.length || metadataImport.warnings.length ? "warning-list metadata-import-result" : "success-message metadata-import-result"}><strong>Imported metadata for {metadataImport.matched} sample(s)</strong><p><code>{metadataImport.path}</code></p>{metadataImport.unmatchedSamples.length > 0 && <p>No matching CSV row for: {metadataImport.unmatchedSamples.slice(0, 8).join(", ")}{metadataImport.unmatchedSamples.length > 8 ? ` (+${metadataImport.unmatchedSamples.length - 8} more)` : ""}</p>}{metadataImport.unusedRows.length > 0 && <p>Unused CSV rows, including superseded legacy duplicates: {metadataImport.unusedRows.slice(0, 8).join(", ")}{metadataImport.unusedRows.length > 8 ? ` (+${metadataImport.unusedRows.length - 8} more)` : ""}</p>}{metadataImport.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div>}
            <div className="design-list">{samples.filter((sample) => sample.included).map((sample, index) => {
              const realIndex = samples.indexOf(sample);
              return <article className="design-row" key={`${sample.sample_id}-${index}`}><strong>{sample.sample_id}</strong><label>Condition<input value={sample.condition} onChange={(event) => updateSample(realIndex, "condition", event.target.value)} /></label><label>Biological replicate (optional)<input value={sample.biological_replicate} onChange={(event) => updateSample(realIndex, "biological_replicate", event.target.value)} /></label><label>Batch<input value={sample.batch ?? ""} onChange={(event) => updateSample(realIndex, "batch", event.target.value || null)} /></label><label>Intervention<input value={typeof sample.covariates.intervention === "string" ? sample.covariates.intervention : ""} onChange={(event) => updateSample(realIndex, "covariates", { ...sample.covariates, intervention: event.target.value || null })} /></label></article>;
            })}</div>
            {groups.length > 0 && <div className="group-summary"><strong>Current groups</strong>{groups.map((group) => <span key={group}>{group}: {samples.filter((sample) => sample.included && sample.condition.trim() === group).length} sample(s)</span>)}</div>}
          </section>
        );
      case 4:
        if (isOntPipeline) return (
          <section className="wizard-card form-stack">
            <div className="section-heading"><div><p className="eyebrow">Step 5</p><h2>Optional annotation exploration</h2></div></div>
            <p className="helper-copy">No existing figures or reports are required. The pipeline generates its own applicable plots and tables from your BAMs. Leave these fields empty for alignment, QC, coverage, and methylation analysis. To add annotation-based exploration, supply all four matching mouse annotation resources below; these describe genomic features, not prior analysis results.</p>
            <fieldset><legend>Optional annotation set (all four or none)</legend>{referenceFileField("GENCODE GFF3", "gencodeGff3", "/references/gencode.vM25.annotation.gff3.gz")}{referenceFileField("CpG islands JSON", "cpgIslands", "/references/cpg_islands.json")}{referenceFileField("cCRE CSV table", "ccreTable", "/references/ccre.csv")}{referenceFileField("Intergenic BED", "intergenicBed", "/references/intergenic.bed")}</fieldset>
            <fieldset><legend>Optional sequencing provenance</legend><p className="helper-copy">An existing instrument report may be retained as provenance, but is not needed to run analysis.</p>{referenceFileField("ONT instrument report (optional)", "ontInstrumentReport", "/data/ont/report_run.html")}</fieldset>
          </section>
        );
        return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 5</p><h2>Build comparisons</h2></div></div>
            <div className="concept-explainer"><p><strong>Comparisons</strong> specify the questions DESeq2 should test. Each comparison uses two conditions from the experimental design and produces its own differential-expression tables and plots.</p><p><strong>Numerator − denominator:</strong> for Treated versus Control, positive log2 fold change means higher expression in Treated; negative means higher in Control.</p></div>
            {groups.length < 2 ? <div className="warning-list">Assign at least two conditions in the experimental design step.</div> : <div className="comparison-builder filtered-comparison-builder"><label>Numerator / test group<select value={numerator} onChange={(event) => setNumerator(event.target.value)}><option value="">Choose group</option>{groups.map((group) => <option key={group}>{group}</option>)}</select></label><span className="direction-mark" aria-hidden="true">versus</span><label>Denominator / reference group<select value={denominator} onChange={(event) => setDenominator(event.target.value)}><option value="">Choose group</option>{groups.map((group) => <option key={group}>{group}</option>)}</select></label><label>Intervention filter<select value={comparisonIntervention} onChange={(event) => setComparisonIntervention(event.target.value)}><option value="">All interventions</option>{interventions.map((intervention) => <option key={intervention}>{intervention}</option>)}</select></label><button className="button primary" type="button" onClick={addComparison}>Add comparison</button></div>}
            <div className="comparison-list">{comparisons.length === 0 ? <p className="empty-copy">No comparisons requested.</p> : comparisons.map((comparison) => <article key={comparison.comparison_id}><div><strong>{comparison.numerator} <span>−</span> {comparison.denominator}</strong><p>{comparison.label}{comparison.intervention ? ` · Intervention: ${comparison.intervention}` : ""}</p></div><button type="button" className="text-button danger" onClick={() => removeComparison(comparison.comparison_id)}>Remove</button></article>)}</div>
          </section>
        );
      case 5:
        if (isOntPipeline) return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 6</p><h2>Preflight validation</h2></div><button className="button primary" type="button" onClick={validate} disabled={busy === "validate"}>{busy === "validate" ? "Validating…" : "Run project checks"}</button></div>
            <p className="helper-copy">Blocking failures prevent saving. Warnings do not.</p>
            {validation && <div className={validation.valid ? "validation-summary valid" : "validation-summary invalid"}><strong>{validation.valid ? "Manifest valid" : "Validation failed"}</strong><span>{validation.checks.filter((check) => check.status === "blocking_failure").length} blocking · {validation.checks.filter((check) => check.status === "warning").length} warning</span></div>}
            <CheckList checks={validation?.checks ?? []} />
          </section>
        );
        return (
          <section className="wizard-card form-stack">
            <div className="section-heading"><div><p className="eyebrow">Step 6</p><h2>Pipeline options</h2></div></div>
            <p className="helper-copy">{startStage === "analysis" ? "Analysis-only execution requires existing Kallisto abundance tables and a human BioMart mapping." : "Full execution supports human paired-end libraries with a supplied Kallisto index and BioMart mapping."}</p>
            <div className="field-pair"><label>Organism<input value={options.organism} onChange={(event) => updateOptions("organism", event.target.value)} /></label><label>Reference genome<input value={options.referenceGenome} onChange={(event) => updateOptions("referenceGenome", event.target.value)} /></label></div>
            <div className="field-pair"><label>Annotation source<input value={options.annotationSource} onChange={(event) => updateOptions("annotationSource", event.target.value)} /></label><label>Library type<select value={options.libraryType} onChange={(event) => updateOptions("libraryType", event.target.value)}><option>total RNA</option><option>lncRNA</option><option>mRNA</option><option>other (confirm)</option></select></label></div>
            {startStage === "quantification" && <div className="field-pair"><label>Read layout<select value={options.readLayout} onChange={(event) => updateOptions("readLayout", event.target.value as OptionsState["readLayout"])}><option value="paired-end">Paired-end</option><option value="single-end">Single-end</option></select></label><label>Strandedness<select value={options.strandedness} onChange={(event) => updateOptions("strandedness", event.target.value as OptionsState["strandedness"])}><option value="unknown">Unknown (confirm)</option><option value="reverse">Reverse / RF</option><option value="forward">Forward / FR</option><option value="unstranded">Unstranded</option></select></label></div>}
            <fieldset><legend>Reference resource paths</legend><p className="helper-copy">{startStage === "analysis" ? "The human BioMart table must match the transcript annotation used for the supplied Kallisto results." : "Kallisto index and BioMart table are required. FASTA and GTF are retained as project provenance."}</p>{startStage === "quantification" && referenceFileField("Kallisto index", "kallistoIndex", "/references/transcripts.idx", true)}{referenceFileField("BioMart table", "biomart", "/references/biomart.tsv", true)}{startStage === "quantification" && <>{referenceFileField("Transcriptome FASTA", "transcriptomeFasta", "/references/transcripts.fa")}{referenceFileField("Annotation GTF", "annotationGtf", "/references/annotation.gtf")}</>}</fieldset>
            <fieldset><legend>{startStage === "analysis" ? "Analysis" : "Trimming and analysis"}</legend>{startStage === "quantification" && <><div className="field-pair"><label>R1 adapter<input value={options.adapterR1} onChange={(event) => updateOptions("adapterR1", event.target.value)} /></label><label>R2 adapter<input value={options.adapterR2} onChange={(event) => updateOptions("adapterR2", event.target.value)} /></label></div><div className="field-pair"><label>Trim quality<input type="number" min="0" max="50" value={options.trimQuality} onChange={(event) => updateOptions("trimQuality", Number(event.target.value))} /></label><label>Minimum read length<input type="number" min="1" value={options.minimumReadLength} onChange={(event) => updateOptions("minimumReadLength", Number(event.target.value))} /></label></div></>}<div className="field-triple"><label>Minimum group size<input type="number" min="2" value={options.minimumGroupSize} onChange={(event) => updateOptions("minimumGroupSize", Number(event.target.value))} /></label><label>Adjusted p-value<input type="number" min="0" max="1" step="0.01" value={options.adjustedPValue} onChange={(event) => updateOptions("adjustedPValue", Number(event.target.value))} /></label><label>Absolute log2 fold change<input type="number" min="0" step="0.05" value={options.absoluteLog2FoldChange} onChange={(event) => updateOptions("absoluteLog2FoldChange", Number(event.target.value))} /></label></div></fieldset>
            <div className="field-triple"><label>Profile<select value={options.executionProfile} onChange={(event) => updateOptions("executionProfile", event.target.value as OptionsState["executionProfile"])}><option value="local">Local tools</option><option value="docker">Docker (regression)</option></select></label><label>Total workflow CPU budget<input type="number" min="1" value={options.cpus} onChange={(event) => updateOptions("cpus", Number(event.target.value))} /></label><label>Total workflow RAM budget (GiB)<input type="number" min="1" value={options.memoryGb} onChange={(event) => updateOptions("memoryGb", Number(event.target.value))} /></label></div>
            <p className="field-help">These limits cover the workflow as a whole. Leave CPU and RAM available for the desktop and other local work.</p>
          </section>
        );
      case 6:
        if (isOntPipeline) return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 7</p><h2>Review and save</h2></div></div>
            <div className="review-grid"><dl><dt>Project</dt><dd>{details.projectName || "—"}</dd><dt>Pipeline</dt><dd>ONT (Oxford Nanopore) Analysis (mouse)</dd><dt>Input</dt><dd>{details.inputDirectory || "—"}</dd><dt>Output</dt><dd>{details.outputDirectory || "—"}</dd><dt>Organism</dt><dd>{options.organism}</dd><dt>Reference</dt><dd>{options.referenceGenome} · {options.annotationSource}</dd></dl><dl><dt>Included samples</dt><dd>{samples.filter((sample) => sample.included).length}</dd><dt>BAM files</dt><dd>{samples.filter((sample) => sample.included).reduce((total, sample) => total + sample.ont_bam_files.length, 0)}</dd><dt>Library</dt><dd>single-end · unknown</dd><dt>Workflow budget</dt><dd>{options.cpus} CPUs · {options.memoryGb} GiB RAM</dd><dt>Execution</dt><dd>{options.executionProfile}</dd></dl></div>
            {!validation?.valid && <div className="warning-list"><strong>Validation required</strong><p>Return to preflight and resolve blocking failures before saving.</p></div>}
            {savedPath && <div className="success-message" role="status">Saved manifest: <code>{savedPath}</code></div>}
            <div className="save-panel"><div><strong>Save manifest</strong><p>BAM files are not copied. A command preview is generated.</p></div><button className="button primary large" type="button" disabled={!validatedManifest || busy === "save"} onClick={saveAndPlan}>{busy === "save" ? "Saving…" : "Save manifest & build run plan"}</button></div>
          </section>
        );
        return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 7</p><h2>Preflight validation</h2></div><button className="button primary" type="button" onClick={validate} disabled={busy === "validate"}>{busy === "validate" ? "Validating…" : "Run project checks"}</button></div>
            <p className="helper-copy">Blocking failures prevent saving. Warnings do not.</p>
            {validation && <div className={validation.valid ? "validation-summary valid" : "validation-summary invalid"}><strong>{validation.valid ? "Manifest valid" : "Validation failed"}</strong><span>{validation.checks.filter((check) => check.status === "blocking_failure").length} blocking · {validation.checks.filter((check) => check.status === "warning").length} warning</span></div>}
            <CheckList checks={validation?.checks ?? []} />
          </section>
        );
      default:
        return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 8</p><h2>Review and save</h2></div></div>
            <div className="review-grid"><dl><dt>Project</dt><dd>{details.projectName || "—"}</dd><dt>Starting point</dt><dd>{startStage === "analysis" ? "Existing Kallisto results" : "FASTQ quantification"}</dd><dt>Input</dt><dd>{details.inputDirectory || "—"}</dd><dt>Output</dt><dd>{details.outputDirectory || "—"}</dd><dt>Organism</dt><dd>{options.organism}</dd><dt>Reference</dt><dd>{options.referenceGenome} · {options.annotationSource}</dd></dl><dl><dt>Included samples</dt><dd>{samples.filter((sample) => sample.included).length}</dd><dt>Comparisons</dt><dd>{comparisons.length}</dd><dt>Library</dt><dd>{options.libraryType}{startStage === "quantification" ? ` · ${options.readLayout} · ${options.strandedness}` : ""}</dd><dt>Workflow budget</dt><dd>{options.cpus} CPUs · {options.memoryGb} GiB RAM</dd><dt>Execution</dt><dd>{options.executionProfile}</dd></dl></div>
            {!validation?.valid && <div className="warning-list"><strong>Validation required</strong><p>Return to preflight and resolve blocking failures before saving.</p></div>}
            {savedPath && <div className="success-message" role="status">Saved manifest: <code>{savedPath}</code></div>}
            <div className="save-panel"><div><strong>Save manifest</strong><p>FASTQ files are not copied. A command preview is generated.</p></div><button className="button primary large" type="button" disabled={!validatedManifest || busy === "save"} onClick={saveAndPlan}>{busy === "save" ? "Saving…" : "Save manifest & build run plan"}</button></div>
          </section>
        );
    }
  };

  return (
    <div className="page-stack wizard-page">
      <header className="page-header">
        <div><p className="eyebrow">New {isOntPipeline ? "ONT analysis" : "bulk RNA-seq"} project</p><h1>{details.projectName || "Untitled project"}</h1><p className="lede">Step {step + 1} of {steps.length} · {steps[step]}</p></div>
        <div className="page-header-actions"><button className="button secondary" type="button" onClick={() => void importSettings()} disabled={busy === "import-settings"}>{busy === "import-settings" ? "Importing…" : "Import settings"}</button><button className="button secondary" type="button" onClick={() => void exportSettings()} disabled={busy === "export-settings"}>{busy === "export-settings" ? "Exporting…" : "Export settings"}</button><span className="draft-chip">Unsaved</span><small>Exports include local paths and sample IDs.</small></div>
      </header>

      {importPath && <div className="warning-list settings-export-success" role="status">Settings imported from <code>{importPath}</code>. Run validation again before saving.</div>}
      {exportPath && <div className="success-message settings-export-success" role="status">Settings exported to <code>{exportPath}</code></div>}

      <div className="wizard-layout">
        <ol className="wizard-steps" aria-label="Project setup steps">
          {steps.map((label, index) => (
            <li key={label} className={index === step ? "current" : index < step ? "complete" : ""}>
              <button type="button" onClick={() => setStep(index)} aria-current={index === step ? "step" : undefined}>
                <span>{index < step ? "✓" : index + 1}</span><strong>{label}</strong>
              </button>
            </li>
          ))}
        </ol>
        <div>
          {error && <div className="inline-error" role="alert"><strong>Error</strong><span>{error}</span><button type="button" aria-label="Dismiss error" onClick={() => setError("")}>×</button></div>}
          {renderStep()}
          <div className="wizard-actions"><button className="button secondary" type="button" onClick={() => setStep((current) => Math.max(0, current - 1))} disabled={step === 0}>Back</button><span>Unsaved changes are temporary.</span><button className="button primary" type="button" onClick={() => setStep((current) => Math.min(steps.length - 1, current + 1))} disabled={step === steps.length - 1}>Continue</button></div>
        </div>
      </div>
    </div>
  );
}
