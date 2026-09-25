import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { saveTextFile } from "../native";
import type { CommandLogChunk } from "../types";

const DEFAULT_POLL_MS = 2_000;

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function processLabel(status: string | undefined, quietMs: number | null): string {
  const normalized = (status ?? "idle").toLowerCase();
  if (normalized === "running" || normalized === "preparing" || normalized === "queued" || normalized === "cancelling") {
    if (quietMs !== null && quietMs >= 60_000) {
      return `Running (no new output for ${formatDuration(quietMs)}; this does not mean the process is frozen)`;
    }
    return "Running";
  }
  if (normalized === "succeeded" || normalized === "completed") return "Completed";
  if (normalized === "failed") return "Failed";
  if (normalized === "cancelled" || normalized === "interrupted") return "Interrupted";
  return status ?? "Idle";
}

export function LiveCommandLog({
  title = "Command log",
  fetchChunk,
  active,
  status,
  stage,
  startedAt,
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
  lastOutputAt?: string | null;
  pollMs?: number;
  defaultExpanded?: boolean;
  resetKey?: string;
}) {
  const [text, setText] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState("");
  const [copyState, setCopyState] = useState("");
  const [now, setNow] = useState(() => Date.now());
  const [expanded, setExpanded] = useState(defaultExpanded);
  const follow = useRef(true);
  const preRef = useRef<HTMLPreElement | null>(null);
  const offsetRef = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    offsetRef.current = 0;
    setOffset(0);
    setText("");
    setError("");
    setCopyState("");
  }, [resetKey]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (!expanded && !active) return;
    let timer: number | undefined;
    const controller = new AbortController();
    let polling = false;

    const poll = async () => {
      if (polling || controller.signal.aborted) return;
      polling = true;
      try {
        const chunk = await fetchChunk(offsetRef.current, controller.signal);
        if (!mounted.current || controller.signal.aborted) return;
        if (chunk.text) {
          setText((existing) => existing + chunk.text);
        }
        offsetRef.current = chunk.next_offset;
        setOffset(chunk.next_offset);
        setError("");
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
  }, [active, expanded, fetchChunk, pollMs, resetKey]);

  useLayoutEffect(() => {
    const element = preRef.current;
    if (element && follow.current) element.scrollTop = element.scrollHeight;
  }, [text]);

  const startedMs = startedAt ? Date.parse(startedAt) : Number.NaN;
  const lastOutputMs = lastOutputAt ? Date.parse(lastOutputAt) : Number.NaN;
  const elapsedMs = Number.isFinite(startedMs) ? now - startedMs : null;
  const quietMs = Number.isFinite(lastOutputMs) ? now - lastOutputMs : null;

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopyState("Copied to clipboard.");
    } catch {
      setCopyState("Clipboard copy failed.");
    }
  };

  const save = async () => {
    try {
      const path = await saveTextFile("Save command log", "missus-tom-command.log", text || "No log output yet.\n", "log");
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
          {elapsedMs !== null ? <span><strong>Elapsed:</strong> {formatDuration(elapsedMs)}</span> : null}
          {quietMs !== null ? <span><strong>Last output:</strong> {formatDuration(quietMs)} ago</span> : <span><strong>Last output:</strong> waiting</span>}
          <span><strong>Bytes read:</strong> {offset.toLocaleString()}</span>
        </div>
        <div className="live-command-log-actions">
          <button type="button" className="text-button" onClick={() => void copy()} disabled={!text}>Copy</button>
          <button type="button" className="text-button" onClick={() => void save()}>Save…</button>
        </div>
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
          {text || (active ? "Waiting for command output…" : "No log output yet.")}
        </pre>
      </details>
    </section>
  );
}
