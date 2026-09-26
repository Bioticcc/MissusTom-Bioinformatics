import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import ts from "typescript";

const contractSource = await readFile(
  new URL("../src/newProjectWizardContract.ts", import.meta.url),
  "utf8",
);
const wizardSource = await readFile(
  new URL("../src/screens/NewProjectWizard.tsx", import.meta.url),
  "utf8",
);

const compiled = ts.transpileModule(contractSource, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 },
}).outputText;
const contract = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString("base64")}`);

test("bulk manifest contract versions and reference resources", () => {
  assert.equal(contract.BULK_MANIFEST_SCHEMA_VERSION, "1.1.0");
  assert.equal(contract.BULK_PIPELINE_VERSION, "0.5.0");

  const buildResources = contract.buildBulkReferenceResources("quantification", "build", {
    transcriptomeFasta: "/refs/transcripts.fa",
    annotationGtf: "/refs/genes.gtf",
    kallistoIndex: "/refs/should-not-appear.idx",
    transcriptToGene: "/refs/should-not-appear.txt",
  });
  assert.deepEqual(buildResources, {
    transcriptome_fasta: "/refs/transcripts.fa",
    annotation_gtf: "/refs/genes.gtf",
  });

  const indexResources = contract.buildBulkReferenceResources("quantification", "existing-index", {
    transcriptomeFasta: "",
    annotationGtf: "/refs/genes.gtf",
    kallistoIndex: "/refs/transcripts.idx",
    transcriptToGene: "",
  });
  assert.deepEqual(indexResources, {
    kallisto_index: "/refs/transcripts.idx",
    annotation_gtf: "/refs/genes.gtf",
  });

  const indexT2gResources = contract.buildBulkReferenceResources("quantification", "existing-index", {
    transcriptomeFasta: "",
    annotationGtf: "",
    kallistoIndex: "/refs/transcripts.idx",
    transcriptToGene: "/refs/t2g.txt",
  });
  assert.deepEqual(indexT2gResources, {
    kallisto_index: "/refs/transcripts.idx",
    transcript_to_gene: "/refs/t2g.txt",
  });

  const analysisResources = contract.buildBulkReferenceResources("analysis", "existing-index", {
    transcriptomeFasta: "/refs/ignored.fa",
    annotationGtf: "/refs/genes.gtf",
    kallistoIndex: "/refs/ignored.idx",
    transcriptToGene: "",
  });
  assert.deepEqual(analysisResources, { annotation_gtf: "/refs/genes.gtf" });
});

test("reference mode resolution and comparison validation", () => {
  assert.equal(contract.resolveBulkReferenceMode("quantification", "build"), "build");
  assert.equal(contract.resolveBulkReferenceMode("quantification", "existing-index"), "existing-index");
  assert.equal(contract.resolveBulkReferenceMode("analysis", "build"), "existing-index");

  const groups = contract.includedConditionGroups([
    { included: true, condition: "Treated" },
    { included: true, condition: "Control" },
    { included: false, condition: "Excluded" },
    { included: true, condition: "  " },
  ]);
  assert.deepEqual(groups, ["Control", "Treated"]);

  assert.equal(contract.validateComparisonSelection("Treated", "Control", groups), null);
  assert.equal(contract.validateComparisonSelection("", "Control", groups), "Choose both a numerator and a denominator condition.");
  assert.equal(contract.validateComparisonSelection("Treated", "Treated", groups), "Choose two different groups for the comparison.");
  assert.equal(
    contract.validateComparisonSelection("Missing", "Control", groups),
    'Numerator "Missing" is not an included sample condition.',
  );

  assert.match(contract.comparisonLabel("Treated", "Control", null), /positive log2FC means higher expression in Treated/);
});

test("import merge revalidates legacy bulk wizard options", () => {
  const merged = contract.mergeImportedBulkOptions(
    {
      adapterR1: contract.DEFAULT_ADAPTER_R1,
      adapterR2: contract.DEFAULT_ADAPTER_R2,
      maxParallelTasks: 1,
      strandedness: "reverse",
      referenceMode: "build",
    },
    { readLayout: "single-end", strandedness: "unknown", maxParallelTasks: 0, executionProfile: "apptainer" },
    "bulk-rnaseq",
  );
  assert.equal(merged.readLayout, "paired-end");
  assert.equal(merged.strandedness, "reverse");
  assert.equal(merged.maxParallelTasks, 1);
  assert.equal(merged.executionProfile, "local");
  assert.equal(merged.referenceMode, "build");
});

test("unstranded libraries omit a Kallisto strandedness flag", () => {
  assert.match(
    contractSource,
    /Recorded as unstranded; Kallisto runs without a strandedness flag\./,
  );
  assert.doesNotMatch(contractSource, /--fr-stranded false/);
});

test("forward and reverse libraries describe the exact Kallisto flags", () => {
  assert.match(contractSource, /Recorded as forward; Kallisto uses --fr-stranded\./);
  assert.match(contractSource, /Recorded as reverse; Kallisto uses --rf-stranded\./);
});

test("wizard UI encodes production bulk controls", () => {
  assert.match(wizardSource, /schema_version: isOntPipeline \? ONT_MANIFEST_SCHEMA_VERSION : BULK_MANIFEST_SCHEMA_VERSION/);
  assert.match(
    wizardSource,
    /\.\.\.\(!isOntPipeline \? \{ reference_mode: bulkReferenceMode \} : \{\}\)/,
  );
  assert.match(wizardSource, /\.\.\.\(isOntPipeline \? \{\} : \{ start_stage: startStage \}\)/);
  assert.doesNotMatch(wizardSource, /start_stage: startStage, reference_mode:/);
  assert.match(wizardSource, /read_layout: isOntPipeline \? "single-end" : "paired-end"/);
  assert.doesNotMatch(wizardSource, /single-end<\/option>/);
  assert.doesNotMatch(wizardSource, /Unknown \(confirm\)/);
  assert.match(wizardSource, /unassigned_files/);
  assert.doesNotMatch(wizardSource, /discovery\.files\.slice\(0, 12\)/);
  assert.match(wizardSource, /maxParallelTasks/);
  assert.match(wizardSource, /export_version: 3/);
  assert.match(wizardSource, /STRANDEDNESS_UI_OPTIONS/);
  assert.match(wizardSource, /positive log2 fold change means higher expression/);
});
