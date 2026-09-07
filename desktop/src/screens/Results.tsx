import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api";
import { openDirectory } from "../native";
import { RequestCoordinator } from "../requestCoordinator";
import type { ResultArtifact, RunRecord } from "../types";

const categories: Array<[string, string]> = [
  ["qc", "QC reports"], ["trimmed_reads", "Trimmed reads"], ["counts", "Kallisto quantification"],
  ["differential_expression", "Differential expression"], ["figures", "Figures"], ["tables", "Tables"],
  ["workflow_reports", "Workflow reports"], ["logs", "Logs"], ["run_manifest", "Run manifest"],
];
const pollableStatuses = new Set(["queued", "preparing", "running", "cancelling"]);
const POLL_MS = 10_000;

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
}

export function Results({ activeRun }: { activeRun: RunRecord | null }) {
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [artifacts, setArtifacts] = useState<ResultArtifact[]>([]);
  const [selectedRun, setSelectedRun] = useState<RunRecord | null>(null);
  const [category, setCategory] = useState("all");
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const selectedId = useRef<string | null>(activeRun?.job_identifier ?? null);
  const coordinator = useRef(new RequestCoordinator());
  const timer = useRef<number | undefined>();
  const mounted = useRef(false);
  const activeRunId = activeRun?.job_identifier;

  const clearScheduledScan = useCallback(() => {
    if (timer.current !== undefined) window.clearTimeout(timer.current);
    timer.current = undefined;
  }, []);

  const scan = useCallback(async (preferredId?: string) => {
    clearScheduledScan();
    const ticket = coordinator.current.start();
    if (ticket.isCurrent() && mounted.current) setRefreshing(true);
    try {
      const records = await apiRequest<RunRecord[]>("/api/v1/runs", { signal: ticket.signal });
      if (!ticket.isCurrent() || !mounted.current) return;
      const selected = records.find((run) => run.job_identifier === (preferredId ?? selectedId.current))
        ?? records.find((run) => run.job_identifier === activeRunId)
        ?? records[0]
        ?? null;
      selectedId.current = selected?.job_identifier ?? null;
      setRuns(records);
      setSelectedRun(selected);
      setArtifacts([]);
      if (selected) {
        const files = await apiRequest<ResultArtifact[]>(`/api/v1/runs/${selected.job_identifier}/artifacts`, { signal: ticket.signal });
        if (!ticket.isCurrent() || !mounted.current || selectedId.current !== selected.job_identifier) return;
        setArtifacts(files);
      }
      if (!ticket.isCurrent() || !mounted.current) return;
      setError("");
      if (selected && pollableStatuses.has(selected.status)) {
        timer.current = window.setTimeout(() => void scan(selected.job_identifier), POLL_MS);
      }
    } catch (reason) {
      if (ticket.isCurrent() && mounted.current) {
        setError(reason instanceof Error ? reason.message : "Results could not be refreshed.");
        timer.current = window.setTimeout(() => void scan(preferredId), POLL_MS);
      }
    } finally {
      if (ticket.isCurrent() && mounted.current) setRefreshing(false);
      ticket.finish();
    }
  }, [activeRunId, clearScheduledScan]);

  useEffect(() => {
    mounted.current = true;
    const requestCoordinator = coordinator.current;
    void scan();
    return () => {
      mounted.current = false;
      clearScheduledScan();
      requestCoordinator.abort();
    };
  }, [clearScheduledScan, scan]);

  const selectRun = (run: RunRecord) => {
    selectedId.current = run.job_identifier;
    setSelectedRun(run);
    setArtifacts([]);
    setError("");
    void scan(run.job_identifier);
  };

  const openOutput = async () => {
    if (!selectedRun) return;
    try { await openDirectory(selectedRun.results_directory); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "The output folder could not be opened."); }
  };
  const visibleCategories = category === "all" ? categories : categories.filter(([key]) => key === category);

  return (
    <div className="page-stack">
      <header className="page-header"><div><p className="eyebrow">Project outputs</p><h1>Results</h1><p className="lede">Files currently in this project’s output folder. Reruns update this folder.</p></div><div className="header-actions">{selectedRun && <button className="button secondary" type="button" onClick={() => void openOutput()}>Open output folder</button>}<button className="button primary" type="button" disabled={!selectedRun || refreshing} onClick={() => { if (selectedRun) void scan(selectedRun.job_identifier); }}>{refreshing ? "Refreshing…" : "Refresh files"}</button></div></header>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="panel results-toolbar">
        <label>Run<select value={selectedRun?.job_identifier ?? ""} onChange={(event) => { const run = runs.find((item) => item.job_identifier === event.target.value); if (run) selectRun(run); }} disabled={runs.length === 0}>{runs.length === 0 ? <option value="">No runs available</option> : runs.map((run) => <option key={run.job_identifier} value={run.job_identifier}>{run.project_name} · {run.status} · {new Date(run.created_at).toLocaleString()}</option>)}</select></label>
        <label>File group<select value={category} onChange={(event) => setCategory(event.target.value)}><option value="all">All file groups</option>{categories.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      </section>
      <section className="results-grid">
        {visibleCategories.map(([key, label]) => {
          const files = artifacts.filter((artifact) => artifact.category === key);
          const expanded = expandedCategories.has(key);
          const shownFiles = expanded ? files : files.slice(0, 8);
          return <article className="panel result-category result-category-files" key={key}>
            <div className="result-icon" aria-hidden="true">□</div><div><h2>{label}</h2>{files.length === 0 ? <p>No files</p> : <><ul>{shownFiles.map((file) => <li key={file.relative_path}><span>{file.relative_path}</span><small>{formatBytes(file.size_bytes)}</small></li>)}</ul>{files.length > 8 && <button type="button" className="text-button" onClick={() => setExpandedCategories((current) => { const next = new Set(current); if (next.has(key)) next.delete(key); else next.add(key); return next; })}>{expanded ? "Show fewer" : `Show ${files.length - 8} more`}</button>}</>}</div><span className="count-pill">{files.length}</span>
          </article>;
        })}
      </section>
      {artifacts.length === 0 && <section className="development-banner subtle"><span className="notice-icon" aria-hidden="true">i</span><div><strong>No result files indexed</strong><p>Refresh files after a workflow writes output.</p></div></section>}
    </div>
  );
}
