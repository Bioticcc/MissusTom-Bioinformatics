import { invoke } from "@tauri-apps/api/core";
import type { ApiEnvelope } from "./types";

const BROWSER_API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";
const REQUEST_TIMEOUT_MS = 15_000;

export type BackendStatus = {
  base_url: string;
  ready: boolean;
  packaged: boolean;
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
        throw new Error("The packaged backend is not ready.");
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
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
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
      if (controller.signal.aborted) throw new ApiError("The local backend did not respond within 15 seconds. Try again.");
      throw new ApiError("The local backend is unavailable. Start it on 127.0.0.1:8000 and try again.");
    }

    let envelope: ApiEnvelope<T>;
    try {
      envelope = (await response.json()) as ApiEnvelope<T>;
    } catch (reason) {
      if (init?.signal?.aborted) throw reason;
      if (controller.signal.aborted) throw new ApiError("The local backend did not respond within 15 seconds. Try again.");
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
      throw new ApiError(message, fields);
    }
    return envelope.data;
  } finally {
    window.clearTimeout(timeout);
    init?.signal?.removeEventListener("abort", abortFromCaller);
  }
}
