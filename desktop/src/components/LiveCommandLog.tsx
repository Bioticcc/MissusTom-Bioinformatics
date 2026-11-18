import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { saveLogFile } from "../native";
import { appendLogTail, CLIPBOARD_LOG_BYTES, LOG_PREVIEW_CHARACTERS, readClipboardLog } from "../commandLog";
import { elapsedMs, formatDuration, isTerminalStatus, lastOutputLabel } from "../runPresentation";
import type { CommandLogChunk } from "../types";

const DEFAULT_POLL_MS = 2_000;

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
  const [copying, setCopying] = useState(false);
  const copyController = useRef<AbortController>();
  const [now, setNow] = useState(() => Date.now());
  const [expanded, setExpanded] = useState(defaultExpanded);
  const follow = useRef(true);
  const preRef = useRef<HTMLPreElement | null>(null);
  const offsetRef = useRef(0);
  const logPathRef = useRef<string | null>(null);
  const [bytesAvailable, setBytesAvailable] = useState(0);
  const fetchChunkRef = useRef(fetchChunk);
  const mounted = useRef(true);
  fetchChunkRef.current = fetchChunk;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      copyController.current?.abort();
    };
  }, []);

  useEffect(() => {
    offsetRef.current = 0;
    copyController.current?.abort();
    setCopying(false);
    logPathRef.current = null;
    setBytesAvailable(0);
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
    let hasMore = false;

    const poll = async () => {
      if (polling || controller.signal.aborted) return;
      polling = true;
      try {
        const chunk = await fetchChunkRef.current(offsetRef.current, controller.signal);
        if (!mounted.current || controller.signal.aborted) return;
        const restarted = chunk.next_offset < offsetRef.current;
        if (chunk.text || restarted) {
          setPreviewText((previous) => appendLogTail(restarted ? "" : previous, chunk.text));
        }
        logPathRef.current = chunk.log_path ?? logPathRef.current;
        setBytesAvailable(chunk.bytes_available);
        hasMore = chunk.next_offset > offsetRef.current && chunk.next_offset < chunk.bytes_available;
        // Skip a large historical backlog; complete export reads the on-disk log.
        offsetRef.current = Math.max(chunk.next_offset, chunk.bytes_available - LOG_PREVIEW_CHARACTERS);
        setOffset(offsetRef.current);
        setError((previous) => previous ? "" : previous);
      } catch (reason) {
        if (mounted.current && !controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Log output could not be loaded.");
        }
      } finally {
        polling = false;
        if (mounted.current && !controller.signal.aborted && (active || hasMore)) {
          timer = window.setTimeout(() => void poll(), hasMore ? 0 : pollMs);
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
    if (copying) return;
    const controller = new AbortController();
    copyController.current = controller;
    setCopying(true);
    try {
      const text = bytesAvailable > CLIPBOARD_LOG_BYTES ? previewText
        : await readClipboardLog(fetchChunkRef.current, controller.signal);
      if (controller.signal.aborted) return;
      await navigator.clipboard.writeText(text);
      setCopyState(bytesAvailable > CLIPBOARD_LOG_BYTES ? "Recent output copied. Save includes the complete log." : "Complete log copied to clipboard.");
    } catch (reason) {
      if (!controller.signal.aborted) setCopyState(reason instanceof Error ? reason.message : "Clipboard copy failed.");
    } finally {
      if (!controller.signal.aborted) setCopying(false);
    }
  };

  const save = async () => {
    try {
      if (!logPathRef.current) throw new Error("No log file is available yet.");
      const path = await saveLogFile(logPathRef.current);
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
          <span><strong>Log position:</strong> {offset.toLocaleString()}</span>
        </div>
        <div className="live-command-log-actions">
          <button type="button" className="text-button" onClick={() => void copy()} disabled={!previewText || copying}>{bytesAvailable > CLIPBOARD_LOG_BYTES ? "Copy recent output" : "Copy"}</button>
          <button type="button" className="text-button" onClick={() => void save()}>Save…</button>
        </div>
        {bytesAvailable > LOG_PREVIEW_CHARACTERS && <p className="field-help">Showing recent output. Save includes the complete log.</p>}
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
