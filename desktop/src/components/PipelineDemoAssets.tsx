import { useCallback, useEffect, useRef, useState } from "react";
import { apiRequest } from "../api";
import type { DemoStatus } from "../types";

export function PipelineDemoAssets({ pipelineIdentifier }: { pipelineIdentifier: "bulk-rnaseq" | "ont-analysis" }) {
  const [assets, setAssets] = useState<DemoStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [preparing, setPreparing] = useState(false);
  const [error, setError] = useState("");
  const controllerRef = useRef<AbortController | null>(null);

  const refresh = useCallback(async (signal: AbortSignal) => {
    const result = await apiRequest<DemoStatus>(`/api/v1/demos/${pipelineIdentifier}/status`, { signal });
    setAssets(result);
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

  const prepare = async () => {
    const controller = controllerRef.current;
    if (!controller) return;
    setPreparing(true);
    setError("");
    try {
      const result = await apiRequest<DemoStatus>(
        `/api/v1/demos/${pipelineIdentifier}/prepare`,
        { method: "POST", body: JSON.stringify({ consent: true }), signal: controller.signal },
      );
      if (!controller.signal.aborted) setAssets(result);
    } catch (reason) {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Demo assets could not be prepared.");
    } finally {
      if (!controller.signal.aborted) setPreparing(false);
    }
  };

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
        <button className="button secondary" type="button" onClick={() => void prepare()} disabled={assets.available || preparing}>
          {preparing ? "Preparing…" : assets.available ? "Demo assets ready" : "Prepare lightweight demo assets"}
        </button>
      </>}
    </section>
  );
}
