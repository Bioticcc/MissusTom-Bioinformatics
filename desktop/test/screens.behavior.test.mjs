import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import { webcrypto } from "node:crypto";
import test from "node:test";
import React from "react";
import Renderer, { act } from "react-test-renderer";
import { build } from "esbuild";

const require = createRequire(import.meta.url);
const reactUrl = pathToFileURL(require.resolve("react")).href;
globalThis.crypto ??= webcrypto;

async function screen(relative) {
  const result = await build({
    entryPoints: [fileURLToPath(new URL(`../src/${relative}.tsx`, import.meta.url))],
    bundle: true, write: false, format: "esm", platform: "node", jsx: "transform",
    jsxFactory: "React.createElement", jsxFragment: "React.Fragment",
    banner: { js: `import * as React from ${JSON.stringify(reactUrl)};` },
    define: { "import.meta.env.VITE_BUILD_REVISION": '"development"' },
    plugins: [{ name: "screen-boundaries", setup(builder) {
      builder.onResolve({ filter: /^react(?:\/.*)?$/ }, (args) => ({ path: pathToFileURL(require.resolve(args.path)).href, external: true }));
      builder.onResolve({ filter: /\/api$/ }, () => ({ path: "api", namespace: "mock" }));
      builder.onResolve({ filter: /\/native$/ }, () => ({ path: "native", namespace: "mock" }));
      builder.onResolve({ filter: /\/components\// }, (args) => args.kind === "entry-point" ? undefined
        : ({ path: args.path.split("/").pop(), namespace: "component" }));
      builder.onLoad({ filter: /.*/, namespace: "component" }, (args) => ({ contents: `export const ${args.path} = () => null;` }));
      builder.onLoad({ filter: /.*/, namespace: "mock" }, (args) => ({ contents: args.path === "api"
        ? 'export const apiRequest=(...args)=>globalThis.__screenMocks.apiRequest(...args); export const bulkProductionBackendError=()=>null; export const streamProjectValidation=()=>Promise.reject(new Error("unexpected validation"));'
        : ["selectFiles", "selectDirectory", "readTextFile", "saveTextFile", "saveLogFile", "openDirectory", "isDesktopShell"].map((name) => `export const ${name}=(...args)=>globalThis.__screenMocks.${name}?.(...args);`).join("\n") }));
    } }],
  });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString("base64")}#${Math.random()}`);
}

function browser() {
  const original = globalThis.window;
  globalThis.window = { setTimeout, clearTimeout, setInterval, clearInterval,
    localStorage: { getItem: () => null }, confirm: () => true };
  return () => { globalThis.window = original; delete globalThis.__screenMocks; };
}
const flush = () => new Promise((resolve) => setImmediate(resolve));
const text = (node) => node.children.map((child) => typeof child === "string" ? child : text(child)).join("");
const button = (root, label) => root.findAllByType("button").find((node) => text(node) === label);
async function click(node) { assert.ok(node); await act(async () => { node.props.onClick(); await flush(); }); }

