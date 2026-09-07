import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/api.ts", import.meta.url), "utf8");

async function loadApi() {
  const testSource = source.replace("import.meta.env.VITE_API_BASE_URL", "undefined");
  const compiled = ts.transpileModule(testSource, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }).outputText.replace('from "./types";', 'from "data:text/javascript,export{}";');
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
    await assert.rejects(apiRequest("/conflict"), (error) => error instanceof ApiError && error.message === "Project is locked" && error.fields[0] === "manifest");
  } finally {
    globalThis.fetch = previousFetch;
    timers.restore();
  }
});
