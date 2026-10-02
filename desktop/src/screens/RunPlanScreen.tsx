import { useCallback, useEffect, useState } from "react";
import { apiRequest } from "../api";
import { FolderPreview } from "../components/FolderPreview";
import { PipelineDependencies } from "../components/PipelineDependencies";
import { openDirectory } from "../native";
import type { DirectoryPreview, ProjectManifest, RunPlan, RunRecord, RunStartStage } from "../types";

function formatBytes(bytes: number) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 2 ? 1 : 0)} ${units[index]}`;
}

const analysisOnlySkippedStages = new Set([
  "raw_read_qc",
  "adapter_trimming",
  "clean_read_qc",
  "quantification",
]);

export function RunPlanScreen({
  manifest,
  plan,
  onStarting,
  onStartFailed,
  onStarted,
}: {
  manifest: ProjectManifest | null;
  plan: RunPlan | null;
  onStarting: () => void | Promise<void>;
  onStartFailed: () => void;
  onStarted: (record: RunRecord) => void;
}) {
  const [starting, setStarting] = useState(false);
  const [resume, setResume] = useState(true);
  const configuredStartStage: RunStartStage = manifest?.parameters.start_stage === "analysis"
    ? "analysis"
    : "quantification";
  const [startStage, setStartStage] = useState<RunStartStage>(configuredStartStage);
  const [error, setError] = useState("");
  const [inputPreview, setInputPreview] = useState<DirectoryPreview | null>(null);
  const [outputPreview, setOutputPreview] = useState<DirectoryPreview | null>(null);
  const [refreshedPlan, setRefreshedPlan] = useState<RunPlan | null>(null);
  const isOntPipeline = manifest?.pipeline_identifier === "ont-analysis";
  const includedSamples = manifest?.samples.filter((sample) => sample.included) ?? [];
  const hasQuantificationReference = manifest?.reference_mode === "build"
    ? Boolean(
      manifest.reference_resources.transcriptome_fasta
      && manifest.reference_resources.annotation_gtf,
    )
    : Boolean(manifest?.reference_resources.kallisto_index);
  const canQuantify = Boolean(
    !isOntPipeline
    && includedSamples.length > 0
    && hasQuantificationReference
    && includedSamples.every(
      (sample) => sample.r1_files.length > 0 && sample.r1_files.length === sample.r2_files.length,
    ),
  );
  const canAnalyze = Boolean(
    !isOntPipeline
    && includedSamples.length > 0
    && includedSamples.every((sample) => Boolean(sample.abundance_tsv)),
  );

  useEffect(() => {
    setStartStage(configuredStartStage);
    setRefreshedPlan(null);
  }, [configuredStartStage, manifest?.project_identifier]);

  useEffect(() => {
    let active = true;
    const load = async () => {
      if (!manifest) return;
      try {
        const [input, output] = await Promise.all([
          apiRequest<DirectoryPreview>("/api/v1/directories/preview", {
            method: "POST",
            body: JSON.stringify({ directory: manifest.input_directory }),
          }),
          apiRequest<DirectoryPreview>("/api/v1/directories/preview", {
            method: "POST",
            body: JSON.stringify({ directory: manifest.output_directory }),
          }),
        ]);
        if (active) {
          setInputPreview(input);
          setOutputPreview(output);
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Folder previews could not be loaded.");
      }
    };
    void load();
    return () => { active = false; };
  }, [manifest]);

  const refreshRunPlan = useCallback(async () => {
    if (!manifest) return;
    const updated = await apiRequest<RunPlan>("/api/v1/runs/plan", {
      method: "POST",
      body: JSON.stringify({ manifest }),
    });
    setRefreshedPlan(updated);
  }, [manifest]);

  if (!manifest || !plan) {
    return (
      <div className="page-stack">
        <header className="page-header"><div><p className="eyebrow">Workflow</p><h1>Run plan</h1></div></header>
        <section className="panel empty-state">
          <div className="empty-orbit" aria-hidden="true">≡</div>
          <h2>No run plan</h2>
          <p>Validate and save a project to generate a command preview.</p>
        </section>
      </div>
    );
  }
  const currentPlan = refreshedPlan ?? plan;

  const startRun = async () => {
    setStarting(true);
    setError("");
    try {
      await onStarting();
      const record = await apiRequest<RunRecord>("/api/v1/runs/start", {
        method: "POST",
        body: JSON.stringify({ manifest, resume: isOntPipeline ? true : resume, start_stage: isOntPipeline ? "quantification" : startStage }),
      });
      onStarted(record);
    } catch (reason) {
      onStartFailed();
      // Do not clear the native busy state here: the backend may have accepted
      // the run even if its response was lost. App-level polling clears it only
      // after the authoritative run list confirms no active work.
      setError(reason instanceof Error ? reason.message : "The run could not be started.");
    } finally {
      setStarting(false);
    }
  };

  const openOutput = async () => {
    try {
      await openDirectory(manifest.output_directory);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The output folder could not be opened.");
    }
  };

  return (
    <div className="page-stack">
      <header className="page-header">
        <div>
          <p className="eyebrow">Project</p>
          <h1>{manifest.project_name}</h1>
          <p className="lede">{isOntPipeline ? "Local mouse modBAM analysis with validated, restartable stages." : "Local tools with resumable Nextflow work."}</p>
        </div>
        <div className="header-actions">
          <button className="button secondary" type="button" onClick={() => void openOutput()}>Open output folder</button>
          <button className="button primary" type="button" disabled={!currentPlan.execution_enabled || starting} onClick={startRun}>{starting ? "Starting…" : "Run pipeline"}</button>
        </div>
      </header>

      {!currentPlan.execution_enabled && (
        <section className="development-banner warning" role="status">
          <span className="notice-icon" aria-hidden="true">!</span>
          <div><strong>Execution unavailable</strong><p>Resolve the validation notes or enable local execution.</p></div>
        </section>
      )}
      {error && <div className="inline-error" role="alert">{error}</div>}
      <PipelineDependencies pipelineIdentifier={manifest.pipeline_identifier} onInstalled={refreshRunPlan} />

      {isOntPipeline ? <section className="panel"><h2>Restartable ONT execution</h2><p>Run all five stages, reusing only validated current outputs. Existing results and logs are retained. A forced rebuild is not exposed in this screen.</p></section> : <fieldset className="run-mode-panel" disabled={starting}>
        <legend>Run mode</legend>
        <label className={`run-mode-option${resume ? " selected" : ""}`}>
          <input
            type="radio"
            name="run-mode"
            checked={resume}
            onChange={() => setResume(true)}
          />
          <span>
            <strong>Resume previous run</strong>
            <small>Reuse completed tasks from the existing Nextflow work directory.</small>
          </span>
        </label>
        <label className={`run-mode-option${resume ? "" : " selected"}`}>
          <input
            type="radio"
            name="run-mode"
            checked={!resume}
            onChange={() => setResume(false)}
          />
          <span>
            <strong>Start from beginning</strong>
            <small>Run every pipeline task again without using cached completions.</small>
          </span>
        </label>
        <p className="run-mode-note">
          Starting from the beginning keeps existing work, results, and logs; Nextflow runs without <code>-resume</code>.
        </p>
      </fieldset>}

      {!isOntPipeline && <fieldset className="run-mode-panel" disabled={starting}>
        <legend>Pipeline scope</legend>
        <label className={`run-mode-option${startStage === "quantification" ? " selected" : ""}${canQuantify ? "" : " disabled"}`}>
          <input
            type="radio"
            name="start-stage"
            checked={startStage === "quantification"}
            disabled={!canQuantify}
            onChange={() => setStartStage("quantification")}
          />
          <span>
            <strong>Quantification + analysis</strong>
            <small>{canQuantify ? "Run FASTQ quality control, trimming, Kallisto index preparation or reuse, quantification, and downstream analysis." : "Unavailable: this project needs paired FASTQs plus FASTA/GTF build references or an existing Kallisto index."}</small>
          </span>
        </label>
        <label className={`run-mode-option${startStage === "analysis" ? " selected" : ""}${canAnalyze ? "" : " disabled"}`}>
          <input
            type="radio"
            name="start-stage"
            checked={startStage === "analysis"}
            disabled={!canAnalyze}
            onChange={() => setStartStage("analysis")}
          />
          <span>
            <strong>Analysis only</strong>
            <small>{canAnalyze ? "Skip FASTQ processing and use the selected per-sample Kallisto abundance tables." : "Unavailable: each included sample needs a selected abundance.tsv input."}</small>
          </span>
        </label>
        <p className="run-mode-note">
          Analysis only requires a selected <code>abundance.tsv</code> under the project input directory for every included sample.
        </p>
      </fieldset>}

      <div className="summary-grid">
        <article className="metric-card"><span>Samples</span><strong>{manifest.samples.filter((sample) => sample.included).length}</strong></article>
        <article className="metric-card"><span>{isOntPipeline ? "BAM files" : "Comparisons"}</span><strong>{isOntPipeline ? manifest.samples.filter((sample) => sample.included).reduce((total, sample) => total + sample.ont_bam_files.length, 0) : manifest.comparisons.length}</strong></article>
        <article className="metric-card"><span>Input size</span><strong>{formatBytes(currentPlan.estimated_input_bytes)}</strong></article>
        <article className="metric-card"><span>Profile</span><strong>{currentPlan.execution_profile}</strong></article>
      </div>

      {(inputPreview || outputPreview) && <div className="folder-preview-grid">
        {inputPreview && <FolderPreview label="Input folder" preview={inputPreview} />}
        {outputPreview && <FolderPreview label="Output folder" preview={outputPreview} />}
      </div>}

      <section className="panel">
        <div className="section-heading"><div><p className="eyebrow">Stages</p><h2>Pipeline map</h2></div><span className="count-pill">{currentPlan.stages.length}</span></div>
        <div className="stage-list">
          {currentPlan.stages.map((stage, index) => (
            <article className="stage-row" key={stage.stage_id}>
              <span className="stage-number">{String(index + 1).padStart(2, "0")}</span>
              <div><h3>{stage.name}</h3><p>{stage.description}</p><small>{stage.source_mapping}</small></div>
              {!isOntPipeline && startStage === "analysis" && analysisOnlySkippedStages.has(stage.stage_id) ? (
                <span className="stage-state skipped">Skipped</span>
              ) : (
                <span className="stage-state">Planned</span>
              )}
            </article>
          ))}
        </div>
      </section>

      <div className="two-column">
        <section className="panel">
          <p className="eyebrow">Argument array</p>
          <h2>Generated command</h2>
          <pre className="command-preview" aria-label="Generated command argument array">
            {JSON.stringify(
              currentPlan.command_preview.map((argument, index, command) => (
                !isOntPipeline && command[index - 1] === "--start_stage" ? startStage : argument
              )),
              null,
              2,
            )}
          </pre>
        </section>
        <section className="panel destination-list">
          <p className="eyebrow">Output paths</p>
          <h2>Logs and results</h2>
          <dl><dt>Results</dt><dd>{currentPlan.results_directory}</dd><dt>Logs</dt><dd>{currentPlan.log_directory}</dd></dl>
          <h3>Validation notes</h3>
          <ul>{currentPlan.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </section>
      </div>
    </div>
  );
}
