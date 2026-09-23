import { useEffect, useRef, useState } from "react";
import { apiRequest, setupInstallConflictMessage } from "../api";
import { LiveCommandLog } from "../components/LiveCommandLog";
import { setDependencyInstallActive } from "../native";
import type { CommandLogChunk, DemoPrepareJob, DemoStatus, PipelineDependencies, RunRecord } from "../types";
import {
  areRequestedActionsComplete,
  loadSetupState,
  recordSetupOutcome,
  saveSetupState,
  selectedActions,
  setupPipelines,
  updateSetupSelection,
  type PersistedSetupState,
  type SetupAction,
  type SetupPipelineIdentifier,
} from "../setupState";

const pipelines: Array<{ id: SetupPipelineIdentifier; name: string; detail: string }> = [
  { id: "bulk-rnaseq", name: "Bulk RNA-seq", detail: "Human paired-end RNA-seq setup and controlled workflow checks." },
  { id: "ont-analysis", name: "Oxford Nanopore ONT", detail: "Mouse modified-base BAM setup, with ONT-specific local tools." },
];

const POLL_INTERVAL_MS = 2_000;

type LiveJobKind = "fixtures" | "dependencies";

interface LiveJobContext {
  kind: LiveJobKind;
  pipeline: SetupPipelineIdentifier;
  jobIdentifier: string;
  status: string;
  stage: string | null;
  startedAt: string | null;
  lastOutputAt: string | null;
}

function actionLabel(action: SetupAction): string {
  return action === "fixtures" ? "synthetic fixtures" : "dependencies";
}

async function pollDemoJob(pipeline: SetupPipelineIdentifier, jobIdentifier: string, signal: AbortSignal): Promise<DemoPrepareJob> {
  while (!signal.aborted) {
    const job = await apiRequest<DemoPrepareJob>(`/api/v1/demos/${pipeline}/prepare/jobs/${jobIdentifier}`, { signal });
    if (job.status !== "running") return job;
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, POLL_INTERVAL_MS);
      signal.addEventListener("abort", () => {
        window.clearTimeout(timer);
        reject(new DOMException("Setup cancelled", "AbortError"));
      }, { once: true });
    });
  }
  throw new DOMException("Setup cancelled", "AbortError");
}

async function pollInstall(pipeline: SetupPipelineIdentifier, controller: AbortSignal): Promise<PipelineDependencies> {
  while (!controller.aborted) {
    const status = await apiRequest<PipelineDependencies>(`/api/v1/pipelines/${pipeline}/dependencies`, { signal: controller });
    if (status.job?.status !== "running") return status;
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, POLL_INTERVAL_MS);
      controller.addEventListener("abort", () => {
        window.clearTimeout(timer);
        reject(new DOMException("Setup cancelled", "AbortError"));
      }, { once: true });
    });
  }
  throw new DOMException("Setup cancelled", "AbortError");
}

