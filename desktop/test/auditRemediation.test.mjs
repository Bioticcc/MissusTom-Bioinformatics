import assert from "node:assert/strict";
import { readFile, mkdtemp, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import ts from "typescript";

async function load(name) {
  const source = await readFile(new URL(`../src/${name}.ts`, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);
}

test("metadata replacement clears stale intervention/replicate and preserves row identity", async () => {
  const { applyMetadataImport } = await load("metadataImport");
  const samples = [{ sample_id: "A", condition: "old", batch: "old", biological_replicate: "old",
    covariates: { intervention: "drug_A", sex: "female" } }, { sample_id: "unmatched" }];
  const result = applyMetadataImport(samples, { path: "/metadata.csv", rows: [{
    sample_id: "original_A", source_sample_id: "original_A", matched_sample_id: "A",
    condition: "control", batch: null, biological_replicate: null, intervention: null,
  }] });
  assert.equal(result[0].covariates.intervention, undefined);
  assert.equal(result[0].biological_replicate, "");
  assert.equal(result[0].covariates.sex, "female");
  assert.equal(result[0].metadata_source_sample_id, "original_A");
  assert.equal(result[0].metadata_source_path, "/metadata.csv");
  assert.equal(result[1], samples[1]);
  assert.equal(samples[0].covariates.intervention, "drug_A");
});

test("renderer tail stays bounded for a large log and retains its final output", async () => {
  const { appendLogTail, LOG_PREVIEW_CHARACTERS } = await load("commandLog");
  let text = "";
  for (let index = 0; index < 1000; index++) {
    text = appendLogTail(text, "x".repeat(32768));
    assert.ok(text.length <= LOG_PREVIEW_CHARACTERS);
  }
  text = appendLogTail(text, "FINAL OUTPUT");
  assert.ok(text.endsWith("FINAL OUTPUT"));
});

test("clipboard export reads all chunks in order and refuses an unbounded allocation", async () => {
  const { readClipboardLog, CLIPBOARD_LOG_BYTES } = await load("commandLog");
  const signal = new AbortController().signal;
  const fetch = async (offset) => ({ text: "abcdef".slice(offset, offset + 2), next_offset: offset + 2, bytes_available: 6 });
  assert.equal(await readClipboardLog(fetch, signal), "abcdef");
  await assert.rejects(readClipboardLog(async () => ({ bytes_available: CLIPBOARD_LOG_BYTES + 1 }), signal), /too large/);
  await assert.rejects(readClipboardLog(async () => ({ text: "", next_offset: 0, bytes_available: 6 }), signal), /changed/);
});

test("dependency policy blocks high severity and incomplete advisory reports", async () => {
  const root = await mkdtemp(join(tmpdir(), "missustom-policy-"));
  try {
    const file = join(root, "audit.json");
    const run = (report) => writeFile(file, JSON.stringify(report)).then(() => spawnSync(process.execPath,
      [new URL("../../scripts/audit-dependencies.mjs", import.meta.url).pathname, "--audit-file", file], { encoding: "utf8" }));
    const report = { metadata: { vulnerabilities: { high: 1, critical: 0 } }, vulnerabilities: { tool: { name: "tool", severity: "high", via: [] } } };
    assert.equal((await run(report)).status, 1);
    report.vulnerabilities.tool.severity = "moderate";
    report.metadata.vulnerabilities.high = 0;
    assert.equal((await run(report)).status, 0);
    assert.equal((await run({ error: { summary: "offline" } })).status, 1);
    assert.equal((await run({ metadata: { vulnerabilities: { high: 1, critical: 0 } }, vulnerabilities: {} })).status, 1);
  } finally { await rm(root, { recursive: true }); }
});
