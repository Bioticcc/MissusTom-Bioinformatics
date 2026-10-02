import { invoke } from "@tauri-apps/api/core";
import { BUILD_REVISION, DEVELOPMENT_BUILD_REVISION } from "./appVersion";
import type { ApiEnvelope, HealthStatus } from "./types";

const BROWSER_API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const REQUEST_TIMEOUT_MS = 15_000;
export const PROJECT_VALIDATION_TIMEOUT_MS = 120_000;

export type ApiRequestOptions = {
  timeoutMs?: number;
  timeoutMessage?: string;
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
  backendBasePromise ??= invoke<BackendStatus>("backend_status")
    .then((status) => {
      if (status.packaged && !status.ready) {
        const detail = status.startup_error || "The packaged backend did not become ready.";
        const log = status.startup_log?.trim();
        throw new Error(log ? `${detail}\n\nBackend startup log:\n${log}` : detail);
      }
      return selectApiBaseUrl(BROWSER_API_BASE, status);
    });
  return backendBasePromise;
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
  const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const timeoutMessage = options.timeoutMessage ?? `The local backend did not respond within ${timeoutMs / 1000} seconds. Try again.`;
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const abortFromCaller = () => controller.abort();
  init?.signal?.addEventListener("abort", abortFromCaller, { once: true });
  if (init?.signal?.aborted) controller.abort();

  try {
    let response: Response;
    try {
      const apiBase = await resolveApiBaseUrl();
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