test("ONT scan reviews, groups, and excludes files before replacing existing samples", async () => {
  const restoreBrowser = browser(); let view; let exported;
  globalThis.__screenMocks = {
    apiRequest: async (path, options) => {
      if (path === "/health") return { status: "ok", version: "0.4.8" };
      if (path !== "/api/v1/ont/discover") return [];
      assert.equal(JSON.parse(options.body).directory, "/input");
      return { directory: "/input", total_files: 3, total_bytes: 9, warnings: ["Review grouping"],
        files: ["A", "B", "C"].map(name => ({ path: `/input/${name}.bam`, size_bytes: 3 })),
        samples: ["A", "B", "C"].map(sample_id => ({ sample_id, ont_bam_files: [`/input/${sample_id}.bam`],
          pairing_status: "single", included: true, warnings: [] })) };
    },
    selectFiles: async () => ["/input/manual.bam"],
    saveTextFile: async (_title, _name, contents) => { exported = JSON.parse(contents); return "/settings.json"; },
  };
  try {
    const { NewProjectWizard } = await screen("screens/NewProjectWizard");
    await act(async () => { view = Renderer.create(React.createElement(NewProjectWizard, { onProjectReady() {} })); await flush(); });
    await act(async () => view.root.findAllByType("input").filter(node => node.props.name === "pipeline")[1].props.onChange());
    const input = view.root.findAllByType("label").find(node => text(node).startsWith("ONT BAM source directory")).findByType("input");
    await act(async () => input.props.onChange({ target: { value: "/input" } }));
    await click(button(view.root, "Continue"));
    await click(button(view.root, "Select BAM files…"));
    await click(button(view.root, "Scan directory"));
    await click(button(view.root, "Export settings"));
    assert.deepEqual(exported.wizard.samples[0].ont_bam_files, ["/input/manual.bam"]);
    await act(async () => view.root.findByProps({ "aria-label": "Scanned sample identifier 2" }).props.onChange({ target: { value: "A" } }));
    await act(async () => view.root.findByProps({ "aria-label": "Use scanned BAM 3" }).props.onChange({ target: { checked: false } }));
    await click(button(view.root, "Apply reviewed assignments"));
    assert.ok(view.root.findAllByType("h2").some(node => text(node) === "Review ONT BAM samples"));
    await click(button(view.root, "Export settings"));
    assert.equal(exported.wizard.samples.length, 1);
    assert.deepEqual(exported.wizard.samples[0].ont_bam_files, ["/input/A.bam", "/input/B.bam"]);
    await click(button(view.root, "Back"));
    await click(button(view.root, "Scan directory"));
    await click(button(view.root, "Dismiss scan"));
    await click(button(view.root, "Export settings"));
    assert.equal(exported.wizard.samples.length, 1);
    assert.deepEqual(exported.wizard.samples[0].ont_bam_files, ["/input/A.bam", "/input/B.bam"]);
  } finally { if (view) act(() => view.unmount()); restoreBrowser(); }
});

test("ONT species and assembly changes clear reference paths and preserve sample assignments", async () => {
  const restoreBrowser = browser(); let view; let exported;
  globalThis.__screenMocks = {
    apiRequest: async (path) => path === "/health" ? { status: "ok", version: "0.4.8" } : [],
    selectFiles: async () => ["/input/sample.bam"],
    saveTextFile: async (_title, _name, contents) => { exported = JSON.parse(contents); return "/settings.json"; },
  };
  const field = (root, label) => root.findAllByType("label").find(node => text(node).startsWith(label));
  try {
    const { NewProjectWizard } = await screen("screens/NewProjectWizard");
    await act(async () => { view = Renderer.create(React.createElement(NewProjectWizard, { onProjectReady() {} })); await flush(); });
    await act(async () => view.root.findAllByType("input").filter(node => node.props.name === "pipeline")[1].props.onChange());
    await click(button(view.root, "Continue"));
    await click(button(view.root, "Select BAM files…"));
    await click(button(view.root, "Continue"));
    await click(button(view.root, "Continue"));
    for (const key of ["referenceFasta", "referenceFai", "minimap2Index"]) {
      await act(async () => view.root.findByProps({ id: `reference-${key}` }).props.onChange({ target: { value: `/mouse/${key}` } }));
    }
    await act(async () => field(view.root, "Organism").findByType("select").props.onChange({ target: { value: "Homo sapiens" } }));
    assert.equal(field(view.root, "Reference genome").findByType("select").props.value, "GRCh38");
    await act(async () => field(view.root, "Modified-base measurements").findByType("select").props.onChange({ target: { value: "5mc_only" } }));
    await click(button(view.root, "Export settings"));
    assert.equal(exported.manifest_draft.parameters.modification_mode, "5mc_only");
    assert.equal(exported.wizard.options.organism, "Homo sapiens");
    assert.equal("minimap2_index" in exported.manifest_draft.reference_resources, false);
    for (const key of ["referenceFasta", "referenceFai", "minimap2Index", "gencodeGff3", "cpgIslands", "ccreTable", "intergenicBed"]) {
      assert.equal(exported.wizard.options[key], "");
    }
    assert.deepEqual(exported.wizard.samples[0].ont_bam_files, ["/input/sample.bam"]);
    await act(async () => view.root.findByProps({ id: "reference-referenceFasta" }).props.onChange({ target: { value: "/human/genome.fa" } }));
    await act(async () => field(view.root, "Reference genome").findByType("select").props.onChange({ target: { value: "hg19" } }));
    assert.equal(view.root.findByProps({ id: "reference-referenceFasta" }).props.value, "");
    await act(async () => field(view.root, "Organism").findByType("select").props.onChange({ target: { value: "Mus musculus" } }));
    assert.equal(field(view.root, "Reference genome").findByType("select").props.value, "GRCm38p6");
  } finally { if (view) act(() => view.unmount()); restoreBrowser(); }
});

