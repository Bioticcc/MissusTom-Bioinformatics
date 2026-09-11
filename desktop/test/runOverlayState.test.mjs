import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/runOverlayState.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
  .replace('from "./types";', 'from "data:text/javascript,export{}";');
const state = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

function run(overrides) {
  return { status: "completed", holds_admission: false, created_at: "2025-01-01T00:00:00Z", started_at: null, ...overrides };
}

test("selectActiveRun chooses the newest active record and ignores completed records", () => {
  const selected = state.selectActiveRun([
    run({ job_identifier: "done", status: "completed" }),
    run({ job_identifier: "old", status: "running", started_at: "2025-01-02T00:00:00Z" }),
    run({ job_identifier: "new", status: "preparing", started_at: "2025-01-03T00:00:00Z" }),
  ]);
  assert.equal(selected.job_identifier, "new");
  assert.equal(state.selectActiveRun([run({ job_identifier: "done" })]), null);
});

test("selectActiveRun retains admission cleanup and latestLogMessage handles terminal formatting", () => {
  assert.equal(state.selectActiveRun([run({ job_identifier: "cleanup", status: "interrupted", holds_admission: true })]).job_identifier, "cleanup");
  assert.equal(state.latestLogMessage("first line\r\u001b[32mlatest message\u001b[0m\r \n"), "latest message");
  assert.equal(state.latestLogMessage("\n "), "No log output yet.");
});
