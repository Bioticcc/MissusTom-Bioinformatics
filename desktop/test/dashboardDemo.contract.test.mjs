import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/screens/Dashboard.tsx", import.meta.url), "utf8");

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
