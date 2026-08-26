import { useMemo, useState } from "react";
import { apiRequest } from "../api";
import { CheckList } from "../components/CheckList";
import { FolderPreview } from "../components/FolderPreview";
import { selectDirectory } from "../native";
import type {
  Comparison,
  DirectoryPreview,
  FastqDiscoveryResult,
  ProjectManifest,
  ProjectValidation,
  ProposedSample,
  RunPlan,
} from "../types";

const steps = [
  "Project & directories",
  "FASTQ discovery",
  "Sample review",
  "Experimental design",
  "Comparisons",
  "Pipeline options",
  "Preflight validation",
  "Review & save",
];

interface DetailsState {
  projectName: string;
  inputDirectory: string;
  outputDirectory: string;
}

interface OptionsState {
  organism: string;
  referenceGenome: string;
  annotationSource: string;
  transcriptomeFasta: string;
  annotationGtf: string;
  biomart: string;
  libraryType: string;
  readLayout: "paired-end" | "single-end";
  strandedness: "unstranded" | "forward" | "reverse" | "unknown";
  executionProfile: "local" | "docker" | "apptainer";
  cpus: number;
  memoryGb: number;
  minimumReadLength: number;
}

function toSafeId(value: string) {
  return value.trim().replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^[_\-.]+|[_\-.]+$/g, "");
}

