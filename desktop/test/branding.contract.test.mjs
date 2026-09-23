import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const visibleFiles = {
  readme: await readFile(new URL("../../README.md", import.meta.url), "utf8"),
  openQuestions: await readFile(new URL("../../docs/open_questions.md", import.meta.url), "utf8"),
  bulkWorkflow: await readFile(new URL("../../workflows/bulk_rnaseq/nextflow.config", import.meta.url), "utf8"),
  indexHtml: await readFile(new URL("../index.html", import.meta.url), "utf8"),
  packageJson: await readFile(new URL("../package.json", import.meta.url), "utf8"),
  app: await readFile(new URL("../src/App.tsx", import.meta.url), "utf8"),
  dashboard: await readFile(new URL("../src/screens/Dashboard.tsx", import.meta.url), "utf8"),
  cargo: await readFile(new URL("../src-tauri/Cargo.toml", import.meta.url), "utf8"),
  tauriRelease: await readFile(new URL("../src-tauri/tauri.release.conf.json", import.meta.url), "utf8"),
};

test("user-visible and package branding remains neutral", () => {
  assert.match(visibleFiles.indexHtml, /content="Missus Tom — a local bioinformatics project workbench"/);
  assert.match(visibleFiles.app, /<span>Local bioinformatics workbench<\/span>/);
  assert.match(visibleFiles.dashboard, /<p className="eyebrow">Local bioinformatics<\/p>/);
  assert.match(visibleFiles.cargo, /^description = "Local bioinformatics workbench"$/m);
  assert.match(visibleFiles.cargo, /^authors = \["Missus Tom contributors"\]$/m);

  for (const source of Object.values(visibleFiles)) {
    assert.doesNotMatch(source, /Yan Lab/i);
  }
});