test("SingleCell is selectable, exports the Seurat contract, and preserves both drafts", async () => {
  const restoreBrowser = browser(); let view; let exported; let exportName; let ready = false;
  const requests = [];
  globalThis.__screenMocks = {
    apiRequest: async (path, options) => {
      requests.push([path, options?.method]);
      return path === "/health" ? { status: "ok", version: "0.4.8" } : [];
    },
    saveTextFile: async (_title, name, contents, kind) => {
      assert.equal(kind, "settings"); exportName = name; exported = JSON.parse(contents);
      return "/exports/singlecell.json";
    },
    selectFiles: async () => ["/objects/islet atlas.rds"],
  };
  const pipeline = (root) => root.findAllByType("input").find((node) =>
    node.props.name === "pipeline" && text(node.parent).includes("SingleCell"));
  const field = (root, label) => root.findAllByType("label").find((node) => text(node).startsWith(label));
  const type = (root, label, value) => act(async () =>
    field(root, label).findByType("input").props.onChange({ target: { value } }));
  try {
    const { NewProjectWizard } = await screen("screens/NewProjectWizard");
    await act(async () => { view = Renderer.create(React.createElement(NewProjectWizard, {
      onProjectReady() { ready = true; },
    })); await flush(); });
    await act(async () => field(view.root, "Project name").findByType("input").props.onChange({ target: { value: "Keep Bulk draft" } }));
    assert.ok(pipeline(view.root));
    await act(async () => pipeline(view.root).props.onChange());
    assert.ok(view.root.findAllByType("h1").some((node) => text(node) === "SingleCell RNA-seq"));
    assert.match(text(view.root.findAllByProps({ role: "status" })[0]), /configuration and export only/);
    assert.equal(field(view.root, "Assay with raw counts").findByType("input").props.value, "RNA");
    assert.equal(field(view.root, "Sample column").findByType("input").props.value, "");
    assert.equal(view.root.findAllByType("label").some((node) => /FASTQ|chemistry/i.test(text(node))), false);
    await click(field(view.root, "Seurat object (.rds)").parent.findByType("button"));
    await type(view.root, "Sample column", "orig.ident");
    await type(view.root, "Condition column", "group");
    await click(button(view.root, "Export SingleCell configuration"));
    assert.equal(exportName, "singlecell-seurat-manifest.json");
    assert.equal(exported.schema_version, "singlecell-seurat-v1");
    assert.equal(exported.input.seurat_rds, "/objects/islet atlas.rds");
    assert.equal(exported.input.assay, "RNA");
    assert.equal(exported.input.metadata_columns.sample_id, "orig.ident");
    assert.equal(exported.input.metadata_columns.condition, "group");
    assert.equal(exported.input.metadata_columns.donor_id, "");
    assert.equal(ready, false);
    assert.ok(requests.every(([, method]) => !method || method === "GET"));
    await click(button(view.root, "Back to pipeline selection"));
    assert.equal(field(view.root, "Project name").findByType("input").props.value, "Keep Bulk draft");
    await act(async () => pipeline(view.root).props.onChange());
    assert.equal(field(view.root, "Seurat object (.rds)").findByType("input").props.value, "/objects/islet atlas.rds");
  } finally { if (view) act(() => view.unmount()); restoreBrowser(); }
});

test("unavailable custom sources can be restored without loading a file", async () => {
  const restoreBrowser = browser(); let view; let restored = false;
  globalThis.__screenMocks = { apiRequest: async (path) => {
    if (path.endsWith("/restore")) { restored = true; return {}; }
    return [{ pipeline_identifier: "bulk-rnaseq", display_name: "Bulk", source_type: restored ? "official" : "custom-unavailable", files: [] }];
  } };
  try {
    const { LearnAndModify } = await screen("screens/LearnAndModify");
    await act(async () => { view = Renderer.create(React.createElement(LearnAndModify, { isRunActive: false })); await flush(); });
    await click(button(view.root, "Restore Original Pipeline"));
    assert.equal(restored, true);
    assert.equal(button(view.root, "Restore Original Pipeline"), undefined);
  } finally { if (view) act(() => view.unmount()); restoreBrowser(); }
});

