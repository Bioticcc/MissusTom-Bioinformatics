import { useEffect, useRef, useState } from "react";
import { apiRequest, setupInstallConflictMessage } from "../api";
import { setDependencyInstallActive } from "../native";
import type { DemoStatus, PipelineDependencies, RunRecord } from "../types";
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

function actionLabel(action: SetupAction): string {
  return action === "fixtures" ? "synthetic fixtures" : "dependencies";
}

export function Setup({ activeRun, isRunActive, onContinue }: {
  activeRun: RunRecord | null;
  isRunActive: boolean;
  onContinue: () => void;
}) {
  const [state, setState] = useState<PersistedSetupState>(() => loadSetupState(window.localStorage));
  const [working, setWorking] = useState(false);
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

  const pollInstall = async (pipeline: SetupPipelineIdentifier, controller: AbortController): Promise<PipelineDependencies> => {
    while (!controller.signal.aborted) {
      const status = await apiRequest<PipelineDependencies>(`/api/v1/pipelines/${pipeline}/dependencies`, { signal: controller.signal });
      if (status.job?.status !== "running") return status;
      await new Promise<void>((resolve, reject) => {
        const timer = window.setTimeout(resolve, POLL_INTERVAL_MS);
        controller.signal.addEventListener("abort", () => {
          window.clearTimeout(timer);
          reject(new DOMException("Setup cancelled", "AbortError"));
        }, { once: true });
      });
    }
    throw new DOMException("Setup cancelled", "AbortError");
  };

  const record = (current: PersistedSetupState, pipeline: SetupPipelineIdentifier, action: SetupAction, outcome: "pending" | "complete" | "skipped" | "failed", reason: string) => {
    const next = recordSetupOutcome(current, pipeline, action, { state: outcome, reason });
    commit(next);
    return next;
  };

  const prepare = async () => {
    if (working) return;
    const controller = new AbortController();
    controllerRef.current = controller;
    setWorking(true);
    setError("");
    let current = state;
    try {
      for (const pipeline of setupPipelines) {
        if (!selectedActions(current, pipeline).includes("fixtures")) continue;
        try {
          const result = await apiRequest<DemoStatus>(`/api/v1/demos/${pipeline}/prepare`, {
            method: "POST", body: JSON.stringify({ consent: true }), signal: controller.signal,
          });
          current = record(current, pipeline, "fixtures", "complete", result.message);
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
            await setDependencyInstallActive(true).catch(() => {
              // Backend admission remains authoritative if native reporting fails.
            });
            status = await pollInstall(pipeline, controller);
            await setDependencyInstallActive(false).catch(() => undefined);
          }
          if (status.missing.length === 0 || status.job?.status === "succeeded") {
            current = record(current, pipeline, "dependencies", "complete", status.job?.message ?? "Dependencies are ready.");
            continue;
          }
          await setDependencyInstallActive(true).catch(() => {
            // Backend admission remains authoritative if native reporting fails.
          });
          await apiRequest(`/api/v1/pipelines/${pipeline}/dependencies/install`, {
            method: "POST", body: JSON.stringify({ consent: true }), signal: controller.signal,
          });
          status = await pollInstall(pipeline, controller);
          await setDependencyInstallActive(false).catch(() => undefined);
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
      if (mounted.current) setWorking(false);
      if (controllerRef.current === controller) controllerRef.current = null;
    }
  };

  return <div className="page-stack">
    <header className="page-header"><div><p className="eyebrow">Local environment</p><h1>Setup</h1><p className="lede">Choose the pipelines and local actions to prepare. Nothing installs until you explicitly start setup.</p></div></header>
    <section className="development-banner setup-sequence-note"><span className="notice-icon" aria-hidden="true">i</span><div><strong>Machine-local, non-executable fixtures</strong><p>Synthetic fixtures only support local setup checks; they do not execute a pipeline or upload biological data. Managed dependency installations run strictly one at a time.</p></div></section>
    {error && <div className="inline-error" role="alert">{error}</div>}
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
        {working ? "Preparing selected setup…" : "Prepare selected setup"}
      </button>
      {areRequestedActionsComplete(state) && <button className="button secondary" type="button" onClick={onContinue}>Continue to Dashboard</button>}
      {activeRun && <p className="field-help">Fixture preparation remains available while this run is active; dependency installation is deferred.</p>}
    </div>
  </div>;
}