function formatBytes(bytes: number) {
  if (!bytes) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index > 2 ? 1 : 0)} ${units[index]}`;
}

export function NewProjectWizard({
  onProjectReady,
}: {
  onProjectReady: (manifest: ProjectManifest, plan: RunPlan) => void;
}) {
  const [step, setStep] = useState(0);
  const [details, setDetails] = useState<DetailsState>({
    projectName: "",
    inputDirectory: "",
    outputDirectory: "",
  });
  const [options, setOptions] = useState<OptionsState>({
    organism: "Mus musculus",
    referenceGenome: "GRCm39",
    annotationSource: "GENCODE (confirm release)",
    transcriptomeFasta: "",
    annotationGtf: "",
    biomart: "",
    libraryType: "total RNA",
    readLayout: "paired-end",
    strandedness: "unknown",
    executionProfile: "local",
    cpus: 4,
    memoryGb: 8,
    minimumReadLength: 20,
  });
  const [discovery, setDiscovery] = useState<FastqDiscoveryResult | null>(null);
  const [samples, setSamples] = useState<ProposedSample[]>([]);
  const [comparisons, setComparisons] = useState<Comparison[]>([]);
  const [numerator, setNumerator] = useState("");
  const [denominator, setDenominator] = useState("");
  const [validation, setValidation] = useState<ProjectValidation | null>(null);
  const [validatedManifest, setValidatedManifest] = useState<ProjectManifest | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [savedPath, setSavedPath] = useState("");
  const [inputPreview, setInputPreview] = useState<DirectoryPreview | null>(null);
  const [outputPreview, setOutputPreview] = useState<DirectoryPreview | null>(null);
  const projectId = useMemo(() => crypto.randomUUID(), []);
  const createdAt = useMemo(() => new Date().toISOString(), []);

  const groups = useMemo(
    () =>
      [...new Set(samples.filter((sample) => sample.included).map((sample) => sample.condition.trim()))]
        .filter(Boolean)
        .sort(),
    [samples],
  );

  const invalidateValidation = () => {
    setValidation(null);
    setValidatedManifest(null);
    setSavedPath("");
  };

  const updateDetails = (key: keyof DetailsState, value: string) => {
    setDetails((current) => ({ ...current, [key]: value }));
    if (key === "inputDirectory") setInputPreview(null);
    if (key === "outputDirectory") setOutputPreview(null);
    invalidateValidation();
  };

  const loadFolderPreview = async (kind: "input" | "output", directory: string) => {
    if (!directory.trim()) return;
    setBusy(`${kind}-preview`);
    setError("");
    try {
      const preview = await apiRequest<DirectoryPreview>("/api/v1/directories/preview", {
        method: "POST",
        body: JSON.stringify({ directory }),
      });
      if (kind === "input") setInputPreview(preview);
      else setOutputPreview(preview);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The folder could not be previewed.");
    } finally {
      setBusy("");
    }
  };

  const chooseFolder = async (kind: "input" | "output") => {
    setBusy(`${kind}-select`);
    setError("");
    try {
      const directory = await selectDirectory(
        kind === "input" ? "Select input FASTQ folder" : "Select project output folder",
      );
      if (!directory) return;
      const key = kind === "input" ? "inputDirectory" : "outputDirectory";
      setDetails((current) => ({ ...current, [key]: directory }));
      invalidateValidation();
      await loadFolderPreview(kind, directory);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The folder could not be selected.");
    } finally {
      setBusy("");
    }
  };

  const updateOptions = <K extends keyof OptionsState>(key: K, value: OptionsState[K]) => {
    setOptions((current) => ({ ...current, [key]: value }));
    invalidateValidation();
  };

  const updateSample = <K extends keyof ProposedSample>(
    index: number,
    key: K,
    value: ProposedSample[K],
  ) => {
    setSamples((current) =>
      current.map((sample, sampleIndex) =>
        sampleIndex === index ? { ...sample, [key]: value } : sample,
      ),
    );
    invalidateValidation();
  };

  const discover = async () => {
    setBusy("discover");
    setError("");
    try {
      const result = await apiRequest<FastqDiscoveryResult>("/api/v1/fastq/discover", {
        method: "POST",
        body: JSON.stringify({ directory: details.inputDirectory, recursive: true }),
      });
      setDiscovery(result);
      setSamples(result.samples);
      invalidateValidation();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "FASTQ discovery failed");
    } finally {
      setBusy("");
    }
  };

  const buildManifest = (): ProjectManifest => {
    const referenceResources: Record<string, string> = {};
    if (options.transcriptomeFasta.trim()) referenceResources.transcriptome_fasta = options.transcriptomeFasta;
    if (options.annotationGtf.trim()) referenceResources.annotation_gtf = options.annotationGtf;
    if (options.biomart.trim()) referenceResources.biomart = options.biomart;

    return {
      schema_version: "1.0.0",
      project_name: details.projectName,
      project_identifier: projectId,
      created_at: createdAt,
      input_directory: details.inputDirectory,
      output_directory: details.outputDirectory,
      pipeline_identifier: "bulk-rnaseq",
      pipeline_version: "0.3.0-full-demo",
      organism: options.organism,
      reference_genome: options.referenceGenome,
      annotation_source: options.annotationSource,
      reference_resources: referenceResources,
      library_type: options.libraryType,
      read_layout: options.readLayout,
      strandedness: options.strandedness,
      samples: samples.map((sample) => ({
        sample_id: sample.sample_id,
        r1_files: sample.r1_files,
        r2_files: options.readLayout === "single-end" ? [] : sample.r2_files,
        condition: sample.condition,
        biological_replicate: sample.biological_replicate,
        batch: sample.batch,
        covariates: {},
        included: sample.included,
      })),
      comparisons,
      parameters: { minimum_read_length: options.minimumReadLength },
      resource_profile: { cpus: options.cpus, memory_gb: options.memoryGb, max_parallel_tasks: 1 },
      execution_profile: options.executionProfile,
      application_version: "0.3.0",
      pipeline_status: "draft",
    };
  };

  const validate = async () => {
    setBusy("validate");
    setError("");
    try {
      const result = await apiRequest<ProjectValidation>("/api/v1/projects/validate", {
        method: "POST",
        body: JSON.stringify(buildManifest()),
      });
      setValidation(result);
      setValidatedManifest(result.valid ? result.manifest : null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Project validation failed");
    } finally {
      setBusy("");
    }
  };

  const saveAndPlan = async () => {
    if (!validatedManifest) return;
    setBusy("save");
    setError("");
    try {
      const saved = await apiRequest<{ manifest_path: string }>("/api/v1/projects/save", {
        method: "POST",
        body: JSON.stringify(validatedManifest),
      });
      const plan = await apiRequest<RunPlan>("/api/v1/runs/plan", {
        method: "POST",
        body: JSON.stringify({ manifest: validatedManifest }),
      });
      setSavedPath(saved.manifest_path);
      onProjectReady({ ...validatedManifest, pipeline_status: "planned" }, plan);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Project save failed");
    } finally {
      setBusy("");
    }
  };

  const addComparison = () => {
    if (!numerator || !denominator || numerator === denominator) {
      setError("Choose two different groups for the comparison.");
      return;
    }
    const comparisonId = toSafeId(`${numerator}_vs_${denominator}`);
    if (comparisons.some((comparison) => comparison.comparison_id === comparisonId)) {
      setError("That comparison has already been added.");
      return;
    }
    setComparisons((current) => [
      ...current,
      {
        comparison_id: comparisonId,
        numerator,
        denominator,
        label: `${numerator} (test) vs ${denominator} (reference)`,
      },
    ]);
    setError("");
    invalidateValidation();
  };

  const removeComparison = (comparisonId: string) => {
    setComparisons((current) =>
      current.filter((comparison) => comparison.comparison_id !== comparisonId),
    );
    invalidateValidation();
  };

  const renderStep = () => {
    switch (step) {
      case 0:
        return (
          <section className="wizard-card form-stack">
            <div className="section-heading"><div><p className="eyebrow">Step 1</p><h2>Project details</h2></div></div>
            <p className="helper-copy">Folder contents are read only after you select a folder or request a preview. FASTQs remain in place.</p>
            <label>Project name <span aria-hidden="true">*</span><input value={details.projectName} onChange={(event) => updateDetails("projectName", event.target.value)} placeholder="e.g. Mouse intervention pilot" /></label>
            <div className="directory-field">
              <label>Input FASTQ directory <span aria-hidden="true">*</span><input value={details.inputDirectory} onChange={(event) => updateDetails("inputDirectory", event.target.value)} placeholder="/data/sequencing/run-01" /></label>
              <div className="directory-actions"><button className="button secondary" type="button" onClick={() => void chooseFolder("input")} disabled={busy.startsWith("input-")}>Select input folder</button><button className="text-button" type="button" onClick={() => void loadFolderPreview("input", details.inputDirectory)} disabled={!details.inputDirectory || busy === "input-preview"}>Preview typed path</button></div>
            </div>
            {inputPreview && <FolderPreview label="Input folder" preview={inputPreview} />}
            <div className="directory-field">
              <label>Project output directory <span aria-hidden="true">*</span><input value={details.outputDirectory} onChange={(event) => updateDetails("outputDirectory", event.target.value)} placeholder="/data/projects/mouse-intervention-pilot" /></label>
              <div className="directory-actions"><button className="button secondary" type="button" onClick={() => void chooseFolder("output")} disabled={busy.startsWith("output-")}>Select output folder</button><button className="text-button" type="button" onClick={() => void loadFolderPreview("output", details.outputDirectory)} disabled={!details.outputDirectory || busy === "output-preview"}>Preview typed path</button></div>
            </div>
            {outputPreview && <FolderPreview label="Output folder" preview={outputPreview} />}
            <div className="safety-note"><strong>Files created</strong><span>Manifest, configuration directories, and empty result directories only.</span></div>
          </section>
        );
      case 1:
        return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 2</p><h2>Discover FASTQ files</h2></div><button className="button primary" type="button" onClick={discover} disabled={busy === "discover" || !details.inputDirectory}>{busy === "discover" ? "Scanning…" : "Scan directory"}</button></div>
            <p className="helper-copy">The scanner reads names and file metadata only. Symlinked directories are skipped.</p>
            {discovery ? (
              <>
                <div className="summary-grid three"><article className="metric-card"><span>FASTQs</span><strong>{discovery.total_files}</strong></article><article className="metric-card"><span>Proposed samples</span><strong>{discovery.samples.length}</strong></article><article className="metric-card"><span>Total size</span><strong>{formatBytes(discovery.total_bytes)}</strong></article></div>
                {discovery.warnings.length > 0 && <div className="warning-list"><strong>Discovery notes</strong><ul>{discovery.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></div>}
                <div className="file-preview"><h3>Detected files</h3>{discovery.files.slice(0, 12).map((file) => <div key={file.path}><span className={`read-chip read-${file.read.toLowerCase()}`}>{file.read}</span><code>{file.path}</code><small>{formatBytes(file.size_bytes)}</small></div>)}{discovery.files.length > 12 && <p>+ {discovery.files.length - 12} more files</p>}</div>
              </>
            ) : <div className="empty-state compact"><div className="empty-orbit" aria-hidden="true">⌁</div><h3>No scan results</h3><p>Enter an input directory in step 1.</p></div>}
          </section>
        );
      case 2:
        return (
          <section className="wizard-card wide-card">
            <div className="section-heading"><div><p className="eyebrow">Step 3</p><h2>Review samples and read pairs</h2></div><span className="count-pill">{samples.length}</span></div>
            <p className="helper-copy">Review all assignments. Resolve pairing warnings before validation.</p>
            {samples.length === 0 ? <p className="empty-copy">No sample proposals. Return to FASTQ discovery first.</p> : (
              <div className="table-scroll"><table className="sample-table"><thead><tr><th>Use</th><th>Sample identifier</th><th>R1 files</th><th>R2 files</th><th>Condition</th><th>Replicate</th><th>Batch</th><th>Status</th></tr></thead><tbody>{samples.map((sample, index) => <tr key={`${sample.sample_id}-${index}`}><td><input type="checkbox" checked={sample.included} onChange={(event) => updateSample(index, "included", event.target.checked)} aria-label={`Include ${sample.sample_id}`} /></td><td><input value={sample.sample_id} onChange={(event) => updateSample(index, "sample_id", event.target.value)} aria-label={`Sample identifier row ${index + 1}`} /></td><td><textarea rows={2} value={sample.r1_files.join("\n")} onChange={(event) => updateSample(index, "r1_files", event.target.value.split("\n").map((value) => value.trim()).filter(Boolean))} aria-label={`R1 files for ${sample.sample_id}`} /></td><td><textarea rows={2} value={sample.r2_files.join("\n")} onChange={(event) => updateSample(index, "r2_files", event.target.value.split("\n").map((value) => value.trim()).filter(Boolean))} aria-label={`R2 files for ${sample.sample_id}`} /></td><td><input value={sample.condition} onChange={(event) => updateSample(index, "condition", event.target.value)} aria-label={`Condition for ${sample.sample_id}`} /></td><td><input value={sample.biological_replicate} onChange={(event) => updateSample(index, "biological_replicate", event.target.value)} aria-label={`Replicate for ${sample.sample_id}`} /></td><td><input value={sample.batch ?? ""} onChange={(event) => updateSample(index, "batch", event.target.value || null)} aria-label={`Batch for ${sample.sample_id}`} /></td><td><span className={`pair-status pair-${sample.pairing_status}`}>{sample.pairing_status}</span>{sample.warnings.map((warning) => <small className="cell-warning" key={warning}>{warning}</small>)}</td></tr>)}</tbody></table></div>
            )}
          </section>
        );
      case 3:
        return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 4</p><h2>Confirm experimental design</h2></div></div>
            <p className="helper-copy">Confirm condition, replicate, and batch values. Filenames are not used to infer them.</p>
            {samples.filter((sample) => sample.included).map((sample, index) => {
              const realIndex = samples.indexOf(sample);
              return <article className="design-row" key={`${sample.sample_id}-${index}`}><strong>{sample.sample_id}</strong><label>Condition<input value={sample.condition} onChange={(event) => updateSample(realIndex, "condition", event.target.value)} /></label><label>Biological replicate<input value={sample.biological_replicate} onChange={(event) => updateSample(realIndex, "biological_replicate", event.target.value)} /></label><label>Batch<input value={sample.batch ?? ""} onChange={(event) => updateSample(realIndex, "batch", event.target.value || null)} /></label></article>;
            })}
            {groups.length > 0 && <div className="group-summary"><strong>Current groups</strong>{groups.map((group) => <span key={group}>{group}: {samples.filter((sample) => sample.included && sample.condition === group).length} sample(s)</span>)}</div>}
          </section>
        );
      case 4:
        return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 5</p><h2>Build comparisons</h2></div></div>
            <p className="helper-copy">Contrast: numerator minus denominator. Positive fold change indicates higher expression in the numerator.</p>
            {groups.length < 2 ? <div className="warning-list">Assign at least two conditions in the experimental design step.</div> : <div className="comparison-builder"><label>Numerator / test group<select value={numerator} onChange={(event) => setNumerator(event.target.value)}><option value="">Choose group</option>{groups.map((group) => <option key={group}>{group}</option>)}</select></label><span className="direction-mark" aria-hidden="true">versus</span><label>Denominator / reference group<select value={denominator} onChange={(event) => setDenominator(event.target.value)}><option value="">Choose group</option>{groups.map((group) => <option key={group}>{group}</option>)}</select></label><button className="button primary" type="button" onClick={addComparison}>Add comparison</button></div>}
            <div className="comparison-list">{comparisons.length === 0 ? <p className="empty-copy">No comparisons requested.</p> : comparisons.map((comparison) => <article key={comparison.comparison_id}><div><strong>{comparison.numerator} <span>−</span> {comparison.denominator}</strong><p>{comparison.label}</p></div><button type="button" className="text-button danger" onClick={() => removeComparison(comparison.comparison_id)}>Remove</button></article>)}</div>
          </section>
        );
      case 5:
        return (
          <section className="wizard-card form-stack">
            <div className="section-heading"><div><p className="eyebrow">Step 6</p><h2>Pipeline options</h2></div></div>
            <div className="field-pair"><label>Organism<input value={options.organism} onChange={(event) => updateOptions("organism", event.target.value)} /></label><label>Reference genome<input value={options.referenceGenome} onChange={(event) => updateOptions("referenceGenome", event.target.value)} /></label></div>
            <div className="field-pair"><label>Annotation source<input value={options.annotationSource} onChange={(event) => updateOptions("annotationSource", event.target.value)} /></label><label>Library type<select value={options.libraryType} onChange={(event) => updateOptions("libraryType", event.target.value)}><option>total RNA</option><option>lncRNA</option><option>mRNA</option><option>other (confirm)</option></select></label></div>
            <div className="field-pair"><label>Read layout<select value={options.readLayout} onChange={(event) => updateOptions("readLayout", event.target.value as OptionsState["readLayout"])}><option value="paired-end">Paired-end</option><option value="single-end">Single-end</option></select></label><label>Strandedness<select value={options.strandedness} onChange={(event) => updateOptions("strandedness", event.target.value as OptionsState["strandedness"])}><option value="unknown">Unknown (confirm)</option><option value="reverse">Reverse / RF</option><option value="forward">Forward / FR</option><option value="unstranded">Unstranded</option></select></label></div>
            <fieldset><legend>Reference resource paths</legend><p className="helper-copy">Optional for framework validation; required before real execution can be enabled.</p><label>Transcriptome FASTA<input value={options.transcriptomeFasta} onChange={(event) => updateOptions("transcriptomeFasta", event.target.value)} placeholder="/references/transcripts.fa" /></label><label>Annotation GTF<input value={options.annotationGtf} onChange={(event) => updateOptions("annotationGtf", event.target.value)} placeholder="/references/annotation.gtf" /></label><label>BioMart table<input value={options.biomart} onChange={(event) => updateOptions("biomart", event.target.value)} placeholder="/references/biomart.tsv" /></label></fieldset>
            <div className="field-triple"><label>Profile<select value={options.executionProfile} onChange={(event) => updateOptions("executionProfile", event.target.value as OptionsState["executionProfile"])}><option value="local">Local</option><option value="docker">Docker</option><option value="apptainer">Apptainer</option></select></label><label>CPUs<input type="number" min="1" value={options.cpus} onChange={(event) => updateOptions("cpus", Number(event.target.value))} /></label><label>Memory (GiB)<input type="number" min="1" value={options.memoryGb} onChange={(event) => updateOptions("memoryGb", Number(event.target.value))} /></label></div>
          </section>
        );
      case 6:
        return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 7</p><h2>Preflight validation</h2></div><button className="button primary" type="button" onClick={validate} disabled={busy === "validate"}>{busy === "validate" ? "Validating…" : "Run project checks"}</button></div>
            <p className="helper-copy">Blocking failures prevent saving. Warnings do not.</p>
            {validation && <div className={validation.valid ? "validation-summary valid" : "validation-summary invalid"}><strong>{validation.valid ? "Manifest valid" : "Validation failed"}</strong><span>{validation.checks.filter((check) => check.status === "blocking_failure").length} blocking · {validation.checks.filter((check) => check.status === "warning").length} warning</span></div>}
            <CheckList checks={validation?.checks ?? []} />
          </section>
        );
      default:
        return (
          <section className="wizard-card">
            <div className="section-heading"><div><p className="eyebrow">Step 8</p><h2>Review and save</h2></div></div>
            <div className="review-grid"><dl><dt>Project</dt><dd>{details.projectName || "—"}</dd><dt>Input</dt><dd>{details.inputDirectory || "—"}</dd><dt>Output</dt><dd>{details.outputDirectory || "—"}</dd><dt>Organism</dt><dd>{options.organism}</dd><dt>Reference</dt><dd>{options.referenceGenome} · {options.annotationSource}</dd></dl><dl><dt>Included samples</dt><dd>{samples.filter((sample) => sample.included).length}</dd><dt>Comparisons</dt><dd>{comparisons.length}</dd><dt>Library</dt><dd>{options.libraryType} · {options.readLayout} · {options.strandedness}</dd><dt>Resources</dt><dd>{options.cpus} CPUs · {options.memoryGb} GiB</dd><dt>Execution</dt><dd>{options.executionProfile} preview only</dd></dl></div>
            {!validation?.valid && <div className="warning-list"><strong>Validation required</strong><p>Return to preflight and resolve blocking failures before saving.</p></div>}
            {savedPath && <div className="success-message" role="status">Saved manifest: <code>{savedPath}</code></div>}
            <div className="save-panel"><div><strong>Save manifest</strong><p>FASTQ files are not copied. A command preview is generated.</p></div><button className="button primary large" type="button" disabled={!validatedManifest || busy === "save"} onClick={saveAndPlan}>{busy === "save" ? "Saving…" : "Save manifest & build run plan"}</button></div>
          </section>
        );
    }
  };

  return (
    <div className="page-stack wizard-page">
      <header className="page-header">
        <div><p className="eyebrow">New bulk RNA-seq project</p><h1>{details.projectName || "Untitled project"}</h1><p className="lede">Step {step + 1} of {steps.length} · {steps[step]}</p></div>
        <span className="draft-chip">Unsaved</span>
      </header>

      <div className="wizard-layout">
        <ol className="wizard-steps" aria-label="Project setup steps">
          {steps.map((label, index) => (
            <li key={label} className={index === step ? "current" : index < step ? "complete" : ""}>
              <button type="button" onClick={() => setStep(index)} aria-current={index === step ? "step" : undefined}>
                <span>{index < step ? "✓" : index + 1}</span><strong>{label}</strong>
              </button>
            </li>
          ))}
        </ol>
        <div>
          {error && <div className="inline-error" role="alert"><strong>Error</strong><span>{error}</span><button type="button" aria-label="Dismiss error" onClick={() => setError("")}>×</button></div>}
          {renderStep()}
          <div className="wizard-actions"><button className="button secondary" type="button" onClick={() => setStep((current) => Math.max(0, current - 1))} disabled={step === 0}>Back</button><span>Unsaved changes are temporary.</span><button className="button primary" type="button" onClick={() => setStep((current) => Math.min(steps.length - 1, current + 1))} disabled={step === steps.length - 1}>Continue</button></div>
        </div>
      </div>
    </div>
  );
}
