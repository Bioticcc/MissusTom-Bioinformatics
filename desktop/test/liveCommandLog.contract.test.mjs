import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const source = await readFile(new URL("../src/components/LiveCommandLog.tsx", import.meta.url), "utf8");
const typesSource = await readFile(new URL("../src/types.ts", import.meta.url), "utf8");

test("LiveCommandLog polls incremental command log chunks", () => {
  assert.match(source, /CommandLogChunk/);
  assert.match(source, /fetchChunk/);
  assert.match(source, /offsetRef\.current/);
  assert.match(source, /chunk\.next_offset/);
  assert.match(source, /live-command-log/);
  assert.match(source, /no new output for/);
});

test("shared types expose CommandLogChunk and extended run logs", () => {
  assert.match(typesSource, /export interface CommandLogChunk/);
  assert.match(typesSource, /next_offset: number/);
  assert.match(typesSource, /bytes_available: number/);
  assert.match(typesSource, /export interface DemoPrepareJob/);
  assert.match(typesSource, /execution_supported: boolean/);
  assert.match(typesSource, /next_offset\?: number \| null/);
});
