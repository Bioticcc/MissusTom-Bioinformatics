import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const source = await readFile(new URL("../src/projectEditor.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const { loadProjectEditor, preserveExistingProject } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

const saved = {
  project_identifier: "project-1",
  created_at: "2026-01-01T00:00:00Z",
  project_name: "Saved project",
  input_directory: "/data/input",
  output_directory: "/data/output",
  pipeline_identifier: "bulk-rnaseq",
  organism: "Homo sapiens",
  reference_genome: "GRCh38",
  annotation_source: "GENCODE",
  reference_mode: "existing-index",
  reference_resources: { kallisto_index: "/ref/index", custom_reference: "/ref/custom" },
  reference_provenance: { checked: true },
  library_type: "total RNA",
  strandedness: "reverse",
  execution_profile: "local",
  resource_profile: { cpus: 8, memory_gb: 32, max_parallel_tasks: 2 },
  parameters: { start_stage: "quantification", trim_quality: 20, custom_parameter: 7 },
  samples: [{ sample_id: "sample-1", r1_files: ["/data/r1.fq.gz"], r2_files: ["/data/r2.fq.gz"], ont_bam_files: [], abundance_tsv: null, condition: "control", biological_replicate: "1", batch: null, covariates: {}, included: true }],
  comparisons: [],
  pipeline_status: "completed",
};

test("saved project values populate the editor", () => {
  const loaded = loadProjectEditor(saved, { trimQuality: 10, adapterR1: "default", adapterR2: "default", minimumReadLength: 20 });
  assert.equal(loaded.details.projectName, "Saved project");
  assert.equal(loaded.options.kallistoIndex, "/ref/index");
  assert.equal(loaded.options.trimQuality, 20);
  assert.equal(loaded.samples[0].sample_id, "sample-1");
  loaded.samples[0].r1_files.push("/data/new.fq.gz");
  assert.equal(saved.samples[0].r1_files.length, 1);
});

test("editing retains identity and extension fields while invalidating saved status", () => {
  const edited = { ...saved, project_identifier: "new-id", created_at: "new-time", project_name: "Changed", reference_resources: { kallisto_index: "/ref/index" }, parameters: { start_stage: "quantification", trim_quality: 25 } };
  const result = preserveExistingProject(saved, edited);
  assert.equal(result.project_identifier, "project-1");
  assert.equal(result.created_at, saved.created_at);
  assert.equal(result.project_name, "Changed");
  assert.equal(result.pipeline_status, "draft");
  assert.equal(result.reference_resources.custom_reference, "/ref/custom");
  assert.equal(result.parameters.custom_parameter, 7);
  assert.deepEqual(result.reference_provenance, saved.reference_provenance);
  const changedReference = preserveExistingProject(saved, { ...edited, reference_resources: { kallisto_index: "/ref/other" } });
  assert.equal(changedReference.reference_provenance, null);
});
