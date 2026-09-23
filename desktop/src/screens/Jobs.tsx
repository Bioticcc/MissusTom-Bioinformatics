import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api";
import { LiveCommandLog } from "../components/LiveCommandLog";
import { openDirectory } from "../native";
import type { RunLog, RunRecord, RunStatus } from "../types";

const pollableStatuses = new Set<RunStatus>(["queued", "preparing", "running", "cancelling"]);
const terminalStatuses = new Set<RunStatus>(["completed", "failed", "cancelled", "interrupted"]);
const cancellableStatuses = new Set<RunStatus>(["queued", "preparing", "running"]);
const POLL_MS = 2_000;

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

function needsStatusRefresh(run: RunRecord) {
  return pollableStatuses.has(run.status) || run.holds_admission;
}

export function Jobs({ activeRun }: { activeRun: RunRecord | null }) {
  const [runs, setRuns] = useState<RunRecord[]>(activeRun ? [activeRun] : []);
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const [lastOutputByJob, setLastOutputByJob] = useState<Record<string, string | null>>({});
  const priorStatuses = useRef<Record<string, RunStatus>>({});
  const mounted = useRef(false);

  const fetchRunLog = useCallback((jobIdentifier: string) => (
    offset: number,
    signal: AbortSignal,
  ) => apiRequest<RunLog>(`/api/v1/runs/${jobIdentifier}/logs?offset=${offset}`, { signal }).then((log) => {
    const lastOutput = log.last_output_at ?? null;
    if (lastOutput) {
      setLastOutputByJob((current) => (
        current[jobIdentifier] === lastOutput
          ? current
          : { ...current, [jobIdentifier]: lastOutput }
      ));
    }
    return {
      text: log.text,
      next_offset: log.next_offset ?? offset + (log.text?.length ?? 0),
      bytes_available: log.bytes_available ?? 0,
      truncated: log.truncated,
      last_output_at: log.last_output_at ?? null,
    };
  }), []);

  useEffect(() => {
    mounted.current = true;
    let timer: number | undefined;
    let controller: AbortController | undefined;
    const refresh = async () => {
      controller = new AbortController();
      try {
        const records = await apiRequest<RunRecord[]>("/api/v1/runs", { signal: controller.signal });
        if (!mounted.current) return;
        priorStatuses.current = Object.fromEntries(records.map((record) => [record.job_identifier, record.status]));
        setRuns(records);
        setError("");
        if (mounted.current && records.some(needsStatusRefresh)) timer = window.setTimeout(() => void refresh(), POLL_MS);
      } catch (reason) {
        if (mounted.current && !controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Jobs could not be loaded.");
          timer = window.setTimeout(() => void refresh(), POLL_MS);
        }
      }
    };
    void refresh();
    return () => {
      mounted.current = false;
      controller?.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  const cancel = async (identifier: string) => {
    setCancelling((current) => new Set(current).add(identifier));
    setError("");
    try {
      const record = await apiRequest<RunRecord>(`/api/v1/runs/${identifier}/cancel`, { method: "POST" });
      if (mounted.current) setRuns((current) => current.map((run) => run.job_identifier === identifier ? record : run));
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : "The job could not be cancelled.");
    } finally {
      if (mounted.current) setCancelling((current) => { const next = new Set(current); next.delete(identifier); return next; });
    }
  };

  return (
    <div className="page-stack">
      <header className="page-header"><div><p className="eyebrow">Execution status</p><h1>Jobs</h1><p className="lede">Local Nextflow job state and logs.</p></div></header>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="panel">
        {runs.length === 0 ? <div className="empty-state"><div className="empty-orbit" aria-hidden="true">◷</div><h2>No jobs</h2><p>No job records exist.</p></div> : <div className="job-list">
          {runs.map((run) => {
            const retryCleanup = run.status === "interrupted" && run.holds_admission;
            const busy = cancelling.has(run.job_identifier) || run.status === "cancelling";
            const logActive = pollableStatuses.has(run.status);
            return <article className="job-card" key={run.job_identifier}>
              <div className="section-heading"><div><h2>{run.project_name}</h2><p>{run.current_stage ?? "No stage reported"}</p></div><span className={`job-state state-${run.status}`}>{run.status}</span></div>
              <dl className="job-metadata"><dt>Started</dt><dd>{formatTime(run.started_at)}</dd><dt>Finished</dt><dd>{formatTime(run.finished_at)}</dd><dt>Pipeline</dt><dd>{run.pipeline_identifier === "ont-analysis" ? "ONT analysis" : run.pipeline_identifier === "bulk-rnaseq" ? "Bulk RNA-seq" : "Configured workflow"}</dd><dt>Run scope</dt><dd>{run.pipeline_identifier === "ont-analysis" ? "Configured ONT workflow" : run.start_stage === "analysis" ? "Analysis only" : "Quantification + analysis"}</dd><dt>Exit code</dt><dd>{run.exit_code ?? "—"}</dd></dl>
              {run.error_message && <p className="inline-error">{run.error_message}</p>}
              {(cancellableStatuses.has(run.status) || retryCleanup) && <button type="button" className="button secondary" disabled={busy} onClick={() => void cancel(run.job_identifier)}>{busy ? "Cancelling…" : retryCleanup ? "Retry cleanup" : "Cancel"}</button>}
              {terminalStatuses.has(run.status) && <button type="button" className="button secondary" onClick={() => void openDirectory(run.results_directory).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "The output folder could not be opened."))}>Open output folder</button>}
              <LiveCommandLog
                title="Log output"
                resetKey={run.job_identifier}
                active={logActive}
                status={run.status}
                stage={run.current_stage}
                startedAt={run.started_at}
                lastOutputAt={lastOutputByJob[run.job_identifier] ?? null}
                fetchChunk={fetchRunLog(run.job_identifier)}
              />
            </article>;
          })}
        </div>}
      </section>
    </div>
  );
}
