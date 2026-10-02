import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const runPlanSource = await readFile(
  new URL("../src/screens/RunPlanScreen.tsx", import.meta.url),
  "utf8",
);
const appSource = await readFile(new URL("../src/App.tsx", import.meta.url), "utf8");

test("run start remains natively busy until authoritative polling reconciles it", () => {
  const busy = runPlanSource.indexOf("await onStarting()");
  const start = runPlanSource.indexOf('apiRequest<RunRecord>("/api/v1/runs/start"');

  assert.ok(busy >= 0 && start > busy);
  assert.doesNotMatch(runPlanSource.slice(start), /setRunOverlayActive\(false\)/);
  assert.match(runPlanSource, /authoritative run list confirms no active work/);
  assert.match(appSource, /runLifecycleGeneration\.current \+= 1/);
  assert.match(appSource, /runStartPending\.current = true/);
  assert.match(appSource, /active \|\| !runStartPending\.current/);
  assert.match(
    appSource,
    /generation !== runLifecycleGeneration\.current/,
  );
});

test("build-mode projects can quantify before a cached index exists", () => {
  assert.match(runPlanSource, /manifest\?\.reference_mode === "build"/);
  assert.match(runPlanSource, /reference_resources\.transcriptome_fasta/);
  assert.match(runPlanSource, /reference_resources\.annotation_gtf/);
  assert.match(runPlanSource, /reference_resources\.kallisto_index/);
  assert.match(runPlanSource, /includedSamples\.length > 0/);
  assert.doesNotMatch(
    runPlanSource,
    /!isOntPipeline\s*&&\s*manifest\?\.reference_resources\.kallisto_index/,
  );
});
