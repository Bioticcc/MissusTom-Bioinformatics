import { invoke } from "@tauri-apps/api/core";
import { BUILD_REVISION, DEVELOPMENT_BUILD_REVISION } from "./appVersion";
import type { ApiEnvelope, HealthStatus } from "./types";

const BROWSER_API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
export const SHORT_REQUEST_TIMEOUT_MS = 5_000;
export const STANDARD_REQUEST_TIMEOUT_MS = 30_000;
export const LONG_REQUEST_TIMEOUT_MS = 120_000;
export const PROJECT_VALIDATION_TIMEOUT_MS = 120_000;

export type ApiRequestKind = "short" | "standard" | "long";

export type ApiRequestOptions = {
  timeoutMs?: number;
  timeoutMessage?: string;
  requestKind?: ApiRequestKind;
};

export type BackendStatus = {
  base_url: string;
  ready: boolean;
  packaged: boolean;
  startup_error?: string | null;
  startup_log_path?: string | null;
  startup_log?: string;
};

let backendBasePromise: Promise<string> | undefined;

function isDesktopShell() {
  return "__TAURI_INTERNALS__" in window;
}

export function selectApiBaseUrl(
  browserBase: string,
  backend: Pick<BackendStatus, "base_url"> | undefined,
): string {
  return backend?.base_url || browserBase;
}

export async function resolveApiBaseUrl(): Promise<string> {
  if (import.meta.env.VITE_API_BASE_URL) return BROWSER_API_BASE;
  if (!isDesktopShell()) return BROWSER_API_BASE;
  const pending = backendBasePromise ??= invoke<BackendStatus>("backend_status")
    .then((status) => {
      if (status.packaged && !status.ready) {
        const detail = status.startup_error || "The packaged backend did not become ready.";
        const log = status.startup_log?.trim();
        throw new Error(log ? `${detail}\n\nBackend startup log:\n${log}` : detail);
      }
      return selectApiBaseUrl(BROWSER_API_BASE, status);
    });
  try {
    return await pending;
  } catch (reason) {
    // A sidecar commonly reports not-ready while it is still binding its port.
    // Do not let one transient Tauri result poison every later API call.
    if (backendBasePromise === pending) backendBasePromise = undefined;
    throw reason;
  }
}

function timeoutFor(options: ApiRequestOptions): number {
  if (options.timeoutMs !== undefined) return options.timeoutMs;
  if (options.requestKind === "short") return SHORT_REQUEST_TIMEOUT_MS;
  if (options.requestKind === "long") return LONG_REQUEST_TIMEOUT_MS;
  return STANDARD_REQUEST_TIMEOUT_MS;
}

async function resolveWithin(signal: AbortSignal): Promise<string> {
  return await new Promise<string>((resolve, reject) => {
    const abort = () => reject(new DOMException("Request aborted", "AbortError"));
    signal.addEventListener("abort", abort, { once: true });
    void resolveApiBaseUrl().then(resolve, reject).finally(() => signal.removeEventListener("abort", abort));
  });
}

