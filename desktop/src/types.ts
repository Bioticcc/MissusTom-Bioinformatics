export type ViewId = "dashboard" | "wizard" | "run-plan" | "jobs" | "results" | "settings";

export interface ErrorDetail {
  code: string;
  message: string;
  field?: string;
}

export interface ApiEnvelope<T> {
  success: boolean;
  data: T | null;
  errors: ErrorDetail[];
  meta: Record<string, unknown>;
}

export type CheckStatus = "passed" | "warning" | "blocking_failure" | "not_yet_configured";

export interface PreflightCheck {
  check_id: string;
  label: string;
  status: CheckStatus;
  message: string;
  details: Record<string, unknown>;
}

export interface SystemPreflight {
  ready_for_framework: boolean;
  ready_for_real_execution: boolean;
  checks: PreflightCheck[];
}

export interface ProposedSample {
  sample_id: string;
  r1_files: string[];
  r2_files: string[];
  lanes: string[];
  pairing_status: "paired" | "single" | "unmatched" | "ambiguous";
  warnings: string[];
  condition: string;
  biological_replicate: string;
  batch: string | null;
  included: boolean;
}

export interface FastqDiscoveryResult {
  directory: string;
  samples: ProposedSample[];
  files: Array<{ path: string; size_bytes: number; read: string; lane: string | null }>;
  unassigned_files: string[];
  warnings: string[];
  total_files: number;
  total_bytes: number;
}

export interface Comparison {
  comparison_id: string;
  numerator: string;
  denominator: string;
  label: string;
}

export interface ProjectManifest {
  schema_version: "1.0.0";
  project_name: string;
  project_identifier: string;
  created_at: string;
  input_directory: string;
  output_directory: string;
  pipeline_identifier: "bulk-rnaseq";
  pipeline_version: string;
  organism: string;
  reference_genome: string;
  annotation_source: string;
  reference_resources: Record<string, string>;
  library_type: string;
  read_layout: "paired-end" | "single-end";
  strandedness: "unstranded" | "forward" | "reverse" | "unknown";
  samples: Array<{
    sample_id: string;
    r1_files: string[];
    r2_files: string[];
    condition: string;
    biological_replicate: string;
    batch: string | null;
    covariates: Record<string, string | number | boolean | null>;
    included: boolean;
  }>;
  comparisons: Comparison[];
  parameters: Record<string, string | number | boolean | null>;
  resource_profile: { cpus: number; memory_gb: number; max_parallel_tasks: number };
  execution_profile: "local" | "docker" | "apptainer";
  application_version: string;
  pipeline_status: "draft" | "validated" | "planned" | "queued" | "preparing" | "running" | "completed" | "failed" | "cancelled";
}

export interface ProjectValidation {
  valid: boolean;
  manifest: ProjectManifest;
  checks: PreflightCheck[];
}

export interface PlannedStage {
  stage_id: string;
  name: string;
  description: string;
  status: string;
  resumable: boolean;
  source_mapping: string | null;
}

export interface RunPlan {
  project_identifier: string;
  pipeline_identifier: string;
  pipeline_version: string;
  execution_profile: string;
  execution_enabled: boolean;
  stages: PlannedStage[];
  command_preview: string[];
  estimated_input_bytes: number;
  log_directory: string;
  results_directory: string;
  warnings: string[];
}

export type RunStatus = "queued" | "preparing" | "running" | "completed" | "failed" | "cancelled";

export interface RunRecord {
  job_identifier: string;
  project_identifier: string;
  project_name: string;
  status: RunStatus;
  current_stage: string | null;
  command: string[];
  log_path: string;
  results_directory: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  exit_code: number | null;
  error_message: string | null;
  resume: boolean;
}

export interface RunLog {
  job_identifier: string;
  text: string;
  truncated: boolean;
}

export interface ResultArtifact {
  category: string;
  relative_path: string;
  size_bytes: number;
  modified_at: string;
}

export interface HumanDemoProject {
  manifest: ProjectManifest;
  plan: RunPlan;
}

export type DirectoryEntryKind = "file" | "directory" | "symlink" | "other";

export interface DirectoryEntry {
  name: string;
  kind: DirectoryEntryKind;
  file_type: string;
  size_bytes: number | null;
}

export interface DirectoryPreview {
  directory: string;
  total_entries: number;
  total_files: number;
  total_directories: number;
  total_bytes: number;
  contains_data: boolean;
  truncated: boolean;
  entries: DirectoryEntry[];
}
