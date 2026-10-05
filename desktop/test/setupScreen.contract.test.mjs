import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const dashboardSource = await readFile(new URL("../src/screens/Dashboard.tsx", import.meta.url), "utf8");
const setupSource = await readFile(new URL("../src/screens/Setup.tsx", import.meta.url), "utf8");
const wizardSource = await readFile(new URL("../src/screens/NewProjectWizard.tsx", import.meta.url), "utf8");
const styles = await readFile(new URL("../src/styles.css", import.meta.url), "utf8");

test("first launch is setup-only until setup completes", () => {
  assert.match(appSource, /loadSetupState\(window\.localStorage\)\.completed/);
  assert.match(appSource, /\? "setup" : "dashboard"/);
  assert.match(appSource, /navigation\.filter\(\(item\) => item\.id === "setup"\)/);
  assert.match(appSource, /setSetupRequired\(false\)/);
});

test("setup restores completed and running debug jobs", () => {
  assert.match(setupSource, /Promise\.allSettled\(\[/);
  assert.match(setupSource, /dependencies/);
  assert.match(setupSource, /fixtures/);
  assert.match(setupSource, /setLiveJob\(restored\)/);
  assert.match(setupSource, /Local setup section in Step 1/);
  assert.match(setupSource, /dependencies\/jobs\/active/);
  assert.doesNotMatch(setupSource, /setDependencyInstallActive/);
});

test("setup and validation expose debug terminals while work is active", () => {
  assert.match(setupSource, /Starting setup and waiting for the backend job/);
  assert.match(wizardSource, /validation-debug-terminal/);
  assert.match(wizardSource, /streamProjectValidation/);
  assert.match(dashboardSource, /Backend diagnostics/);
  assert.match(dashboardSource, /startup_log_path/);
});

test("new project setup explains where additional pipeline installation lives", () => {
  assert.match(wizardSource, /Need another pipeline\?/);
  assert.match(wizardSource, /Local setup section below/);
});

test("focus treatment is a simple green outline", () => {
  assert.match(styles, /outline: 2px solid var\(--green-500\)/);
  assert.match(styles, /outline-offset: 1px/);
  assert.match(styles, /input::-webkit-search-cancel-button/);
  assert.match(styles, /appearance: none/);
});
