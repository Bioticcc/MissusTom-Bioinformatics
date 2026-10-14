import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { saveTextFile } from "../native";
import { elapsedMs, formatDuration, isTerminalStatus, lastOutputLabel } from "../runPresentation";
import type { CommandLogChunk } from "../types";

const DEFAULT_POLL_MS = 2_000;
const LOG_PREVIEW_CHARACTERS = 131_072;

function processLabel(status: string | undefined, quietMs: number | null): string {
  const normalized = (status ?? "idle").toLowerCase();
  if (normalized === "running" || normalized === "preparing" || normalized === "queued" || normalized === "cancelling") {
    const label = normalized === "preparing" ? "Preparing" : normalized === "queued" ? "Queued" : normalized === "cancelling" ? "Stopping" : "Running";
    if (quietMs !== null && quietMs >= 60_000) {
      return `${label} (no new output for ${formatDuration(quietMs)}; this does not mean the process is frozen)`;
    }
    return label;
  }
  if (normalized === "succeeded" || normalized === "completed") return "Completed";
  if (normalized === "failed") return "Failed";
  if (normalized === "cancelled") return "Cancelled";
  if (normalized === "interrupted") return "Interrupted";
  return status ?? "Idle";
}

export function LiveCommandLog({
  title = "Command log",
  fetchChunk,
  active,
  status,
  stage,
  startedAt,
  finishedAt,
  lastOutputAt,
  pollMs = DEFAULT_POLL_MS,
  defaultExpanded = true,
  resetKey,
}: {
  title?: string;
  fetchChunk: (offset: number, signal: AbortSignal) => Promise<CommandLogChunk>;
  active: boolean;
  status?: string;
  stage?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  lastOutputAt?: string | null;
  pollMs?: number;
  defaultExpanded?: boolean;
  resetKey?: string;
}) {
  const [previewText, setPreviewText] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [copyState, setCopyState] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [expanded, setExpanded] = useState(defaultExpanded);
  const follow = useRef(true);
  const preRef = useRef<HTMLPreElement | null>(null);
  const offsetRef = useRef(0);
  const fullTextRef = useRef("");
  const fetchChunkRef = useRef(fetchChunk);
  const mounted = useRef(true);
  fetchChunkRef.current = fetchChunk;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    offsetRef.current = 0;
    fullTextRef.current = "";
    setOffset(0);
    setPreviewText("");
    setError("");
    setCopyState("");
  }, [resetKey]);

  useEffect(() => {
    if (!active || isTerminalStatus(status)) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [active, status]);

  useEffect(() => {
    if (!expanded) return;
    let timer: number | undefined;
    const controller = new AbortController();
    let polling = false;

    const poll = async () => {
      if (polling || controller.signal.aborted) return;
      polling = true;
      try {
        const chunk = await fetchChunkRef.current(offsetRef.current, controller.signal);
        if (!mounted.current || controller.signal.aborted) return;
        if (chunk.text) {
          fullTextRef.current += chunk.text;
          setPreviewText(fullTextRef.current.slice(-LOG_PREVIEW_CHARACTERS));
        }
        offsetRef.current = chunk.next_offset;
        setOffset((previous) => previous === chunk.next_offset ? previous : chunk.next_offset);
        setError((previous) => previous ? "" : previous);
      } catch (reason) {
        if (mounted.current && !controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Log output could not be loaded.");
        }
      } finally {
        polling = false;
        if (mounted.current && !controller.signal.aborted && active) {
          timer = window.setTimeout(() => void poll(), pollMs);
        }
      }
    };

    void poll();
    return () => {
      controller.abort();
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [active, expanded, pollMs, resetKey]);

  useLayoutEffect(() => {
    const element = preRef.current;
    if (element && follow.current) element.scrollTop = element.scrollHeight;
  }, [previewText]);

  const lastOutputMs = lastOutputAt ? Date.parse(lastOutputAt) : Number.NaN;
  const terminal = isTerminalStatus(status);
  const runElapsedMs = elapsedMs(startedAt, finishedAt, status, now);
  const quietMs = !terminal && Number.isFinite(lastOutputMs) ? Math.max(0, now - lastOutputMs) : null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(fullTextRef.current);
      setCopyState("Copied to clipboard.");
    } catch {
      setCopyState("Clipboard copy failed.");
    }
  };

  const save = async () => {
    try {
      const path = await saveTextFile("Save command log", "missus-tom-command.log", fullTextRef.current || "No log output yet.\n", "log");
      setCopyState(path ? `Saved to ${path}` : "Save cancelled.");
    } catch (reason) {
      setCopyState(reason instanceof Error ? reason.message : "Log could not be saved.");
    }
  };

  return (
    <section className="live-command-log" aria-live="polite">
      <details open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
        <summary>{title}</summary>
        <div className="live-command-log-meta">
          <span><strong>Status:</strong> {processLabel(status, quietMs)}</span>
          {stage ? <span><strong>Stage:</strong> {stage}</span> : null}
          {runElapsedMs !== null ? <span><strong>Elapsed:</strong> {formatDuration(runElapsedMs)}</span> : null}
          {terminal && runElapsedMs === null ? <span><strong>Elapsed:</strong> Unconfirmed</span> : null}
          <span><strong>Last output:</strong> {lastOutputLabel(lastOutputAt, status, now)}</span>
          <span><strong>Bytes read:</strong> {offset.toLocaleString()}</span>
        </div>
        <div className="live-command-log-actions">
          <button type="button" className="text-button" onClick={() => void copy()} disabled={!fullTextRef.current}>Copy</button>
          <button type="button" className="text-button" onClick={() => void save()}>Save…</button>
        </div>
        {fullTextRef.current.length > LOG_PREVIEW_CHARACTERS && <p className="field-help">Showing recent output. Copy or Save includes all loaded output.</p>}
        {copyState && <p className="field-help" role="status">{copyState}</p>}
        {error && <div className="inline-error" role="alert">{error}</div>}
        <pre
          aria-label={title}
          className="command-preview job-log"
          onScroll={(event) => {
            const element = event.currentTarget;
            follow.current = element.scrollHeight - element.scrollTop - element.clientHeight <= 8;
          }}
          ref={preRef}
        >
          {previewText || (active && !terminal ? "Waiting for command output…" : "No log output yet.")}
        </pre>
      </details>
    </section>
  );
}
