import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/components/PipelineDemoAssets.tsx", import.meta.url), "utf8");

test("PipelineDemoAssets uses the synchronous demo status and preparation contract", () => {
  assert.match(source, /`\/api\/v1\/demos\/\$\{pipelineIdentifier\}\/status`/);
  assert.match(source, /`\/api\/v1\/demos\/\$\{pipelineIdentifier\}\/prepare`/);
  assert.match(source, /method: "POST", body: JSON\.stringify\(\{ consent: true \}\)/);
  assert.match(source, /assets\.available/);
  assert.match(source, /assets\.message/);
  assert.match(source, /assets\.execution_note/);
  assert.match(source, /assets\.bundle_directory/);
  assert.match(source, /assets\.manifest_path/);
  assert.match(source, /Local self-consistency:/);
  assert.doesNotMatch(source, /Integrity:/);
  assert.doesNotMatch(source, /\/api\/v1\/pipelines\/.*demo-assets/);
  assert.doesNotMatch(source, /assets\.job|POLL_INTERVAL_MS|setInterval/);
});
