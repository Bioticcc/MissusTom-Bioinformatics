import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const source = await readFile(new URL("../src/automaticSettings.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText.replace('from "./types";', 'from "data:text/javascript,export{}";');
const automatic = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

function sample(sampleId, conditionFiles) {
  return {
    sample_id: sampleId,
    r1_files: [`/data/${conditionFiles}_R1.fastq.gz`],
    r2_files: [`/data/${conditionFiles}_R2.fastq.gz`],
    ont_bam_files: [],
    abundance_tsv: null,
    lanes: [],
    pairing_status: "paired",
    warnings: [],
    condition: "",
    biological_replicate: "",
    batch: null,
    covariates: {},
    included: true,
  };
}

test("automatic settings infer conditions and replicates from repeated filename categories", () => {
  const result = automatic.inferAutomaticSettings([
    sample("control_rep1", "control_rep1"),
    sample("control_rep2", "control_rep2"),
    sample("treated_rep1", "treated_rep1"),
    sample("treated_rep2", "treated_rep2"),
  ]);
  assert.deepEqual(result.suggestions.map(({ condition, biological_replicate }) => ({ condition, biological_replicate })), [
    { condition: "control", biological_replicate: "1" },
    { condition: "control", biological_replicate: "2" },
    { condition: "treated", biological_replicate: "1" },
    { condition: "treated", biological_replicate: "2" },
  ]);
  assert.deepEqual(result.inferredFields, ["condition", "biological_replicate"]);
});

test("automatic settings recognizes explicit batch and intervention markers", () => {
  const first = sample("control_rep1_batchA_drugA", "control_rep1_batchA_drugA");
  const second = sample("treated_rep1_batchB_drugB", "treated_rep1_batchB_drugB");
  const result = automatic.inferAutomaticSettings([first, second]);
  assert.equal(result.suggestions[0].batch, "A");
  assert.equal(result.suggestions[0].intervention, "A");
  assert.equal(result.suggestions[1].batch, "B");
  assert.equal(result.suggestions[1].intervention, "B");
});

test("automatic settings leaves ambiguous filenames blank and explains why", () => {
  const result = automatic.inferAutomaticSettings([
    sample("sample", "sample"),
    sample("sample", "sample"),
  ]);
  assert.equal(result.suggestions.length, 0);
  assert.ok(result.warnings.some((warning) => warning.includes("unambiguous")));
});
