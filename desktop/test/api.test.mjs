import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");

async function loadApi() {
  const testSource = source.replaceAll("import.meta.env.VITE_API_BASE_URL", "undefined");
  const compiled = ts.transpileModule(testSource, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }).outputText
    .replace('from "./types";', 'from "data:text/javascript,export{}";')
    .replace('from "@tauri-apps/api/core";', 'from "data:text/javascript,export const invoke = async () => ({ base_url: \\"http://127.0.0.1:8765\\", ready: true });";');
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}#${Math.random()}`);
}

function installBrowserTimers() {
  const previousWindow = globalThis.window;
  let timer;
  globalThis.window = {
    setTimeout(callback) { timer = callback; return 1; },
    clearTimeout() { timer = undefined; },
  };
  return {
    fireTimer() { timer?.(); },
    restore() { globalThis.window = previousWindow; },
  };
}

function response({ ok = true, status = 200, statusText = "OK", json }) {
  return { ok, status, statusText, json };
}

test("apiRequest times out while a response body is still pending", async () => {
  const timers = installBrowserTimers();
  const previousFetch = globalThis.fetch;
  let bodyStarted;
  globalThis.fetch = async (_url, init) => response({
    json: () => new Promise((_, reject) => {
      bodyStarted();
      init.signal.addEventListener("abort", () => reject(new Error("body aborted")), { once: true });
    }),
  });
  try {
    const { ApiError, apiRequest } = await loadApi();
    const bodyPending = new Promise((resolve) => { bodyStarted = resolve; });
    const request = apiRequest("/pending");
    await bodyPending;
    timers.fireTimer();
    await assert.rejects(request, (error) => error instanceof ApiError && error.message.includes("did not respond within 15 seconds"));
  } finally {
    globalThis.fetch = previousFetch;
    timers.restore();
  }
});

test("apiRequest preserves a caller abort while the response body is pending", async () => {
  const timers = installBrowserTimers();
  const previousFetch = globalThis.fetch;
  const callerAbort = new Error("caller aborted request");
  let bodyStarted;
  globalThis.fetch = async (_url, init) => response({
    json: () => new Promise((_, reject) => {
      bodyStarted();
      init.signal.addEventListener("abort", () => reject(callerAbort), { once: true });
    }),
  });
  try {
    const { apiRequest } = await loadApi();
    const controller = new AbortController();
    const bodyPending = new Promise((resolve) => { bodyStarted = resolve; });
    const request = apiRequest("/caller-abort", { signal: controller.signal });
    await bodyPending;
    controller.abort();
    await assert.rejects(request, (error) => error === callerAbort);
  } finally {
    globalThis.fetch = previousFetch;
    timers.restore();
  }
});

test("apiRequest distinguishes unavailable, malformed, and HTTP failure responses", async () => {
  const timers = installBrowserTimers();
  const previousFetch = globalThis.fetch;
  try {
    const { ApiError, apiRequest } = await loadApi();
    globalThis.fetch = async () => { throw new TypeError("connection refused"); };
    await assert.rejects(apiRequest("/offline"), (error) => error instanceof ApiError && error.message.includes("backend is unavailable"));

    globalThis.fetch = async () => response({ json: async () => { throw new SyntaxError("not json"); } });
    await assert.rejects(apiRequest("/invalid"), (error) => error instanceof ApiError && error.message.includes("invalid response"));

    globalThis.fetch = async () => response({
      ok: false,
      status: 409,
      statusText: "Conflict",
      json: async () => ({ success: false, data: null, errors: [{ code: "blocked", message: "Project is locked", field: "manifest" }], meta: {} }),
    });
    await assert.rejects(apiRequest("/conflict"), (error) => error instanceof ApiError && error.status === 409 && error.message === "Project is locked" && error.fields[0] === "manifest");
  } finally {
    globalThis.fetch = previousFetch;
    timers.restore();
  }
});

test("setup install conflicts require HTTP 409 and a specific message", async () => {
  const { ApiError, setupInstallConflictMessage } = await loadApi();
  const concurrent = new ApiError("another dependency installation is already running", [], 409);
  const samePipeline = new ApiError("dependency installation is already running for this pipeline", [], 409);
  const activeRun = new ApiError("a workflow run is active or requires recovery", [], 409);
  const otherJob = new ApiError("another workflow job is active", [], 409);
  const bareInstallation = new ApiError("Installation failed", [], 409);
  const wrongStatus = new ApiError("another dependency installation is already running", [], 400);

  assert.match(setupInstallConflictMessage(concurrent), /another dependency installation/);
  assert.match(setupInstallConflictMessage(samePipeline), /another dependency installation/);
  assert.match(setupInstallConflictMessage(activeRun), /workflow run is active/);
  assert.match(setupInstallConflictMessage(otherJob), /workflow run is active/);
  assert.equal(setupInstallConflictMessage(bareInstallation), null);
  assert.equal(setupInstallConflictMessage(wrongStatus), null);
  assert.equal(setupInstallConflictMessage(new Error("already running")), null);
});

test("selectApiBaseUrl uses a packaged sidecar base and retains browser fallback", async () => {
  const { selectApiBaseUrl } = await loadApi();
  assert.equal(
    selectApiBaseUrl("http://127.0.0.1:8000", { base_url: "http://127.0.0.1:8765" }),
    "http://127.0.0.1:8765",
  );
  assert.equal(selectApiBaseUrl("http://127.0.0.1:8000", undefined), "http://127.0.0.1:8000");
});
