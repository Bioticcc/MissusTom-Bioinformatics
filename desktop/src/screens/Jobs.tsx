import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import type { SyntheticEvent } from "react";
import { apiRequest } from "../api";
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
  const [logs, setLogs] = useState<Record<string, RunLog>>({});
  const [expandedLogs, setExpandedLogs] = useState<Record<string, boolean>>({});
  const [cancelling, setCancelling] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");
  const logElements = useRef<Record<string, HTMLPreElement | null>>({});
  const followLogs = useRef<Record<string, boolean>>({});
  const expandedLogsRef = useRef(expandedLogs);
  const logControllers = useRef<Record<string, AbortController | undefined>>({});
  const priorStatuses = useRef<Record<string, RunStatus>>({});
  const mounted = useRef(false);

  useEffect(() => { expandedLogsRef.current = expandedLogs; }, [expandedLogs]);

  const scrollLogToLatest = useCallback((identifier: string) => {
    const element = logElements.current[identifier];
    if (element && followLogs.current[identifier] !== false) element.scrollTop = element.scrollHeight;
  }, []);

  useLayoutEffect(() => { Object.keys(logs).forEach(scrollLogToLatest); }, [logs, scrollLogToLatest]);

  const loadLog = useCallback(async (identifier: string, replace = false) => {
    if (logControllers.current[identifier] && !replace) return;
    logControllers.current[identifier]?.abort();
    const controller = new AbortController();
    logControllers.current[identifier] = controller;
    try {
      const log = await apiRequest<RunLog>(`/api/v1/runs/${identifier}/logs`, { signal: controller.signal });
      if (mounted.current && logControllers.current[identifier] === controller) {
        setLogs((existing) => ({ ...existing, [identifier]: log }));
        setError("");
      }
    } catch (reason) {
      if (mounted.current && !controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Log output could not be loaded.");
    } finally {
      if (logControllers.current[identifier] === controller) delete logControllers.current[identifier];
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    const activeLogControllers = logControllers.current;
    let timer: number | undefined;
    let controller: AbortController | undefined;
    const refresh = async () => {
      controller = new AbortController();
      try {
        const records = await apiRequest<RunRecord[]>("/api/v1/runs", { signal: controller.signal });
        if (!mounted.current) return;
        const finalOpenedLogs = records.filter((record) => {
          const previousStatus = priorStatuses.current[record.job_identifier];
          return expandedLogsRef.current[record.job_identifier]
            && terminalStatuses.has(record.status)
            && (Boolean(previousStatus && pollableStatuses.has(previousStatus)) || record.holds_admission);
        });
        priorStatuses.current = Object.fromEntries(records.map((record) => [record.job_identifier, record.status]));
        setRuns(records);
        setError("");
        await Promise.all([
          ...records.filter((record) => needsStatusRefresh(record) && expandedLogsRef.current[record.job_identifier]),
          ...finalOpenedLogs,
        ].map((record) => loadLog(record.job_identifier)));
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
      Object.values(activeLogControllers).forEach((logController) => logController?.abort());
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [loadLog]);

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

  const trackLogPosition = (identifier: string, element: HTMLPreElement) => {
    followLogs.current[identifier] = element.scrollHeight - element.scrollTop - element.clientHeight <= 8;
  };

  const revealLog = (identifier: string, event: SyntheticEvent<HTMLDetailsElement>) => {
    const open = event.currentTarget.open;
    setExpandedLogs((current) => ({ ...current, [identifier]: open }));
    if (open) {
      void loadLog(identifier);
      window.requestAnimationFrame(() => scrollLogToLatest(identifier));
    }
  };

  return (
    <div className="page-stack">
      <header className="page-header"><div><p className="eyebrow">Execution status</p><h1>Jobs</h1><p className="lede">Local Nextflow job state and logs.</p></div></header>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="panel">
        {runs.length === 0 ? <div className="empty-state"><div className="empty-orbit" aria-hidden="true">◷</div><h2>No jobs</h2><p>No job records exist.</p></div> : <div className="job-list">
          {runs.map((run) => {
            const log = logs[run.job_identifier];
            const retryCleanup = run.status === "interrupted" && run.holds_admission;
            const busy = cancelling.has(run.job_identifier) || run.status === "cancelling";
            return <article className="job-card" key={run.job_identifier}>
              <div className="section-heading"><div><h2>{run.project_name}</h2><p>{run.current_stage ?? "No stage reported"}</p></div><span className={`job-state state-${run.status}`}>{run.status}</span></div>
              <dl className="job-metadata"><dt>Started</dt><dd>{formatTime(run.started_at)}</dd><dt>Finished</dt><dd>{formatTime(run.finished_at)}</dd><dt>Start stage</dt><dd>{run.start_stage === "analysis" ? "Analysis only" : "Quantification + analysis"}</dd><dt>Exit code</dt><dd>{run.exit_code ?? "—"}</dd></dl>
              {run.error_message && <p className="inline-error">{run.error_message}</p>}
              {(cancellableStatuses.has(run.status) || retryCleanup) && <button type="button" className="button secondary" disabled={busy} onClick={() => void cancel(run.job_identifier)}>{busy ? "Cancelling…" : retryCleanup ? "Retry cleanup" : "Cancel"}</button>}
              {terminalStatuses.has(run.status) && <button type="button" className="button secondary" onClick={() => void openDirectory(run.results_directory).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "The output folder could not be opened."))}>Open output folder</button>}
              <details onToggle={(event) => revealLog(run.job_identifier, event)}>
                <summary>Log output</summary>
                <button type="button" className="text-button log-refresh" onClick={() => void loadLog(run.job_identifier, true)}>Refresh log</button>
                {log?.truncated && <p className="log-note">Showing the retained log output.</p>}
                <pre aria-label={`Log output for ${run.project_name}`} className="command-preview job-log" onScroll={(event) => trackLogPosition(run.job_identifier, event.currentTarget)} ref={(element) => { logElements.current[run.job_identifier] = element; }}>{log ? log.text || "No log output yet." : "Loading log output…"}</pre>
              </details>
            </article>;
          })}
        </div>}
      </section>
    </div>
  );
}
