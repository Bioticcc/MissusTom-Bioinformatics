import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/screens/Dashboard.tsx", import.meta.url), "utf8");
const nativeSource = await readFile(new URL("../src/native.ts", import.meta.url), "utf8");
const tauriSource = await readFile(new URL("../src-tauri/src/lib.rs", import.meta.url), "utf8");
const defaultCapability = JSON.parse(
  await readFile(new URL("../src-tauri/capabilities/default.json", import.meta.url), "utf8"),
);

test("Dashboard runs the bulk RNA-seq demo through prepare and project endpoints", () => {
  assert.match(source, /Run Bulk RNA-seq Demo/);
  assert.match(source, /\/api\/v1\/demos\/bulk-rnaseq\/status/);
  assert.match(source, /\/api\/v1\/demos\/bulk-rnaseq\/prepare/);
  assert.match(source, /\/api\/v1\/demos\/bulk-rnaseq\/project/);
  assert.match(source, /LiveCommandLog/);
  assert.match(source, /synthetic fixtures/);
  assert.doesNotMatch(source, /\/api\/v1\/demos\/human/);
  assert.doesNotMatch(source, /Load human demo/);
});

test("Desktop dialogs use app-owned pickers and host-owned text exports", () => {
  assert.match(source, /import \{ selectFiles \} from "\.\.\/native"/);
  assert.match(source, /selectFiles\("Open saved Missus Tom project"\)/);
  assert.match(source, /openProject\(selected\[0\]\)/);
  assert.match(nativeSource, /import \{ open \} from "@tauri-apps\/plugin-dialog"/);
  assert.match(nativeSource, /open\(\{ title, multiple \}\)/);
  assert.match(nativeSource, /open\(\{ title, directory: true \}\)/);
  assert.match(nativeSource, /invoke<string \| null>\("save_text_file", \{ title, suggestedName, contents, exportKind \}\)/);
  assert.match(nativeSource, /Array\.isArray\(selected\) \? selected : \[selected\]/);
  assert.match(nativeSource, /if \(!isDesktopShell\(\)\)/);
  assert.doesNotMatch(nativeSource, /invoke<string\[\] \| null>\("select_files"/);
  assert.match(tauriSource, /\.plugin\(tauri_plugin_dialog::init\(\)\)/);
  assert.doesNotMatch(tauriSource, /fn select_files\(/);
  assert.doesNotMatch(tauriSource, /fn select_directory\(/);
  assert.match(tauriSource, /async fn save_text_file\([\s\S]*export_kind: TextExportKind/);
  assert.doesNotMatch(tauriSource, /fn write_text_file\(/);
  assert.doesNotMatch(tauriSource, /zenity/);
  assert.match(tauriSource, /\.blocking_save_file\(\)/);
  assert.match(tauriSource, /symlink_metadata\(&destination\)/);
  assert.match(tauriSource, /enforce_export_extension/);
  assert.ok(defaultCapability.permissions.includes("dialog:allow-open"));
  assert.ok(!defaultCapability.permissions.includes("dialog:allow-save"));
  assert.ok(!defaultCapability.permissions.includes("dialog:default"));
});