test("saved projects and settings imports retain metadata; pipeline/stage changes clear old inputs", async () => {
  const restoreBrowser = browser(); let view; let exported; let imported;
  globalThis.__screenMocks = {
    apiRequest: async (path) => path === "/health" ? { status: "ok", version: "0.4.8" } : [],
    saveTextFile: async (_title, _name, contents) => { exported = JSON.parse(contents); return "/settings.json"; },
    selectFiles: async () => ["/settings.json"], readTextFile: async () => JSON.stringify(imported),
  };
  const manifest = {
    schema_version: "1.1.0", project_identifier: "saved-project", project_name: "Saved",
    created_at: "2026-01-01T00:00:00Z", input_directory: "/input", output_directory: "/output",
    pipeline_identifier: "bulk-rnaseq", pipeline_version: "0.5.0", organism: "Homo sapiens",
    reference_genome: "GRCh38", annotation_source: "GENCODE", reference_mode: "build",
    reference_resources: {}, library_type: "total RNA", strandedness: "reverse", execution_profile: "local",
    resource_profile: { cpus: 2, memory_gb: 8, max_parallel_tasks: 1 }, parameters: {},
    samples: [{ sample_id: "A", r1_files: ["/input/A.fq"], r2_files: [], ont_bam_files: [],
      abundance_tsv: null, condition: "control", biological_replicate: "donor", batch: null,
      covariates: {}, included: true, metadata_source_sample_id: "CSV_A", metadata_source_path: "/metadata.csv" }],
    comparisons: [], pipeline_status: "draft",
  };
  try {
    const { NewProjectWizard } = await screen("screens/NewProjectWizard");
    await act(async () => { view = Renderer.create(React.createElement(NewProjectWizard, { initialManifest: manifest, onProjectReady() {} })); await flush(); });
    await click(button(view.root, "Export settings"));
    assert.equal(exported.manifest_draft.samples[0].metadata_source_sample_id, "CSV_A");
    imported = exported;
    act(() => view.unmount());
    await act(async () => { view = Renderer.create(React.createElement(NewProjectWizard, { onProjectReady() {} })); await flush(); });
    await click(button(view.root, "Import settings"));
    await click(button(view.root, "Export settings"));
    assert.equal(exported.wizard.samples[0].metadata_source_sample_id, "CSV_A");
    const pipeline = view.root.findAllByType("input").filter((node) => node.props.name === "pipeline");
    await act(async () => pipeline[1].props.onChange());
    await click(button(view.root, "Export settings"));
    assert.equal(exported.wizard.pipeline_identifier, "ont-analysis");
    assert.deepEqual(exported.wizard.samples, []);
    assert.deepEqual(exported.wizard.comparisons, []);
    assert.equal(exported.wizard.details.inputDirectory, "");
    await act(async () => view.root.findAllByType("input").filter((node) => node.props.name === "pipeline")[0].props.onChange());
    await act(async () => view.root.findAllByType("input").filter((node) => node.props.name === "setup-start-stage")[1].props.onChange());
    await click(button(view.root, "Export settings"));
    assert.equal(exported.wizard.start_stage, "analysis");
    assert.deepEqual(exported.wizard.samples, []);
    assert.equal(exported.wizard.validation, null);
  } finally { if (view) act(() => view.unmount()); restoreBrowser(); }
});

test("mounted log exports its complete disk file and bounds the displayed text", async () => {
  const restoreBrowser = browser(); let view; let saved; let reads = 0;
  globalThis.__screenMocks = { saveLogFile: async (path) => { saved = path; return "/export.log"; } };
  try {
    const { LiveCommandLog } = await screen("components/LiveCommandLog");
    const fetchChunk = async () => ++reads === 1 ? { text: "x".repeat(500000),
      log_path: "/original.log", bytes_available: 500000, next_offset: 500000 }
      : { text: "", log_path: "/original.log", bytes_available: 0, next_offset: 0 };
    await act(async () => { view = Renderer.create(React.createElement(LiveCommandLog, {
      active: false, status: "completed", fetchChunk,
    })); await flush(); });
    assert.equal(view.root.findByType("pre").children[0].length, 131072);
    await click(button(view.root, "Save…"));
    assert.equal(saved, "/original.log");
    await act(async () => { view.update(React.createElement(LiveCommandLog, { active: true, status: "completed", fetchChunk })); await flush(); });
    assert.equal(view.root.findByType("pre").children[0], "No log output yet.");
  } finally { if (view) act(() => view.unmount()); restoreBrowser(); }
});

