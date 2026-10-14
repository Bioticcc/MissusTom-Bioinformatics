import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api";
import { LiveCommandLog } from "../components/LiveCommandLog";
import { DirectoryOpenError, type DirectoryOpenFailure } from "../components/DirectoryOpenError";
import { isDesktopShell, openDirectory } from "../native";
import { finishedTime, outcomeLabel } from "../runPresentation";
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

function withActiveRun(records: RunRecord[], activeRun: RunRecord | null) {
  if (!activeRun) return records;
  if (records.some((run) => run.job_identifier === activeRun.job_identifier)) return records;
  return [activeRun, ...records];
}

export function Jobs({
  activeRun,
  polledRuns,
}: {
  activeRun: RunRecord | null;
  polledRuns: RunRecord[] | null;
}) {
  const desktop = isDesktopShell();
  const [runs, setRuns] = useState<RunRecord[]>(
    polledRuns === null ? (activeRun ? [activeRun] : []) : withActiveRun(polledRuns, activeRun),
  );
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const cancellingPending = useRef(new Set<string>());
  const [confirmingCancel, setConfirmingCancel] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [directoryOpenFailure, setDirectoryOpenFailure] = useState<DirectoryOpenFailure | null>(null);
  const [lastOutputByJob, setLastOutputByJob] = useState<Record<string, string | null>>({});
  const mounted = useRef(false);

  const settleStops = useCallback((records: RunRecord[]) => {
    const finished = records.filter((record) => terminalStatuses.has(record.status)).map((record) => record.job_identifier);
    if (finished.length === 0) return;
    finished.forEach((identifier) => cancellingPending.current.delete(identifier));
    setCancelling((current) => {
      if (!finished.some((identifier) => current.has(identifier))) return current;
      const next = new Set(current);
      finished.forEach((identifier) => next.delete(identifier));
      return next;
    });
  }, []);

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
    if (!desktop || polledRuns === null) return;
    setRuns(withActiveRun(polledRuns, activeRun));
    settleStops(polledRuns);
    setError("");
  }, [activeRun, desktop, polledRuns, settleStops]);

  useEffect(() => {
    mounted.current = true;
    if (desktop) {
      return () => {
        mounted.current = false;
      };
    }
    let timer: number | undefined;
    let controller: AbortController | undefined;
    const refresh = async () => {
      controller = new AbortController();
      try {
        const records = await apiRequest<RunRecord[]>("/api/v1/runs", { signal: controller.signal });
        if (!mounted.current) return;
        setRuns(records);
        settleStops(records);
        setError("");
        if (mounted.current && records.some(needsStatusRefresh)) {
          timer = window.setTimeout(() => void refresh(), POLL_MS);
        }
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
  }, [desktop, settleStops]);

  const cancel = async (identifier: string) => {
    if (cancellingPending.current.has(identifier)) return;
    cancellingPending.current.add(identifier);
    setConfirmingCancel(null);
    setCancelling((current) => new Set(current).add(identifier));
    setError("");
    try {
      const record = await apiRequest<RunRecord>(`/api/v1/runs/${identifier}/cancel`, { method: "POST" });
      if (mounted.current) setRuns((current) => current.map((run) => run.job_identifier === identifier ? record : run));
      settleStops([record]);
    } catch (reason) {
      if (mounted.current) setError(reason instanceof Error ? reason.message : "The job could not be cancelled.");
      cancellingPending.current.delete(identifier);
      if (mounted.current) setCancelling((current) => { const next = new Set(current); next.delete(identifier); return next; });
    }
  };

  const openOutput = async (path: string) => {
    try {
      await openDirectory(path);
      setDirectoryOpenFailure(null);
    } catch (reason) {
      setDirectoryOpenFailure({ path, message: reason instanceof Error ? reason.message : String(reason) });
    }
  };

  return (
    <div className="page-stack">
      <header className="page-header"><div><p className="eyebrow">Execution status</p><h1>Jobs</h1><p className="lede">Local Nextflow job state and logs.</p></div></header>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {directoryOpenFailure && <DirectoryOpenError key={directoryOpenFailure.path} {...directoryOpenFailure} />}
      <section className="panel">
        {runs.length === 0 ? <div className="empty-state"><div className="empty-orbit" aria-hidden="true">◷</div><h2>No jobs</h2><p>No job records exist.</p></div> : <div className="job-list">
          {runs.map((run) => {
            const retryCleanup = run.holds_admission && Boolean(run.cleanup_warning || run.finished_at || run.status === "interrupted");
            const busy = cancelling.has(run.job_identifier) || run.status === "cancelling";
            const logActive = pollableStatuses.has(run.status) || run.holds_admission;
            return <article className="job-card" key={run.job_identifier}>
              <div className="section-heading"><div><h2>{run.project_name}</h2><p>{run.current_stage ?? "No stage reported"}</p></div><span className={`job-state state-${run.status}`}>{outcomeLabel(run)}</span></div>
              <dl className="job-metadata"><dt>Started</dt><dd>{formatTime(run.started_at)}</dd><dt>Finished</dt><dd>{finishedTime(run)}</dd><dt>Pipeline</dt><dd>{run.pipeline_identifier === "ont-analysis" ? "ONT analysis" : run.pipeline_identifier === "bulk-rnaseq" ? "Bulk RNA-seq" : "Configured workflow"}</dd><dt>Run scope</dt><dd>{run.pipeline_identifier === "ont-analysis" ? "Configured ONT workflow" : run.start_stage === "analysis" ? "Analysis only" : "Quantification + analysis"}</dd><dt>Exit code</dt><dd>{run.exit_code ?? "—"}</dd></dl>
              {run.error_message && (run.status === "cancelled" && run.error_message === "Cancelled by user" ? <p className="field-help">Cancelled by user. Logs and run history are retained.</p> : <p className="inline-error">Execution: {run.error_message}</p>)}
              {run.cleanup_warning && <p className="inline-error">Cleanup needs attention: {run.cleanup_warning}</p>}
              {(cancellableStatuses.has(run.status) || run.status === "cancelling") && <button type="button" className="button secondary" disabled={busy} onClick={() => setConfirmingCancel(run.job_identifier)}>{busy ? "Stopping…" : "Stop run"}</button>}
              {confirmingCancel === run.job_identifier && cancellableStatuses.has(run.status) && !busy && <div className="cancel-confirmation" role="alertdialog" aria-label="Confirm run cancellation"><p>Stop this run? Missus Tom will stop its controlled work and keep the logs and run history.</p><button type="button" className="button danger" onClick={() => void cancel(run.job_identifier)}>Stop run</button><button type="button" className="button secondary" onClick={() => setConfirmingCancel(null)}>Keep running</button></div>}
              {retryCleanup && <button type="button" className="button secondary" disabled={busy} onClick={() => void cancel(run.job_identifier)}>{cancelling.has(run.job_identifier) ? "Checking cleanup…" : "Retry cleanup"}</button>}
              {terminalStatuses.has(run.status) && <button type="button" className="button secondary" onClick={() => void openOutput(run.results_directory)}>Open output folder</button>}
              <LiveCommandLog
                title="Log output"
                resetKey={run.job_identifier}
                active={logActive}
                status={run.status}
                stage={run.current_stage}
                startedAt={run.started_at}
                finishedAt={run.finished_at}
                lastOutputAt={lastOutputByJob[run.job_identifier] ?? null}
                fetchChunk={fetchRunLog(run.job_identifier)}
                defaultExpanded={pollableStatuses.has(run.status)}
              />
            </article>;
          })}
        </div>}
      </section>
    </div>
  );
}
