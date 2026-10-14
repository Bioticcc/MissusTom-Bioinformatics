import { useEffect, useRef, useState } from "react";
import { apiRequest, getBackendStatus, setupInstallConflictMessage, type BackendStatus } from "../api";
import { LiveCommandLog } from "../components/LiveCommandLog";
import { isDesktopShell } from "../native";
import type { CommandLogChunk, DependencyJobStatus, DemoPrepareJob, DemoStatus, PipelineDependencies, PreflightCheck, RunRecord, SystemPreflight } from "../types";
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
  { id: "bulk-rnaseq", name: "Bulk RNA-seq", detail: "Paired-end RNA-seq setup, managed references, and controlled workflow checks." },
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

async function pollDemoJob(pipeline: SetupPipelineIdentifier, jobIdentifier: string, signal: AbortSignal, onUpdate: (job: DemoPrepareJob) => void): Promise<DemoPrepareJob> {
  while (!signal.aborted) {
    const job = await apiRequest<DemoPrepareJob>(`/api/v1/demos/${pipeline}/prepare/jobs/${jobIdentifier}`, { signal });
    onUpdate(job);
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

async function pollInstall(pipeline: SetupPipelineIdentifier, controller: AbortSignal, onUpdate: (job: PipelineDependencies["job"]) => void): Promise<void> {
  while (!controller.aborted) {
    const status = await apiRequest<DependencyJobStatus>(
      "/api/v1/dependencies/jobs/active", { signal: controller }, { requestKind: "short" },
    );
    const job = status.jobs.find((candidate) => candidate.pipeline_identifier === pipeline);
    if (!job) return;
    onUpdate(job);
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
  const [setupStep, setSetupStep] = useState("");
  const [setupAttempted, setSetupAttempted] = useState(false);
  const [backendStatus, setBackendStatus] = useState<BackendStatus | undefined>();
  const [nativeCheck, setNativeCheck] = useState<PreflightCheck | null>(null);
  const [nativeCheckError, setNativeCheckError] = useState("");
  const [nativeCheckPending, setNativeCheckPending] = useState(true);
  const [nativeCheckGeneration, setNativeCheckGeneration] = useState(0);
  const mounted = useRef(true);
  const controllerRef = useRef<AbortController | null>(null);
  const liveJobKind = liveJob?.kind;
  const liveJobPipeline = liveJob?.pipeline;
  const liveJobIdentifier = liveJob?.jobIdentifier;
  const liveJobStatus = liveJob?.status;

  useEffect(() => () => {
    mounted.current = false;
    controllerRef.current?.abort();
  }, []);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const refresh = async () => {
      const status = await getBackendStatus();
      if (!active) return;
      setBackendStatus(status);
      if (isDesktopShell() && (!status || (status.packaged && !status.ready))) {
        timer = window.setTimeout(() => void refresh(), POLL_INTERVAL_MS);
      }
    };
    void refresh();
    return () => { active = false; if (timer !== undefined) window.clearTimeout(timer); };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setNativeCheckPending(true);
    setNativeCheckError("");
    void apiRequest<SystemPreflight>(
      "/api/v1/system/preflight", { signal: controller.signal }, { requestKind: "long" },
    ).then((result) => {
      if (!controller.signal.aborted) {
        setNativeCheck(result.checks.find((check) => check.check_id === "native_containment") ?? null);
      }
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setNativeCheckError(reason instanceof Error ? reason.message : "Native containment could not be checked.");
    }).finally(() => {
      if (!controller.signal.aborted) setNativeCheckPending(false);
    });
    return () => controller.abort();
  }, [nativeCheckGeneration]);

  useEffect(() => {
    const controller = new AbortController();
    let restored: LiveJobContext | null = null;
    const consider = (candidate: LiveJobContext) => {
      if (!restored) {
        restored = candidate;
        return;
      }
      const running = candidate.status === "running";
      const restoredRunning = restored.status === "running";
      const candidateTime = Date.parse(candidate.lastOutputAt ?? candidate.startedAt ?? "") || 0;
      const restoredTime = Date.parse(restored.lastOutputAt ?? restored.startedAt ?? "") || 0;
      if ((running && !restoredRunning) || (running === restoredRunning && candidateTime > restoredTime)) restored = candidate;
    };
    const restore = async () => {
      await Promise.all(setupPipelines.map(async (pipeline) => {
        const demoResult = await Promise.allSettled([
          apiRequest<DemoStatus>(`/api/v1/demos/${pipeline}/status`, { signal: controller.signal }),
        ]);
        if (controller.signal.aborted) return;
        if (demoResult[0].status === "fulfilled" && demoResult[0].value.job) {
          const job = demoResult[0].value.job;
          consider({
            kind: "fixtures", pipeline, jobIdentifier: job.job_identifier, status: job.status,
            stage: job.current_stage || null, startedAt: job.started_at, lastOutputAt: job.last_output_at,
          });
        }
      }));
      const dependencyJobs = await apiRequest<DependencyJobStatus>(
        "/api/v1/dependencies/jobs/active", { signal: controller.signal }, { requestKind: "short" },
      ).catch(() => null);
      for (const job of dependencyJobs?.jobs ?? []) {
        consider({
          kind: "dependencies", pipeline: job.pipeline_identifier as SetupPipelineIdentifier,
          jobIdentifier: job.job_identifier, status: job.status, stage: job.current_stage || null,
          startedAt: job.started_at, lastOutputAt: job.last_output_at,
        });
      }
      if (!controller.signal.aborted && restored) setLiveJob(restored);
    };
    void restore();
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (working || !liveJobKind || !liveJobPipeline || !liveJobIdentifier || liveJobStatus !== "running") return;
    const kind = liveJobKind;
    const pipeline = liveJobPipeline;
    const jobIdentifier = liveJobIdentifier;
    const controller = new AbortController();
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const job = kind === "fixtures"
          ? await apiRequest<DemoPrepareJob>(`/api/v1/demos/${pipeline}/prepare/jobs/${jobIdentifier}`, { signal: controller.signal })
          : (await apiRequest<DependencyJobStatus>("/api/v1/dependencies/jobs/active", { signal: controller.signal }, { requestKind: "short" })).jobs.find((candidate) => candidate.job_identifier === jobIdentifier)
            ?? (await apiRequest<PipelineDependencies>(`/api/v1/pipelines/${pipeline}/dependencies`, { signal: controller.signal }, { requestKind: "long" })).job;
        if (controller.signal.aborted || !job || job.job_identifier !== jobIdentifier) return;
        setLiveJob({ kind, pipeline, jobIdentifier, status: job.status, stage: job.current_stage,
          startedAt: job.started_at, lastOutputAt: job.last_output_at });
        if (job.status === "running") timer = window.setTimeout(() => void refresh(), POLL_INTERVAL_MS);
      } catch {
        if (!controller.signal.aborted) timer = window.setTimeout(() => void refresh(), POLL_INTERVAL_MS);
      }
    };
    void refresh();
    return () => { controller.abort(); if (timer !== undefined) window.clearTimeout(timer); };
  }, [working, liveJobKind, liveJobPipeline, liveJobIdentifier, liveJobStatus]);

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

  const syncDependencyLiveJob = (pipeline: SetupPipelineIdentifier, job: PipelineDependencies["job"]) => {
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
    setSetupAttempted(true);
    setSetupStep("Starting setup and checking selected actions…");
    setError("");
    setLiveJob(null);
    let current = state;
    try {
      for (const pipeline of setupPipelines) {
        if (!selectedActions(current, pipeline).includes("fixtures")) continue;
        setSetupStep(`Checking ${pipeline} synthetic fixtures…`);
        try {
          const demoStatus = await apiRequest<DemoStatus>(`/api/v1/demos/${pipeline}/status`, { signal: controller.signal });
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
            ? await pollDemoJob(pipeline, job.job_identifier, controller.signal, (update) => setLiveJob({
              kind: "fixtures", pipeline, jobIdentifier: update.job_identifier, status: update.status,
              stage: update.current_stage, startedAt: update.started_at, lastOutputAt: update.last_output_at,
            }))
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
        setSetupStep(`Checking ${pipeline} dependencies…`);
        if (isRunActive) {
          current = record(current, pipeline, "dependencies", "pending", "Waiting for the active run to finish before installation.");
          continue;
        }
        try {
          let status = await apiRequest<PipelineDependencies>(
            `/api/v1/pipelines/${pipeline}/dependencies`,
            { signal: controller.signal },
            { requestKind: "long" },
          );
          if (status.missing.length === 0) {
            current = record(current, pipeline, "dependencies", "skipped", "All required dependencies are already available.");
            continue;
          }
          if (!status.installable) {
            current = record(current, pipeline, "dependencies", "skipped", `Manual prerequisite required: ${status.manual_requirements.join(", ") || "see dependency details"}.`);
            continue;
          }
          const joinedExistingInstall = status.job?.status === "running";
          if (joinedExistingInstall && status.job) {
            syncDependencyLiveJob(pipeline, status.job);
            setSetupStep(`Installing ${pipeline} dependencies…`);
            await pollInstall(pipeline, controller.signal, (job) => syncDependencyLiveJob(pipeline, job));
            setSetupStep(`Verifying ${pipeline} dependencies…`);
            status = await apiRequest<PipelineDependencies>(`/api/v1/pipelines/${pipeline}/dependencies`, { signal: controller.signal }, { requestKind: "long" });
          }
          if (status.missing.length === 0) {
            current = joinedExistingInstall
              ? record(current, pipeline, "dependencies", status.job?.status === "succeeded" ? "complete" : "failed",
                status.job?.status === "succeeded" ? "Installed and verified." : status.job?.message ?? "Installation did not complete successfully.")
              : record(current, pipeline, "dependencies", "skipped", "All required dependencies are already available.");
            continue;
          }
          const installJob = await apiRequest<NonNullable<PipelineDependencies["job"]>>(
            `/api/v1/pipelines/${pipeline}/dependencies/install`,
            { method: "POST", body: JSON.stringify({ consent: true }), signal: controller.signal },
          );
          syncDependencyLiveJob(pipeline, installJob);
          setSetupStep(`Installing ${pipeline} dependencies…`);
          await pollInstall(pipeline, controller.signal, (job) => syncDependencyLiveJob(pipeline, job));
          setSetupStep(`Verifying ${pipeline} dependencies…`);
          status = await apiRequest<PipelineDependencies>(`/api/v1/pipelines/${pipeline}/dependencies`, { signal: controller.signal }, { requestKind: "long" });
          if (status.job) syncDependencyLiveJob(pipeline, status.job);
          current = status.job?.status === "succeeded" && status.missing.length === 0
            ? record(current, pipeline, "dependencies", "complete", "Installed and verified.")
            : record(current, pipeline, "dependencies", "failed", status.missing.length > 0
              ? `Installation finished but verification still reports missing requirements: ${status.missing.join(", ")}.`
              : status.job?.message ?? "Installation did not complete.");
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
        setSetupStep("");
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

  const requestedOutcomes = setupPipelines.flatMap((pipeline) => selectedActions(state, pipeline).map((action) => state.pipelines[pipeline].outcomes[action]));
  const setupNeedsAttention = requestedOutcomes.some((outcome) => outcome.state === "failed" || (outcome.state === "skipped" && outcome.reason.startsWith("Manual prerequisite required")));
  const setupSummary = !working && (setupAttempted || state.completed)
    ? setupNeedsAttention ? "Setup finished with items needing attention. Review the results below."
      : areRequestedActionsComplete(state) ? "Setup completed. Selected dependencies and fixtures are ready or already available."
        : "Setup is incomplete. Review the results below and retry the pending actions."
    : "";

  return <div className="page-stack">
    <header className="page-header"><div><p className="eyebrow">Local environment</p><h1>Setup</h1><p className="lede">Choose the pipelines and local actions to prepare. Nothing installs until you explicitly start setup.</p></div></header>
    <details className="panel setup-sequence-note"><summary>About local setup</summary><p>Bulk RNA-seq synthetic fixtures support local setup checks and controlled execution when your environment is ready. ONT synthetic fixtures remain setup-only and do not execute a pipeline. Managed dependency installations run strictly one at a time; biological data is not uploaded.</p><p className="field-help">After setup, additional pipeline requirements can be installed from the Local setup section in Step 1 of a new project.</p></details>
    {backendStatus?.packaged && <details className="panel diagnostic-details" open={!backendStatus.ready ? true : undefined}><summary>Backend startup diagnostics</summary><p>{backendStatus.ready ? "Packaged backend is ready." : "Waiting for the packaged backend to become ready…"}</p>{backendStatus.startup_error && <p className="inline-error" role="alert">{backendStatus.startup_error}</p>}{backendStatus.startup_log_path && <small>Log file: {backendStatus.startup_log_path}</small>}<pre className="debug-terminal">{backendStatus.startup_log || "Waiting for backend startup output…"}</pre></details>}
    <section className="panel" aria-label="Native execution readiness"><div className="section-heading"><h2>Native execution readiness</h2><button className="text-button" type="button" disabled={nativeCheckPending} onClick={() => setNativeCheckGeneration((generation) => generation + 1)}>Recheck</button></div>{nativeCheckPending ? <p role="status">Checking the systemd user session, cgroup controllers, and an owned test workload…</p> : nativeCheckError ? <p className="inline-error" role="alert">Readiness check unavailable: {nativeCheckError}</p> : nativeCheck ? <p className={nativeCheck.status === "passed" ? "field-help" : "inline-error"} role="status">{nativeCheck.status === "passed" ? "Native execution is ready. " : "Native runs cannot start yet. "}{nativeCheck.message}</p> : <p className="inline-error" role="alert">The backend did not report native containment readiness.</p>}</section>
    {error && <div className="inline-error" role="alert">{error}</div>}
    {working && <p className="setup-progress" role="status"><strong>Setup request:</strong> {setupStep}</p>}
    {working && !liveJob && <pre className="debug-terminal" aria-label="Setup debug terminal">Starting setup and waiting for the backend job… Backend job output will appear here when the job starts.</pre>}
    {setupSummary && <p className={setupNeedsAttention ? "inline-error" : "setup-progress"} role="status">{setupSummary}</p>}
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