test("Results displays ONT artifacts and opens samples, preserving Bulk and legacy folders", async () => {
  const restoreBrowser = browser(); let view; const opened = [];
  const ont = { job_identifier: "ont", pipeline_identifier: "ont-analysis", results_directory: "/ont/results", project_name: "ONT", status: "completed", created_at: "2026-11-04T12:00:00Z" };
  const bulk = { ...ont, job_identifier: "bulk", pipeline_identifier: "bulk-rnaseq", results_directory: "/bulk/results" };
  const legacy = { ...ont, job_identifier: "legacy", results_directory: "/legacy/results" };
  const artifact = (category, relative_path) => ({ category, relative_path, size_bytes: 100 });
  const files = {
    ont: [artifact("methylation_exploration", "results/samples/A/05_methylation_exploration/figures/plot.pdf"), artifact("methylation", "results/samples/A/04_methylation/global.tsv")],
    bulk: [artifact("counts", "results/counts/A/abundance.tsv")],
    legacy: [artifact("methylation_exploration", "results/05_methylation_exploration/figures/old.pdf")],
  };
  globalThis.__screenMocks = {
    apiRequest: async (path) => path === "/api/v1/runs" ? [ont, bulk, legacy] : files[path.split("/")[4]],
    openDirectory: async (path) => opened.push(path),
  };
  try {
    const { Results } = await screen("screens/Results");
    await act(async () => { view = Renderer.create(React.createElement(Results, { activeRun: ont })); await flush(); });
    assert.match(text(view.root), /Figures and reports/);
    assert.match(text(view.root), /results\/samples\/A\/.*plot.pdf/);
    assert.doesNotMatch(text(view.root), /Kallisto quantification/);
    await click(button(view.root, "Open output folder"));
    assert.equal(opened.at(-1), "/ont/results/samples");
    files.ont.push(artifact("project_qc", "results/project_qc/ont_project_qc_report.html"));
    await click(button(view.root, "Refresh files"));
    assert.match(text(view.root), /Project QC overview/);
    assert.match(text(view.root), /ont_project_qc_report.html/);
    await click(button(view.root, "Open output folder"));
    assert.equal(opened.at(-1), "/ont/results");
    await act(async () => view.root.findAllByType("select")[1].props.onChange({ target: { value: "methylation" } }));
    await act(async () => { view.root.findAllByType("select")[0].props.onChange({ target: { value: "bulk" } }); await flush(); });
    assert.match(text(view.root), /results\/counts\/A\/abundance.tsv/);
    assert.equal(view.root.findAllByType("select")[1].props.value, "all");
    await click(button(view.root, "Open output folder"));
    assert.equal(opened.at(-1), "/bulk/results");
    await act(async () => { view.root.findAllByType("select")[0].props.onChange({ target: { value: "legacy" } }); await flush(); });
    assert.match(text(view.root), /old.pdf/);
    await click(button(view.root, "Open output folder"));
    assert.equal(opened.at(-1), "/legacy/results");
  } finally { if (view) act(() => view.unmount()); restoreBrowser(); }
});

test("Jobs opens the published ONT sample directory and falls back when indexing is unavailable", async () => {
  const restoreBrowser = browser(); let view; const opened = []; let offline = false;
  const run = { job_identifier: "ont", pipeline_identifier: "ont-analysis", results_directory: "/ont/results", project_name: "ONT", status: "completed", holds_admission: false };
  globalThis.__screenMocks = {
    isDesktopShell: () => true,
    apiRequest: async () => { if (offline) throw new Error("offline"); return [{ relative_path: "results/samples/A/04_methylation/global.tsv" }]; },
    openDirectory: async (path) => opened.push(path),
  };
  try {
    const { Jobs } = await screen("screens/Jobs");
    await act(async () => { view = Renderer.create(React.createElement(Jobs, { activeRun: null, polledRuns: [run] })); await flush(); });
    await click(button(view.root, "Open output folder"));
    assert.equal(opened.at(-1), "/ont/results/samples");
    offline = true;
    await click(button(view.root, "Open output folder"));
    assert.equal(opened.at(-1), "/ont/results");
  } finally { if (view) act(() => view.unmount()); restoreBrowser(); }
});
