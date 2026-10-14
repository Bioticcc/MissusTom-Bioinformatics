import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/runPresentation.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const presentation = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("terminal elapsed time and last output stop changing", () => {
  const start = "2026-01-01T10:00:00Z";
  const finish = "2026-01-01T10:05:00Z";
  const first = Date.parse("2026-01-01T10:06:00Z");
  const later = Date.parse("2026-01-02T10:06:00Z");
  assert.equal(presentation.elapsedMs(start, finish, "completed", first), 300_000);
  assert.equal(presentation.elapsedMs(start, finish, "completed", later), 300_000);
  assert.equal(presentation.lastOutputLabel(finish, "completed", first), presentation.lastOutputLabel(finish, "completed", later));
  assert.doesNotMatch(presentation.lastOutputLabel(finish, "completed", later), /ago/);
  assert.equal(presentation.elapsedMs(start, null, "interrupted", later), null);
});

test("active time remains live and terminal outcome names user cancellation", () => {
  const start = "2026-01-01T10:00:00Z";
  assert.equal(presentation.elapsedMs(start, null, "running", Date.parse("2026-01-01T10:01:00Z")), 60_000);
  assert.equal(presentation.lastOutputLabel(start, "running", Date.parse("2026-01-01T10:01:00Z")), "1m 0s ago");
  assert.equal(presentation.finishedTime({ status: "interrupted", finished_at: null }), "Unconfirmed");
  assert.equal(presentation.outcomeLabel({ status: "cancelled", error_message: "Cancelled by user" }), "Cancelled by user");
  assert.equal(presentation.outcomeLabel({ status: "cancelled", error_message: null }), "cancelled");
});
