import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";

const settings = await readFile(new URL("../src/screens/Settings.tsx", import.meta.url), "utf8");
const app = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");
const native = await readFile(new URL("../src/native.ts", import.meta.url), "utf8");
const host = await readFile(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");

test("Settings provides a labeled local performance recorder and shortcut", () => {
  assert.match(settings, /Performance diagnostics/);
  assert.match(settings, /State being tested/);
  assert.match(settings, /Start recording/);
  assert.match(settings, /Stop recording/);
  assert.match(settings, /Performance diagnostics keyboard shortcut/);
  assert.match(settings, /active-run/);
  assert.match(settings, /large-log/);
  assert.match(app, /matchesPerformanceDiagnosticsShortcut/);
  assert.match(app, /startPerformanceDiagnostics/);
  assert.match(app, /stopPerformanceDiagnostics/);
});

test("host-owned diagnostics use timestamped state-labelled local files", () => {
  assert.match(native, /start_performance_diagnostics/);
  assert.match(native, /stop_performance_diagnostics/);
  assert.match(host, /PERFORMANCE_DIAGNOSTICS_DIRECTORY/);
  assert.match(host, /desktop-performance-\{\}-\{file_timestamp\}\.ndjson/);
  assert.match(host, /valid_performance_state_label/);
  assert.match(host, /process_tree_metrics/);
  assert.match(host, /local_health_sample/);
  assert.match(settings, /Recording never starts, stops, or changes an analysis/);
});