export function Setup({ activeRun, isRunActive, onContinue }: {
  activeRun: RunRecord | null;
  isRunActive: boolean;
  onContinue: () => void;
}) {
  const [state, setState] = useState<PersistedSetupState>(() => loadSetupState(window.localStorage));
  const [working, setWorking] = useState(false);
  const [liveJob, setLiveJob] = useState<LiveJobContext | null>(null);
  const [error, setError] = useState("");
  const mounted = useRef(true);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => {
    mounted.current = false;
    controllerRef.current?.abort();
  }, []);

  const commit = (next: PersistedSetupState) => {
    saveSetupState(window.localStorage, next);
    if (mounted.current) setState(next);
    return next;
  };

  const select = (pipeline: SetupPipelineIdentifier, field: "selected" | SetupAction, value: boolean) => {
    if (working) return;
    commit(updateSetupSelection(state, pipeline, field, value));
  };

  const record = (current: PersistedSetupState, pipeline: SetupPipelineIdentifier, action: SetupAction, outcome: "pending" | "complete" | "skipped" | "failed", reason: string) => {
    const next = recordSetupOutcome(current, pipeline, action, { state: outcome, reason });
    commit(next);
    return next;
  };

  const syncDependencyLiveJob = (pipeline: SetupPipelineIdentifier, status: PipelineDependencies) => {
    const job = status.job;
    if (!job) {
      setLiveJob(null);
      return;
    }
    setLiveJob({
      kind: "dependencies",
      pipeline,
      jobIdentifier: job.job_identifier,
      status: job.status,
      stage: job.current_stage || null,
      startedAt: job.started_at,
      lastOutputAt: job.last_output_at,
    });
  };

  const prepare = async () => {
    if (working) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setWorking(true);
    setError("");
    setLiveJob(null);
    let current = state;
    try {
      for (const pipeline of setupPipelines) {
        if (!selectedActions(current, pipeline).includes("fixtures")) continue;
        try {
          let demoStatus = await apiRequest<DemoStatus>(`/api/v1/demos/${pipeline}/status`, { signal: controller.signal });
          if (demoStatus.available) {
            current = record(current, pipeline, "fixtures", "complete", demoStatus.message);
            continue;
          }
          let job = demoStatus.job?.status === "running" ? demoStatus.job : null;
          if (!job) {
            job = await apiRequest<DemoPrepareJob>(`/api/v1/demos/${pipeline}/prepare`, {
              method: "POST", body: JSON.stringify({ consent: true }), signal: controller.signal,
            });
          }
          setLiveJob({
            kind: "fixtures",
            pipeline,
            jobIdentifier: job.job_identifier,
            status: job.status,
            stage: job.current_stage,
            startedAt: job.started_at,
            lastOutputAt: job.last_output_at,
          });
          const finished = job.status === "running"
            ? await pollDemoJob(pipeline, job.job_identifier, controller.signal)
            : job;
          if (controller.signal.aborted) throw new DOMException("Setup cancelled", "AbortError");
          setLiveJob({
            kind: "fixtures",
            pipeline,
            jobIdentifier: finished.job_identifier,
            status: finished.status,
            stage: finished.current_stage,
            startedAt: finished.started_at,
            lastOutputAt: finished.last_output_at,
          });
          current = finished.status === "succeeded"
            ? record(current, pipeline, "fixtures", "complete", finished.message)
            : record(current, pipeline, "fixtures", "failed", finished.message);
        } catch (reason) {
          if (controller.signal.aborted) throw reason;
          current = record(current, pipeline, "fixtures", "failed", reason instanceof Error ? reason.message : "Fixture preparation failed.");
        }
      }
      for (const pipeline of setupPipelines) {
        if (!selectedActions(current, pipeline).includes("dependencies")) continue;
        if (isRunActive) {
          current = record(current, pipeline, "dependencies", "pending", "Waiting for the active run to finish before installation.");
          continue;
        }
        try {
          let status = await apiRequest<PipelineDependencies>(`/api/v1/pipelines/${pipeline}/dependencies`, { signal: controller.signal });
          if (status.missing.length === 0) {
            current = record(current, pipeline, "dependencies", "skipped", "All required dependencies are already available.");
            continue;
          }
          if (!status.installable) {
            current = record(current, pipeline, "dependencies", "skipped", `Manual prerequisite required: ${status.manual_requirements.join(", ") || "see dependency details"}.`);
            continue;
          }
          if (status.job?.status === "running") {
            syncDependencyLiveJob(pipeline, status);
            await setDependencyInstallActive(true).catch(() => undefined);
            status = await pollInstall(pipeline, controller.signal);
            await setDependencyInstallActive(false).catch(() => undefined);
          }
          if (status.missing.length === 0 || status.job?.status === "succeeded") {
            current = record(current, pipeline, "dependencies", "complete", status.job?.message ?? "Dependencies are ready.");
            continue;
          }
          await setDependencyInstallActive(true).catch(() => undefined);
          const installJob = await apiRequest<NonNullable<PipelineDependencies["job"]>>(
            `/api/v1/pipelines/${pipeline}/dependencies/install`,
            { method: "POST", body: JSON.stringify({ consent: true }), signal: controller.signal },
          );
          syncDependencyLiveJob(pipeline, { ...status, job: installJob });
          status = await pollInstall(pipeline, controller.signal);
          await setDependencyInstallActive(false).catch(() => undefined);
          syncDependencyLiveJob(pipeline, status);
          current = status.job?.status === "succeeded"
            ? record(current, pipeline, "dependencies", "complete", status.job.message)
            : record(current, pipeline, "dependencies", "failed", status.job?.message ?? "Installation did not complete.");
        } catch (reason) {
          if (controller.signal.aborted) throw reason;
          const message = reason instanceof Error ? reason.message : "Dependency installation failed.";
          current = record(current, pipeline, "dependencies", "failed", message);
          const conflict = setupInstallConflictMessage(reason);
          if (conflict) {
            setError(conflict);
            break;
          }
        }
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Setup did not complete.");
    } finally {
      if (mounted.current) {
        setWorking(false);
        setLiveJob(null);
      }
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  };

  const liveLogFetch = liveJob
    ? (offset: number, signal: AbortSignal) => {
      if (liveJob.kind === "fixtures") {
        return apiRequest<CommandLogChunk>(
          `/api/v1/demos/${liveJob.pipeline}/prepare/jobs/${liveJob.jobIdentifier}/logs?offset=${offset}`,
          { signal },
        );
      }
      return apiRequest<CommandLogChunk>(
        `/api/v1/pipelines/${liveJob.pipeline}/dependencies/jobs/${liveJob.jobIdentifier}/logs?offset=${offset}`,
        { signal },
      );
    }
    : null;

  return <div className="page-stack">
    <header className="page-header"><div><p className="eyebrow">Local environment</p><h1>Setup</h1><p className="lede">Choose the pipelines and local actions to prepare. Nothing installs until you explicitly start setup.</p></div></header>
    <section className="development-banner setup-sequence-note"><span className="notice-icon" aria-hidden="true">i</span><div><strong>Machine-local synthetic fixtures</strong><p>Bulk RNA-seq synthetic fixtures support local setup checks and controlled execution when your environment is ready. ONT synthetic fixtures remain setup-only and do not execute a pipeline. Managed dependency installations run strictly one at a time; biological data is not uploaded.</p></div></section>
    {error && <div className="inline-error" role="alert">{error}</div>}
    {liveJob && liveLogFetch && <LiveCommandLog
      title={liveJob.kind === "fixtures" ? `${liveJob.pipeline} fixture preparation` : `${liveJob.pipeline} dependency installation`}
      resetKey={`${liveJob.kind}-${liveJob.jobIdentifier}`}
      active={liveJob.status === "running"}
      status={liveJob.status}
      stage={liveJob.stage}
      startedAt={liveJob.startedAt}
      lastOutputAt={liveJob.lastOutputAt}
      fetchChunk={liveLogFetch}
    />}
    <div className="setup-pipeline-grid">
      {pipelines.map((pipeline) => {
        const configured = state.pipelines[pipeline.id];
        const enabled = configured.selected;
        return <section className={`panel setup-pipeline-card${enabled ? " selected" : ""}`} key={pipeline.id}>
          <label className="setup-pipeline-toggle"><input type="checkbox" checked={enabled} disabled={working} onChange={(event) => select(pipeline.id, "selected", event.target.checked)} /><span><strong>{pipeline.name}</strong><small>{pipeline.detail}</small></span></label>
          {enabled && <div className="setup-actions">
            <label className="setup-action-toggle"><input type="checkbox" checked={configured.dependencies} disabled={working} onChange={(event) => select(pipeline.id, "dependencies", event.target.checked)} /> Install required packages {isRunActive && <small>(unavailable during an active run)</small>}</label>
            <label className="setup-action-toggle"><input type="checkbox" checked={configured.fixtures} disabled={working} onChange={(event) => select(pipeline.id, "fixtures", event.target.checked)} /> Prepare synthetic fixtures</label>
            {selectedActions(state, pipeline.id).map((action) => {
              const outcome = configured.outcomes[action];
              return <p className={`setup-job ${outcome.state}`} key={action}><strong>{actionLabel(action)}:</strong> {outcome.state === "pending" ? "Awaiting your confirmation." : outcome.reason}</p>;
            })}
          </div>}
        </section>;
      })}
    </div>
    <div className="setup-footer">
      <button className="button primary" type="button" disabled={working || !setupPipelines.some((pipeline) => selectedActions(state, pipeline).length > 0)} onClick={() => void prepare()}>
        {working ? "Running selected setup…" : "Prepare selected setup"}
      </button>
      {areRequestedActionsComplete(state) && <button className="button secondary" type="button" onClick={onContinue}>Continue to Dashboard</button>}
      {activeRun && <p className="field-help">Fixture preparation remains available while this run is active; dependency installation is deferred.</p>}
    </div>
  </div>;
}
