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
    transcriptomeFasta: "/refs/original.fa",
    annotationGtf: "/refs/genes.gtf",
    kallistoIndex: "/refs/transcripts.idx",
    transcriptToGene: "",
  });
  assert.deepEqual(indexResources, {
    kallisto_index: "/refs/transcripts.idx",
    annotation_gtf: "/refs/genes.gtf",
    transcriptome_fasta: "/refs/original.fa",
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

test("backend capability loading blocks only Bulk project actions", () => {
  assert.equal(contract.projectActionsBlockedByBackend("bulk-rnaseq", false, null), true);
  assert.equal(contract.projectActionsBlockedByBackend("bulk-rnaseq", true, null), false);
  assert.equal(contract.projectActionsBlockedByBackend("bulk-rnaseq", true, "old backend"), true);
  assert.equal(contract.projectActionsBlockedByBackend("ont-analysis", false, "Bulk only"), false);
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

test("debug settings restore current and short-lived seven-step Bulk wizard positions", () => {
  assert.equal(contract.resolveImportedWizardStep("bulk-rnaseq", 3, "Experimental design"), 3);
  assert.equal(contract.resolveImportedWizardStep("bulk-rnaseq", 3, "Sample review"), 2);
  assert.equal(contract.resolveImportedWizardStep("bulk-rnaseq", 5, "Comparisons"), 5);
  assert.equal(contract.resolveImportedWizardStep("bulk-rnaseq", 8, undefined), 8);
  assert.equal(contract.resolveImportedWizardStep("bulk-rnaseq", 2, "Kallisto discovery"), 1);
  assert.equal(contract.resolveImportedWizardStep("ont-analysis", 7, "Review & save"), 6);
});

test("unstranded libraries omit a Kallisto strandedness flag", () => {
  assert.match(contractSource, /No strandedness flag\./);
  assert.doesNotMatch(contractSource, /--fr-stranded false/);
});

test("forward and reverse libraries describe the exact Kallisto flags", () => {
  assert.match(contractSource, /Read 1 maps in transcript orientation; Kallisto uses --fr-stranded\./);
  assert.match(contractSource, /Read 1 maps antisense to the transcript; Kallisto uses --rf-stranded\./);
  assert.match(contractSource, /Common first-strand protocols are usually RF/);
  assert.doesNotMatch(contractSource, /Forward \(FR \/ first-strand\)/);
  assert.doesNotMatch(contractSource, /Reverse \(RF \/ second-strand\)/);
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
  assert.match(wizardSource, /Advanced: use an existing Kallisto index/);
  assert.match(wizardSource, /Missus Tom will validate the FASTA and GTF/);
  assert.doesNotMatch(wizardSource, /human BioMart/);
  assert.doesNotMatch(wizardSource, /name="bulk-reference-mode"/);
  assert.match(wizardSource, /const bulkHealthPending = !isOntPipeline && !healthReady/);
  assert.match(wizardSource, /Checking backend compatibility/);
  assert.match(wizardSource, /backendBlocksProjectActions/);
  assert.match(wizardSource, /disabled=\{backendBlocksProjectActions && index > step\}/);
  assert.match(wizardSource, /!isOntPipeline && healthReady && !bulkCompatError/);
  assert.match(wizardSource, /Backend busy/);
  assert.doesNotMatch(wizardSource, /Compatible Bulk backend connected/);
  assert.match(wizardSource, /Jump to latest/);
  assert.match(wizardSource, /validationFollow/);
  assert.match(wizardSource, /busy === "plan"/);
  assert.match(wizardSource, /const bulkSteps = \[\s*"Project & directories",\s*"FASTQ discovery",\s*"Sample review",\s*"Experimental design",\s*"Figures \(Experimental\)",\s*"Comparisons",\s*"Pipeline options",\s*"Preflight validation",\s*"Review & save"/);
  assert.match(wizardSource, /<h2>Figures \(Experimental\)<\/h2>/);
  assert.match(wizardSource, /const ontSteps = \[\s*"Project & directories",\s*"BAM selection",\s*"Sample review"/);
  assert.doesNotMatch(wizardSource, /Manage sample inputs/);
  assert.doesNotMatch(wizardSource, /sample-id-inline/);
  assert.match(wizardSource, /samples\.slice\(0, 8\)/);
  assert.match(wizardSource, /includedSamples\.slice\(0, 8\)/);
  assert.match(wizardSource, /Expand sample list/);
  assert.match(wizardSource, /Review sample inclusion, identifiers, input paths, and pairing status/);
  assert.match(wizardSource, /resolveImportedWizardStep/);
  assert.match(wizardSource, /Experimental design type/);
  assert.match(wizardSource, /experimental_design_type: options\.experimentalDesignType/);
  assert.match(wizardSource, /~ biological_replicate \+ condition/);
  assert.match(wizardSource, /Adjust for Batch Effects/);
  assert.match(wizardSource, /adjust_for_batch_effects: options\.adjustForBatchEffects/);
});

test("project preflight uses an operation-specific timeout and keeps timeout errors distinct", () => {
  assert.match(wizardSource, /streamProjectValidation/);
  assert.match(wizardSource, /validationController.current\?\.abort/);
  assert.match(wizardSource, /setValidatedManifest\(null\)/);
});

test("figure gallery uses offline illustrations and confirms custom figure drafts", () => {
  assert.match(wizardSource, /function FigureThumbnail/);
  assert.doesNotMatch(wizardSource, /figure-thumbnail" aria-hidden/);
  assert.match(wizardSource, /const \[figureDraft, setFigureDraft\]/);
  assert.match(wizardSource, /<FigureEditor/);
  assert.match(wizardSource, /editingFigureId \? current\.custom_figures\.map/);
  assert.match(wizardSource, /: \[\.\.\.current\.custom_figures, figure\]/);
  assert.match(wizardSource, /setFigureDraft\(null\); setEditingFigureId\(null\);/);
});
