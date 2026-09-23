import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api";
import { LiveCommandLog } from "./LiveCommandLog";
import type { CommandLogChunk, DemoPrepareJob, DemoStatus } from "../types";

const POLL_INTERVAL_MS = 2_000;

async function pollDemoJob(
  pipelineIdentifier: string,
  jobIdentifier: string,
  signal: AbortSignal,
): Promise<DemoPrepareJob> {
  while (!signal.aborted) {
    const job = await apiRequest<DemoPrepareJob>(
      `/api/v1/demos/${pipelineIdentifier}/prepare/jobs/${jobIdentifier}`,
      { signal },
    );
    if (job.status !== "running") return job;
    await new Promise<void>((resolve, reject) => {
      const timer = window.setTimeout(resolve, POLL_INTERVAL_MS);
      signal.addEventListener("abort", () => {
        window.clearTimeout(timer);
        reject(new DOMException("Demo preparation cancelled", "AbortError"));
      }, { once: true });
    });
  }
  throw new DOMException("Demo preparation cancelled", "AbortError");
}

export function PipelineDemoAssets({ pipelineIdentifier }: { pipelineIdentifier: "bulk-rnaseq" | "ont-analysis" }) {
  const [assets, setAssets] = useState<DemoStatus | null>(null);
  const [prepareJob, setPrepareJob] = useState<DemoPrepareJob | null>(null);
  const [loading, setLoading] = useState(true);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState("");
  const controllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async (signal: AbortSignal) => {
    const result = await apiRequest<DemoStatus>(`/api/v1/demos/${pipelineIdentifier}/status`, { signal });
    setAssets(result);
    if (result.job?.status === "running") setPrepareJob(result.job);
    return result;
  }, [pipelineIdentifier]);

  useEffect(() => {
    const controller = new AbortController();
    controllerRef.current = controller;
    setLoading(true);
    setError("");
    void refresh(controller.signal).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Demo asset status could not be checked.");
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => {
      controller.abort();
      if (controllerRef.current === controller) controllerRef.current = null;
    };
  }, [refresh]);

  const trackedJob = assets?.job;
  useEffect(() => {
    if (!trackedJob || trackedJob.status !== "running") return;
    setPrepareJob(trackedJob);
    const controller = new AbortController();
    void pollDemoJob(pipelineIdentifier, trackedJob.job_identifier, controller.signal)
      .then((finished) => {
        setPrepareJob(finished);
        return refresh(controller.signal);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Demo preparation could not be tracked.");
      });
    return () => controller.abort();
  }, [trackedJob, pipelineIdentifier, refresh]);

  const prepare = async () => {
    const controller = controllerRef.current;
    if (!controller) return;
    setPreparing(true);
    setError("");
    try {
      const job = await apiRequest<DemoPrepareJob>(
        `/api/v1/demos/${pipelineIdentifier}/prepare`,
        { method: "POST", body: JSON.stringify({ consent: true }), signal: controller.signal },
      );
      if (controller.signal.aborted) return;
      setPrepareJob(job);
      const finished = job.status === "running"
        ? await pollDemoJob(pipelineIdentifier, job.job_identifier, controller.signal)
        : job;
      if (!controller.signal.aborted) {
        setPrepareJob(finished);
        await refresh(controller.signal);
      }
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Demo assets could not be prepared.");
    } finally {
      if (!controller.signal.aborted) setPreparing(false);
    }
  };

  const activeJob = prepareJob?.status === "running" ? prepareJob : assets?.job?.status === "running" ? assets.job : null;
  const displayJob = prepareJob ?? activeJob;
  const displayJobId = displayJob?.job_identifier;

  const fetchDemoPrepareLog = useCallback(
    (offset: number, signal: AbortSignal) => {
      if (!displayJobId) {
        return Promise.reject(new Error("Demo preparation job is not available."));
      }
      return apiRequest<CommandLogChunk>(
        `/api/v1/demos/${pipelineIdentifier}/prepare/jobs/${displayJobId}/logs?offset=${offset}`,
        { signal },
      );
    },
    [displayJobId, pipelineIdentifier],
  );

  return (
    <section className="setup-demo-assets" aria-live="polite">
      <div><h3>Lightweight demo assets</h3><p>Optional local, synthetic or small demo inputs for setup checks; biological data is not uploaded.</p></div>
      {error && <div className="inline-error" role="alert">{error}</div>}
      {loading ? <p className="loading-copy">Checking demo assets…</p> : assets && <>
        <p className={assets.available ? "success-message" : "field-help"}>{assets.message}</p>
        <p className="field-help">{assets.execution_note}</p>
        {assets.available && <div className="field-help">
          <p>Bundle: <code>{assets.bundle_directory}</code></p>
          {assets.manifest_path && <p>Manifest: <code>{assets.manifest_path}</code></p>}
          {assets.integrity && <p>Local self-consistency: {assets.integrity.file_count} files; manifest SHA-256 <code>{assets.integrity.sha256}</code></p>}
        </div>}
        {displayJob && <LiveCommandLog
          title="Demo preparation log"
          resetKey={displayJob.job_identifier}
          active={displayJob.status === "running"}
          status={displayJob.status}
          stage={displayJob.current_stage}
          startedAt={displayJob.started_at}
          lastOutputAt={displayJob.last_output_at}
          fetchChunk={fetchDemoPrepareLog}
        />}
        <button className="button secondary" type="button" onClick={() => void prepare()} disabled={assets.available || preparing || Boolean(activeJob)}>
          {preparing || activeJob ? "Preparing demo assets…" : assets.available ? "Demo assets ready" : "Prepare lightweight demo assets"}
        </button>
      </>}
    </section>
  );
}