export async function getBackendStatus(): Promise<BackendStatus | undefined> {
  if (!isDesktopShell()) return undefined;
  try {
    return await invoke<BackendStatus>("backend_status");
  } catch {
    return undefined;
  }
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly fields: string[] = [],
    public readonly status?: number,
    public readonly code?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function bulkProductionBackendError(
  health: HealthStatus | null | undefined,
  frontendRevision = BUILD_REVISION,
): string | null {
  if (!health || health.status !== "ok") {
    return "The local backend did not report a compatible health response. Install a matching Missus Tom build before creating a production Bulk RNA-seq project.";
  }
  if (health.capabilities?.bulk_fasta_gtf_reference_preparation !== true) {
    return "This interface requires a backend that prepares Bulk RNA-seq references from FASTA and GTF. The connected backend is too old. Install a matching Missus Tom build.";
  }
  const backendRevision = health.build_revision?.trim();
  if (!backendRevision) {
    return "The local backend did not report build provenance. Install a matching Missus Tom build before creating a production Bulk RNA-seq project.";
  }
  if (frontendRevision !== backendRevision) {
    const frontendLabel = frontendRevision || DEVELOPMENT_BUILD_REVISION;
    return `The interface build (${frontendLabel}) does not match the backend build (${backendRevision}). Restart Missus Tom from one complete installation or reinstall the matching package.`;
  }
  return null;
}

export function setupInstallConflictMessage(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  if (error.code === "dependency_install_in_progress") {
    return "The backend is busy with another dependency installation. The completed work is saved; retry to resume.";
  }
  if (error.code === "workflow_admission_locked") {
    return "A workflow run is active or needs recovery. Dependency installation stays locked until that run is finished.";
  }
  return null;
}

export async function apiRequest<T>(
  path: string,
  init?: RequestInit,
  options: ApiRequestOptions = {},
): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const controller = new AbortController();
  const timeoutMs = timeoutFor(options);
  const timeoutMessage = options.timeoutMessage ?? `The local backend request timed out after ${timeoutMs / 1000} seconds. The operation may still be running.`;
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const abortFromCaller = () => controller.abort();
  init?.signal?.addEventListener("abort", abortFromCaller, { once: true });
  if (init?.signal?.aborted) controller.abort();

  try {
    let response: Response;
    try {
      const apiBase = await resolveWithin(controller.signal);
      response = await fetch(`${apiBase}${path}`, { ...init, headers, signal: controller.signal });
    } catch (reason) {
      if (init?.signal?.aborted) throw reason;
      if (controller.signal.aborted) throw new ApiError(timeoutMessage);
      throw new ApiError("The local backend is unavailable. Start it on 127.0.0.1:8000 and try again.");
    }

    let envelope: ApiEnvelope<T>;
    try {
      envelope = (await response.json()) as ApiEnvelope<T>;
    } catch (reason) {
      if (init?.signal?.aborted) throw reason;
      if (controller.signal.aborted) throw new ApiError(timeoutMessage);
      throw new ApiError("The local backend returned an invalid response.");
    }
    if (!response.ok || !envelope.success || envelope.data === null) {
      const errorCounts = new Map<string, number>();
      envelope.errors?.forEach((error) => {
        errorCounts.set(error.message, (errorCounts.get(error.message) ?? 0) + 1);
      });
      const message = [...errorCounts.entries()]
        .map(([text, count]) => count > 1 ? `${text} (${count} fields)` : text)
        .join("; ") || response.statusText;
      const fields = envelope.errors?.flatMap((error) => (error.field ? [error.field] : [])) ?? [];
      const code = envelope.errors?.find((error) => error.code)?.code;
      throw new ApiError(message, fields, response.status, code);
    }
    return envelope.data;
  } finally {
    window.clearTimeout(timeout);
    init?.signal?.removeEventListener("abort", abortFromCaller);
  }
}

/** Stream real backend validation operations and return the authoritative final result. */
export async function streamProjectValidation(
  manifest: import("./types").ProjectManifest,
  onProgress: (message: string) => void,
  signal?: AbortSignal,
): Promise<import("./types").ProjectValidation> {
  const controller = new AbortController();
  let timer: ReturnType<typeof window.setTimeout>;
  let timedOut = false;
  const resetTimeout = () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { timedOut = true; controller.abort(); }, PROJECT_VALIDATION_TIMEOUT_MS);
  };
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) controller.abort();
  resetTimeout();
  let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
  try {
    const apiBase = await resolveWithin(controller.signal);
    const response = await fetch(`${apiBase}/api/v1/projects/validate/stream`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(manifest), signal: controller.signal,
    });
    if (!response.ok) {
      let envelope: ApiEnvelope<never> | undefined;
      try {
        envelope = await response.json() as ApiEnvelope<never>;
      } catch {
        throw new ApiError(`Validation request failed with an invalid response (${response.status}).`, [], response.status);
      }
      throw new ApiError(envelope.errors?.map((error) => error.message).join("; ") || `Validation request failed (${response.status}).`, [], response.status);
    }
    if (!response.body) throw new ApiError("The backend did not provide a validation stream.");
    reader = response.body.getReader();
    const decoder = new TextDecoder();
    let pending = "";
    while (true) {
      const { value, done } = await reader.read();
      pending += decoder.decode(value, { stream: !done });
      if (value?.length) resetTimeout();
      const lines = pending.split("\n");
      pending = lines.pop() ?? "";
      if (done && pending.trim()) { lines.push(pending); pending = ""; }
      for (const line of lines) {
        if (!line.trim()) continue;
        let event: import("./types").ValidationEvent;
        try {
          event = JSON.parse(line) as import("./types").ValidationEvent;
        } catch {
          throw new ApiError("The backend returned an invalid validation event.");
        }
        if (event.type === "progress" && typeof event.message === "string") onProgress(event.message);
        else if (event.type === "error" && typeof event.message === "string") throw new ApiError(event.message);
        else if (event.type === "result" && typeof event.result?.valid === "boolean" && Array.isArray(event.result.checks) && event.result.manifest) return event.result;
        else throw new ApiError("The backend returned an invalid validation event.");
      }
      if (done) throw new ApiError("Validation stream ended before the backend returned its results. Run checks again.");
    }
  } catch (reason) {
    if (timedOut) throw new ApiError("No validation progress received for 120 seconds. The backend may still be finishing a check.");
    throw reason;
  } finally {
    window.clearTimeout(timer!);
    signal?.removeEventListener("abort", abort);
    await reader?.cancel().catch(() => undefined);
    controller.abort();
  }
}
