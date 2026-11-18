import type { ResultArtifact, RunRecord } from "./types";

const bulkCategories: Array<[string, string]> = [
  ["qc", "QC reports"], ["trimmed_reads", "Trimmed reads"], ["counts", "Kallisto quantification"],
  ["differential_expression", "Differential expression"], ["figures", "Figures"], ["tables", "Tables"],
  ["workflow_reports", "Workflow reports"], ["logs", "Logs"], ["run_manifest", "Run manifest"],
];
const ontCategories: Array<[string, string]> = [
  ["project_qc", "Project QC overview"],
  ["methylation_exploration", "Figures and reports"], ["methylation", "Methylation calls and summaries"],
  ["qc_coverage", "Sequencing QC and coverage"], ["alignment_qc", "Alignment QC"],
  ["alignment", "Aligned reads"], ["manifests", "Input manifests"],
  ["workflow_configuration", "Workflow configuration"], ["logs", "Logs"], ["run_manifest", "Run manifest"],
];

export function resultCategories(pipeline: string | null | undefined): Array<[string, string]> {
  return pipeline === "ont-analysis" ? ontCategories : bulkCategories;
}

/** Use published artifacts to distinguish per-sample ONT runs from legacy layouts. */
export function outputDirectoryForRun(run: Pick<RunRecord, "pipeline_identifier" | "results_directory">, artifacts: ResultArtifact[]): string {
  if (artifacts.some((file) => file.category === "project_qc")) return run.results_directory;
  if (run.pipeline_identifier === "ont-analysis" && artifacts.some((file) =>
    file.relative_path.replaceAll("\\", "/").startsWith("results/samples/"))) {
    return `${run.results_directory.replace(/\/+$/, "")}/samples`;
  }
  return run.results_directory;
}
