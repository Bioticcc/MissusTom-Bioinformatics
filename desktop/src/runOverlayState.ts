import type { RunRecord, RunStatus } from "./types";

const activeStatuses = new Set<RunStatus>(["queued", "preparing", "running", "cancelling"]);
const ansiEscapeSequence = new RegExp(`${String.fromCharCode(27)}\\[[0-?]*[ -/]*[@-~]`, "g");

export function isActiveRun(run: RunRecord): boolean {
  return activeStatuses.has(run.status) || run.holds_admission;
}

/** Prefer the most recently started active run when persisted records contain more than one. */
export function selectActiveRun(runs: RunRecord[]): RunRecord | null {
  return runs
    .filter(isActiveRun)
    .sort((left, right) => Date.parse(right.started_at ?? right.created_at) - Date.parse(left.started_at ?? left.created_at))[0] ?? null;
}

export function latestLogMessage(text: string): string {
  const lines = text.replace(ansiEscapeSequence, "").split(/[\r\n]/);
  for (let index = lines.length - 1; index >= 0; index -= 1) {
    const message = lines[index].trim();
    if (message) return message;
  }
  return "No log output yet.";
}

export function formatRunStartedAt(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "Not started yet";
}
