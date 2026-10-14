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

test("setup requires fresh dependency verification after an installer job succeeds", () => {
  assert.match(setupSource, /status\.job\?\.status === "succeeded" && status\.missing\.length === 0/);
  assert.match(setupSource, /const joinedExistingInstall = status\.job\?\.status === "running"/);
  assert.match(setupSource, /status\.job\?\.status === "succeeded" \? "complete" : "failed"/);
  assert.match(setupSource, /Installation finished but verification still reports missing requirements/);
  assert.match(setupSource, /Installed and verified\./);
  assert.doesNotMatch(setupSource, /status\.missing\.length === 0 \|\| status\.job\?\.status === "succeeded"/);
});

test("setup and validation expose debug terminals while work is active", () => {
  assert.match(setupSource, /Starting setup and waiting for the backend job/);
  assert.match(setupSource, /getBackendStatus\(\)/);
  assert.match(setupSource, /native_containment/);
  assert.match(setupSource, /Native runs cannot start yet/);
  assert.match(setupSource, /Recheck/);
  assert.match(setupSource, /Backend startup diagnostics/);
  assert.match(setupSource, /Setup request:/);
  assert.match(setupSource, /Verifying \$\{pipeline\} dependencies/);
  assert.match(setupSource, /Setup completed\. Selected dependencies and fixtures are ready/);
  assert.match(setupSource, /onUpdate\(job\)/);
  assert.match(wizardSource, /validation-debug-terminal/);
  assert.match(wizardSource, /streamProjectValidation/);
  assert.match(dashboardSource, /Backend diagnostics/);
  assert.match(dashboardSource, /startup_log_path/);
});

test("redundant information banners do not occupy the dashboard or setup", () => {
  assert.doesNotMatch(dashboardSource, /Local pipeline workbench/);
  assert.doesNotMatch(setupSource, /development-banner setup-sequence-note/);
  assert.match(setupSource, /<details className="panel setup-sequence-note">/);
  assert.doesNotMatch(wizardSource, /Compatible Bulk backend connected/);
  assert.match(wizardSource, /Incompatible or unavailable backend/);
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
