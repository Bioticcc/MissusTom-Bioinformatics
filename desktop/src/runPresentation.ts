import type { RunRecord } from "./types";

const terminalStatuses = new Set(["completed", "failed", "cancelled", "interrupted", "succeeded"]);

export function isTerminalStatus(status: string | undefined): boolean {
  return terminalStatuses.has((status ?? "").toLowerCase());
}

export function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

export function elapsedMs(startedAt: string | null | undefined, finishedAt: string | null | undefined, status: string | undefined, now: number): number | null {
  const start = startedAt ? Date.parse(startedAt) : Number.NaN;
  const finish = finishedAt ? Date.parse(finishedAt) : Number.NaN;
  if (!Number.isFinite(start) || (isTerminalStatus(status) && !Number.isFinite(finish))) return null;
  return Math.max(0, (Number.isFinite(finish) ? finish : now) - start);
}

export function lastOutputLabel(lastOutputAt: string | null | undefined, status: string | undefined, now: number): string {
  const lastOutput = lastOutputAt ? Date.parse(lastOutputAt) : Number.NaN;
  if (isTerminalStatus(status)) return Number.isFinite(lastOutput) ? new Date(lastOutput).toLocaleString() : "not recorded";
  return Number.isFinite(lastOutput) ? `${formatDuration(now - lastOutput)} ago` : "waiting";
}

export function finishedTime(run: RunRecord): string {
  if (run.finished_at) return new Date(run.finished_at).toLocaleString();
  return isTerminalStatus(run.status) ? "Unconfirmed" : "—";
}

export function outcomeLabel(run: RunRecord): string {
  if (run.status === "cancelled" && run.error_message === "Cancelled by user") return "Cancelled by user";
  return run.status;
}
