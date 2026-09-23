import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api";
import { setDependencyInstallActive } from "../native";
import type { PipelineDependencies } from "../types";

const POLL_INTERVAL_MS = 5_000;
const LOG_TAIL_LIMIT = 20;
const dependencyBusy = new Map<string, boolean>();

function setPipelineDependencyBusy(pipelineIdentifier: string, active: boolean): void {
  dependencyBusy.set(pipelineIdentifier, active);
  void setDependencyInstallActive([...dependencyBusy.values()].some(Boolean)).catch(() => {
    // Desktop lifecycle reporting is best-effort; status polling remains authoritative.
  });
}

function reportDependencyBusy(pipelineIdentifier: string, result: PipelineDependencies): void {
  setPipelineDependencyBusy(pipelineIdentifier, result.job?.status === "running");
}

export function PipelineDependencies({
  pipelineIdentifier,
  onInstalled,
}: {
  pipelineIdentifier: "bulk-rnaseq" | "ont-analysis";
  onInstalled?: () => void | Promise<void>;
}) {
  const [dependencies, setDependencies] = useState<PipelineDependencies | null>(null);
  const [job, setJob] = useState<PipelineDependencies["job"]>(null);
  const [loading, setLoading] = useState(true);
  const [installing, setInstalling] = useState(false);
  const [statusRefreshPending, setStatusRefreshPending] = useState(false);
  const [error, setError] = useState("");
  const generationRef = useRef(0);
  const requestRef = useRef(0);
  const notifiedJobRef = useRef("");
  const lifecycleControllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async (signal: AbortSignal) => apiRequest<PipelineDependencies>(
      `/api/v1/pipelines/${pipelineIdentifier}/dependencies`,
      { signal },
    ), [pipelineIdentifier]);

  const applyStatus = useCallback((result: PipelineDependencies, generation: number, request: number) => {
    if (generation !== generationRef.current || request !== requestRef.current) return false;
    setDependencies(result);
    setJob(result.job);
    reportDependencyBusy(pipelineIdentifier, result);
    return true;
  }, [pipelineIdentifier]);

  useEffect(() => {
    lifecycleControllerRef.current?.abort();
    const controller = new AbortController();
    lifecycleControllerRef.current = controller;
    const generation = generationRef.current + 1;
    generationRef.current = generation;
    const request = requestRef.current + 1;
    requestRef.current = request;
    setDependencies(null);
    setJob(null);
    setStatusRefreshPending(false);
    setError("");
    setLoading(true);
    void refresh(controller.signal)
      .then((result) => {
        applyStatus(result, generation, request);
      }).catch((reason: unknown) => {
        if (!controller.signal.aborted && generation === generationRef.current && request === requestRef.current) setError(reason instanceof Error ? reason.message : "Package requirements could not be checked.");
      })
      .finally(() => {
        if (!controller.signal.aborted && generation === generationRef.current && request === requestRef.current) setLoading(false);
      });
    return () => {
      controller.abort();
      if (lifecycleControllerRef.current === controller) lifecycleControllerRef.current = null;
    };
  }, [applyStatus, refresh]);

  useEffect(() => {
    if (job?.status !== "running" || statusRefreshPending) return;
    const lifecycleController = lifecycleControllerRef.current;
    if (!lifecycleController) return;
    const controller = new AbortController();
    const abortFromLifecycle = () => controller.abort();
    lifecycleController.signal.addEventListener("abort", abortFromLifecycle, { once: true });
    if (lifecycleController.signal.aborted) controller.abort();
    const generation = generationRef.current;
    let timeout: number | undefined;
    let polling = false;
    const poll = async () => {
      if (polling || controller.signal.aborted) return;
      polling = true;
      const request = requestRef.current + 1;
      requestRef.current = request;
      try {
        const result = await refresh(controller.signal);
        if (!applyStatus(result, generation, request)) return;
        if (result.job?.status === "succeeded" && notifiedJobRef.current !== result.job.job_identifier) {
          notifiedJobRef.current = result.job.job_identifier;
          void Promise.resolve(onInstalled?.()).catch((reason: unknown) => {
            if (!controller.signal.aborted && generation === generationRef.current) setError(reason instanceof Error ? reason.message : "The run plan could not be refreshed.");
          });
        }
        if (!controller.signal.aborted && generation === generationRef.current && result.job?.status === "running") timeout = window.setTimeout(poll, POLL_INTERVAL_MS);
      } catch (reason) {
        if (!controller.signal.aborted && generation === generationRef.current && request === requestRef.current) {
          setError(reason instanceof Error ? reason.message : "Installation status could not be refreshed.");
          timeout = window.setTimeout(poll, POLL_INTERVAL_MS);
        }
      } finally {
        polling = false;
      }
    };
    timeout = window.setTimeout(poll, POLL_INTERVAL_MS);
    return () => {
      controller.abort();
      lifecycleController.signal.removeEventListener("abort", abortFromLifecycle);
      if (timeout !== undefined) window.clearTimeout(timeout);
    };
  }, [applyStatus, job?.status, onInstalled, refresh, statusRefreshPending]);

  const requestRefresh = async () => {
    const controller = lifecycleControllerRef.current;
    if (!controller) return;
    const generation = generationRef.current;
    const request = requestRef.current + 1;
    requestRef.current = request;
    setLoading(true);
    setError("");
    try {
      const result = await refresh(controller.signal);
      applyStatus(result, generation, request);
    } catch (reason) {
      if (!controller.signal.aborted && generation === generationRef.current && request === requestRef.current) setError(reason instanceof Error ? reason.message : "Package requirements could not be checked.");
    } finally {
      if (!controller.signal.aborted && generation === generationRef.current && request === requestRef.current) setLoading(false);
    }
  };

  const install = async () => {
    const controller = lifecycleControllerRef.current;
    if (!controller) return;
    const generation = generationRef.current;
    const request = requestRef.current + 1;
    requestRef.current = request;
    setInstalling(true);
    setError("");
    setPipelineDependencyBusy(pipelineIdentifier, true);
    try {
      const result = await apiRequest<NonNullable<PipelineDependencies["job"]>>(
        `/api/v1/pipelines/${pipelineIdentifier}/dependencies/install`,
        { method: "POST", body: JSON.stringify({ consent: true }), signal: controller.signal },
      );
      if (generation !== generationRef.current || request !== requestRef.current) return;
      setJob(result);
      if (result.status === "succeeded" && notifiedJobRef.current !== result.job_identifier) {
        notifiedJobRef.current = result.job_identifier;
        void Promise.resolve(onInstalled?.()).catch((callbackError: unknown) => {
          if (!controller.signal.aborted && generation === generationRef.current) setError(callbackError instanceof Error ? callbackError.message : "The run plan could not be refreshed.");
        });
      }
      setStatusRefreshPending(true);
      const refreshRequest = requestRef.current + 1;
      requestRef.current = refreshRequest;
      void refresh(controller.signal).then((status) => {
        if (!applyStatus(status, generation, refreshRequest)) return;
        if (status.job?.status === "succeeded" && notifiedJobRef.current !== status.job.job_identifier) {
          notifiedJobRef.current = status.job.job_identifier;
          void Promise.resolve(onInstalled?.()).catch((callbackError: unknown) => {
            if (!controller.signal.aborted && generation === generationRef.current) setError(callbackError instanceof Error ? callbackError.message : "The run plan could not be refreshed.");
          });
        }
      }).catch((refreshError: unknown) => {
        if (!controller.signal.aborted && generation === generationRef.current && refreshRequest === requestRef.current) setError(refreshError instanceof Error ? refreshError.message : "Installation status could not be refreshed.");
      }).finally(() => {
        if (!controller.signal.aborted && generation === generationRef.current && refreshRequest === requestRef.current) setStatusRefreshPending(false);
      });
    } catch (reason) {
      if (!controller.signal.aborted && generation === generationRef.current && request === requestRef.current) setError(reason instanceof Error ? reason.message : "Required packages could not be installed.");
    } finally {
      if (!controller.signal.aborted && generation === generationRef.current) setInstalling(false);
    }
  };

  const running = job?.status === "running";
  const title = pipelineIdentifier === "ont-analysis" ? "ONT analysis dependencies" : "Bulk RNA-seq dependencies";

  return (
    <section className="panel pipeline-dependencies" aria-live="polite">
      <div className="section-heading">
        <div><p className="eyebrow">Local setup</p><h2>{title}</h2></div>
        <button className="button secondary" type="button" onClick={() => void requestRefresh()} disabled={loading || running}>
          {loading ? "Checking…" : "Refresh"}
        </button>
      </div>
      <p className="helper-copy">
        Managed installation downloads software from the internet and does not upload biological data. {pipelineIdentifier === "ont-analysis"
          ? <>ONT setup can download several GiB, including Dorado, and requires additional extracted disk space; it may take time.</>
          : <>Bulk RNA-seq setup downloads managed native tools and may take time.</>} Downloads remain subject to third-party license terms{pipelineIdentifier === "ont-analysis" ? <>; see the <a href="https://github.com/nanoporetech/dorado#license" target="_blank" rel="noopener noreferrer">Dorado license</a>.</> : "."}
      </p>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {loading && !dependencies ? <p className="loading-copy">Checking required packages…</p> : dependencies && <>
        {dependencies.missing.length === 0 ? <p className="success-message" role="status">All required packages are available.</p> : <div className="warning-list"><strong>{dependencies.missing.length} requirement{dependencies.missing.length === 1 ? "" : "s"} need attention</strong><p>{dependencies.missing.join(", ")}</p></div>}
        <ul className="dependency-list">
          {dependencies.requirements.map((requirement) => <li key={requirement.name}>
            <span className={requirement.installed ? "dependency-state installed" : "dependency-state missing"}>{requirement.installed ? "Available" : "Missing"}</span>
            <div><strong>{requirement.name}</strong><p>{requirement.detail}</p></div>
            <small>{requirement.managed ? "Managed" : "Manual"}</small>
          </li>)}
        </ul>
        {dependencies.manual_requirements.length > 0 && <div className="manual-requirements"><strong>Manual prerequisites</strong><ul>{dependencies.manual_requirements.map((requirement) => <li key={requirement}>{requirement}</li>)}</ul></div>}
        {job && <div className={`dependency-job ${job.status}`}><strong>{job.status === "running" ? "Installing packages" : job.status === "succeeded" ? "Installation complete" : "Installation failed"}</strong><p>{job.message}</p>{job.log_tail.length > 0 && <pre aria-label="Installation log tail">{job.log_tail.slice(-LOG_TAIL_LIMIT).join("\n")}</pre>}</div>}
        <button className="button primary" type="button" onClick={() => void install()} disabled={!dependencies.installable || dependencies.missing.length === 0 || running || installing}>
          {running || installing ? "Installing…" : "Install required packages"}
        </button>
      </>}
    </section>
  );
}
