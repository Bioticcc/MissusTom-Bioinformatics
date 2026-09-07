import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/requestCoordinator.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { RequestCoordinator } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("newer refresh aborts and supersedes an older refresh", () => {
  const coordinator = new RequestCoordinator();
  const first = coordinator.start();
  const second = coordinator.start();

  assert.equal(first.signal.aborted, true);
  assert.equal(first.isCurrent(), false);
  assert.equal(second.signal.aborted, false);
  assert.equal(second.isCurrent(), true);
});

test("only the current refresh is permitted to commit a result", () => {
  const coordinator = new RequestCoordinator();
  const first = coordinator.start();
  const second = coordinator.start();
  let result = "";

  if (first.isCurrent()) result = "first";
  if (second.isCurrent()) result = "second";

  assert.equal(result, "second");
  second.finish();
  assert.equal(second.isCurrent(), true);
  coordinator.abort();
  assert.equal(second.isCurrent(), false);
});
