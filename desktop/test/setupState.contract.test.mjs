import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/setupState.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const setup = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

function storage() {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
}

test("setup completes only requested terminal actions", () => {
  let state = setup.defaultSetupState();
  assert.equal(setup.areRequestedActionsComplete(state), false);
  state = setup.recordSetupOutcome(state, "bulk-rnaseq", "fixtures", { state: "complete", reason: "prepared" });
  assert.equal(setup.areRequestedActionsComplete(state), false);
  state = setup.recordSetupOutcome(state, "bulk-rnaseq", "dependencies", { state: "skipped", reason: "already installed" });
  assert.equal(setup.areRequestedActionsComplete(state), true);
});

test("changing a requested action resets completion and persists valid state", () => {
  const local = storage();
  let state = setup.defaultSetupState();
  state = setup.recordSetupOutcome(state, "bulk-rnaseq", "fixtures", { state: "complete", reason: "prepared" });
  state = setup.recordSetupOutcome(state, "bulk-rnaseq", "dependencies", { state: "complete", reason: "installed" });
  setup.saveSetupState(local, state);
  assert.equal(setup.loadSetupState(local).completed, true);
  state = setup.updateSetupSelection(state, "bulk-rnaseq", "fixtures", false);
  assert.equal(state.completed, true);
  state = setup.updateSetupSelection(state, "bulk-rnaseq", "fixtures", true);
  assert.equal(state.completed, false);
});

test("invalid persisted values fall back to safe defaults", () => {
  const local = storage();
  local.setItem(setup.SETUP_STORAGE_KEY, '{"version":99}');
  assert.deepEqual(setup.loadSetupState(local), setup.defaultSetupState());
});
