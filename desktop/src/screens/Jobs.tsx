import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { openDirectory } from "../native";
import type { RunLog, RunRecord } from "../types";

const activeStatuses = new Set(["queued", "preparing", "running"]);

function formatTime(value: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

export function Jobs({ activeRun }: { activeRun: RunRecord | null }) {
  const [runs, setRuns] = useState<RunRecord[]>(activeRun ? [activeRun] : []);
  const [logs, setLogs] = useState<Record<string, string>>({});
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    const refresh = async () => {
      try {
        const records = await apiRequest<RunRecord[]>("/api/v1/runs");
        if (!active) return;
        setRuns(records);
        setError("");
        const current = records.find((record) => activeStatuses.has(record.status)) ?? records[0];
        if (current) {
          const result = await apiRequest<RunLog>(`/api/v1/runs/${current.job_identifier}/logs`);
          if (active) setLogs((existing) => ({ ...existing, [current.job_identifier]: result.text }));
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Jobs could not be loaded.");
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 2_000);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, []);

  const cancel = async (identifier: string) => {
    try {
      await apiRequest<RunRecord>(`/api/v1/runs/${identifier}/cancel`, { method: "POST" });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The job could not be cancelled.");
    }
  };

  return (
    <div className="page-stack">
      <header className="page-header"><div><p className="eyebrow">Execution status</p><h1>Jobs</h1><p className="lede">Local Nextflow job state and logs.</p></div></header>
      {error && <div className="inline-error" role="alert">{error}</div>}
      <section className="panel">
        {runs.length === 0 ? <div className="empty-state">
          <div className="empty-orbit" aria-hidden="true">◷</div>
          <h2>No jobs</h2>
          <p>No job records exist.</p>
        </div> : <div className="job-list">
          {runs.map((run) => (
            <article className="job-card" key={run.job_identifier}>
              <div className="section-heading">
                <div><h2>{run.project_name}</h2><p>{run.current_stage ?? "No stage reported"}</p></div>
                <span className={`job-state state-${run.status}`}>{run.status}</span>
              </div>
              <dl className="job-metadata">
                <dt>Started</dt><dd>{formatTime(run.started_at)}</dd>
                <dt>Finished</dt><dd>{formatTime(run.finished_at)}</dd>
                <dt>Exit code</dt><dd>{run.exit_code ?? "—"}</dd>
              </dl>
              {run.error_message && <p className="inline-error">{run.error_message}</p>}
              {activeStatuses.has(run.status) && (
                <button type="button" className="button secondary" onClick={() => cancel(run.job_identifier)}>Cancel</button>
              )}
              {run.status === "completed" && (
                <button type="button" className="button primary" onClick={() => void openDirectory(run.results_directory).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "The output folder could not be opened."))}>Open output folder</button>
              )}
              <details>
                <summary>Log output</summary>
                <pre className="command-preview job-log">{logs[run.job_identifier] || "No log output yet."}</pre>
              </details>
            </article>
          ))}
        </div>}
      </section>
    </div>
  );
}
