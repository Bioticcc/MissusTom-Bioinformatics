import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { restoreMainWindow, startOverlayDragging } from "../native";
import { formatRunStartedAt, latestLogMessage, selectActiveRun } from "../runOverlayState";
import type { RunLog, RunRecord } from "../types";

const POLL_MS = 2_000;

export function RunOverlay() {
  const [run, setRun] = useState<RunRecord | null>(null);
  const [message, setMessage] = useState("Loading run status…");
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    let controller: AbortController | undefined;
    let timer: number | undefined;
    let logRunId: string | null = null;

    const refresh = async () => {
      controller = new AbortController();
      try {
        const records = await apiRequest<RunRecord[]>("/api/v1/runs", { signal: controller.signal });
        const activeRun = selectActiveRun(records);
        if (!live || controller.signal.aborted) return;
        setRun(activeRun);
        if (!activeRun) {
          logRunId = null;
          setMessage("No active run.");
          setError("");
        } else {
          if (logRunId !== activeRun.job_identifier) {
            logRunId = activeRun.job_identifier;
            setMessage("Loading latest log message…");
            setError("");
          }
          const log = await apiRequest<RunLog>(`/api/v1/runs/${activeRun.job_identifier}/logs?limit=4000`, { signal: controller.signal });
          if (!live || controller.signal.aborted) return;
          setMessage(latestLogMessage(log.text));
          setError("");
        }
      } catch (reason) {
        if (live && !controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Run status could not be refreshed.");
        }
      } finally {
        if (live && !controller?.signal.aborted) timer = window.setTimeout(() => void refresh(), POLL_MS);
      }
    };

    void refresh();
    return () => {
      live = false;
      controller?.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);

  const drag = () => { void startOverlayDragging().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "The window could not be moved.")); };
  const restore = () => { void restoreMainWindow().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "The main window could not be restored.")); };

  return <main className="run-overlay" aria-live="polite">
    <header className="run-overlay-drag" onMouseDown={drag}>
      <span>Missus Tom</span>
      <button type="button" className="run-overlay-restore" onMouseDown={(event) => event.stopPropagation()} onClick={restore}>Open app</button>
    </header>
    {run ? <>
      <div className="run-overlay-heading"><div><p>Active run</p><h1 title={run.project_name}>{run.project_name}</h1></div><span className={`job-state state-${run.status}`}>{run.status}</span></div>
      <dl><dt>Started</dt><dd>{formatRunStartedAt(run.started_at)}</dd><dt>Stage</dt><dd title={run.current_stage ?? undefined}>{run.current_stage ?? "Waiting for workflow status"}</dd></dl>
      <p className="run-overlay-log" title={message}>{message}</p>
    </> : <p className="run-overlay-empty">{message}</p>}
    {error && <p className="run-overlay-error" role="alert">{error}</p>}
  </main>;
}
