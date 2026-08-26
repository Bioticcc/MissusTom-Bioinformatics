import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { FolderPreview } from "../components/FolderPreview";
import { openDirectory } from "../native";
import type { DirectoryPreview, ProjectManifest, RunPlan, RunRecord } from "../types";

function formatBytes(bytes: number) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 2 ? 1 : 0)} ${units[index]}`;
}

export function RunPlanScreen({
  manifest,
  plan,
  onStarted,
}: {
  manifest: ProjectManifest | null;
  plan: RunPlan | null;
  onStarted: (record: RunRecord) => void;
}) {
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [inputPreview, setInputPreview] = useState<DirectoryPreview | null>(null);
  const [outputPreview, setOutputPreview] = useState<DirectoryPreview | null>(null);

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

  const startRun = async () => {
    setStarting(true);
    setError("");
    try {
      const record = await apiRequest<RunRecord>("/api/v1/runs/start", {
        method: "POST",
        body: JSON.stringify({ manifest, resume: true }),
      });
      onStarted(record);
    } catch (reason) {
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
          <p className="lede">Local Docker execution with resumable Nextflow work.</p>
        </div>
        <div className="header-actions">
          <button className="button secondary" type="button" onClick={() => void openOutput()}>Open output folder</button>
          <button className="button primary" type="button" disabled={!plan.execution_enabled || starting} onClick={startRun}>{starting ? "Starting…" : "Run pipeline"}</button>
        </div>
      </header>

      {!plan.execution_enabled && (
        <section className="development-banner warning" role="status">
          <span className="notice-icon" aria-hidden="true">!</span>
          <div><strong>Execution unavailable</strong><p>Only the prepared human demo manifest is enabled for execution.</p></div>
        </section>
      )}
      {error && <div className="inline-error" role="alert">{error}</div>}

      <div className="summary-grid">
        <article className="metric-card"><span>Samples</span><strong>{manifest.samples.filter((sample) => sample.included).length}</strong></article>
        <article className="metric-card"><span>Comparisons</span><strong>{manifest.comparisons.length}</strong></article>
        <article className="metric-card"><span>Input size</span><strong>{formatBytes(plan.estimated_input_bytes)}</strong></article>
        <article className="metric-card"><span>Profile</span><strong>{plan.execution_profile}</strong></article>
      </div>

      {(inputPreview || outputPreview) && <div className="folder-preview-grid">
        {inputPreview && <FolderPreview label="Input folder" preview={inputPreview} />}
        {outputPreview && <FolderPreview label="Output folder" preview={outputPreview} />}
      </div>}

      <section className="panel">
        <div className="section-heading"><div><p className="eyebrow">Stages</p><h2>Pipeline map</h2></div><span className="count-pill">{plan.stages.length}</span></div>
        <div className="stage-list">
          {plan.stages.map((stage, index) => (
            <article className="stage-row" key={stage.stage_id}>
              <span className="stage-number">{String(index + 1).padStart(2, "0")}</span>
              <div><h3>{stage.name}</h3><p>{stage.description}</p><small>{stage.source_mapping}</small></div>
              <span className="stage-state">Planned</span>
            </article>
          ))}
        </div>
      </section>

      <div className="two-column">
        <section className="panel">
          <p className="eyebrow">Argument array</p>
          <h2>Generated command</h2>
          <pre className="command-preview" aria-label="Generated command argument array">
            {JSON.stringify(plan.command_preview, null, 2)}
          </pre>
        </section>
        <section className="panel destination-list">
          <p className="eyebrow">Output paths</p>
          <h2>Logs and results</h2>
          <dl><dt>Results</dt><dd>{plan.results_directory}</dd><dt>Logs</dt><dd>{plan.log_directory}</dd></dl>
          <h3>Validation notes</h3>
          <ul>{plan.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </section>
      </div>
    </div>
  );
}
