import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { openDirectory } from "../native";
import type { ResultArtifact, RunRecord } from "../types";

const categories: Array<[string, string]> = [
  ["qc", "QC reports"],
  ["trimmed_reads", "Trimmed reads"],
  ["counts", "Kallisto quantification"],
  ["differential_expression", "Differential expression"],
  ["figures", "Figures"],
  ["tables", "Tables"],
  ["workflow_reports", "Workflow reports"],
  ["logs", "Logs"],
  ["run_manifest", "Run manifest"],
];

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
}

export function Results({ activeRun }: { activeRun: RunRecord | null }) {
  const [artifacts, setArtifacts] = useState<ResultArtifact[]>([]);
  const [error, setError] = useState("");
  const [selectedRun, setSelectedRun] = useState<RunRecord | null>(activeRun);

  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const runs = await apiRequest<RunRecord[]>("/api/v1/runs");
        const selected = activeRun ?? runs[0];
        if (!selected) return;
        const files = await apiRequest<ResultArtifact[]>(`/api/v1/runs/${selected.job_identifier}/artifacts`);
        if (active) {
          setArtifacts(files);
          setSelectedRun(selected);
          setError("");
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Results could not be indexed.");
      }
    };
    void load();
    const timer = window.setInterval(load, 3_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [activeRun]);

  const openOutput = async () => {
    if (!selectedRun) return;
    try {
      await openDirectory(selectedRun.results_directory);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The output folder could not be opened.");
    }
  };

  return (
    <div className="page-stack">
      <header className="page-header"><div><p className="eyebrow">Project outputs</p><h1>Results</h1><p className="lede">Files written by the local workflow.</p></div>{selectedRun && <button className={selectedRun.status === "completed" ? "button primary large" : "button secondary"} type="button" onClick={() => void openOutput()}>Open output folder</button>}</header>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="results-grid">
        {categories.map(([key, label]) => {
          const files = artifacts.filter((artifact) => artifact.category === key);
          return <article className="panel result-category result-category-files" key={key}>
            <div className="result-icon" aria-hidden="true">□</div>
            <div><h2>{label}</h2>{files.length === 0 ? <p>No files</p> : <ul>{files.slice(0, 12).map((file) => (
              <li key={file.relative_path}><span>{file.relative_path}</span><small>{formatBytes(file.size_bytes)}</small></li>
            ))}</ul>}</div>
            <span className="count-pill">{files.length}</span>
          </article>;
        })}
      </section>
      {artifacts.length === 0 && <section className="development-banner subtle">
        <span className="notice-icon" aria-hidden="true">i</span>
        <div><strong>No result files indexed</strong><p>Files appear here after a workflow starts.</p></div>
      </section>}
    </div>
  );
}
