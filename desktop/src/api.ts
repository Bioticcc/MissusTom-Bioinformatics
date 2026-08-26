import type { ApiEnvelope } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000";

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

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
    });
  } catch {
    throw new ApiError("The local backend is unavailable. Start it on 127.0.0.1:8000 and try again.");
  }

  const envelope = (await response.json()) as ApiEnvelope<T>;
  if (!response.ok || !envelope.success || envelope.data === null) {
    const message = envelope.errors?.map((error) => error.message).join("; ") || response.statusText;
    const fields = envelope.errors?.flatMap((error) => (error.field ? [error.field] : [])) ?? [];
    throw new ApiError(message, fields);
  }
  return envelope.data;
}
