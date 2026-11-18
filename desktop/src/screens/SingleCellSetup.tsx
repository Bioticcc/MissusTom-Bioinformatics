import { useState } from "react";
import { saveTextFile, selectFiles } from "../native";
import {
  newSingleCellLibrary, nextSingleCellLibraryId, singleCellChemistries,
  type SingleCellFastqManifest, type SingleCellLibrary,
} from "../singleCellSetup";

export function SingleCellSetup({ draft, onChange, onBack }: {
  draft: SingleCellFastqManifest;
  onChange: (draft: SingleCellFastqManifest) => void;
  onBack: () => void;
}) {
  const [error, setError] = useState("");
  const [savedPath, setSavedPath] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);
  const change = (value: SingleCellFastqManifest) => {
    setSavedPath(null);
    onChange(value);
  };
  const reference = (value: Partial<SingleCellFastqManifest["reference"]>) =>
    change({ ...draft, reference: { ...draft.reference, ...value } });
  const analysis = (value: Partial<SingleCellFastqManifest["analysis"]>) =>
    change({ ...draft, analysis: { ...draft.analysis, ...value } });
  const library = (index: number, value: Partial<SingleCellLibrary>) =>
    change({ ...draft, samples: draft.samples.map((sample, i) => i === index ? { ...sample, ...value } : sample) });
  const lane = (index: number, laneIndex: number, mate: "r1" | "r2", path: string) =>
    library(index, { lanes: draft.samples[index].lanes.map((value, i) => i === laneIndex ? { ...value, [mate]: path } : value) });
  const choose = async (label: string, apply: (path: string) => void) => {
    setError("");
    setPicking(true);
    try {
      const paths = await selectFiles(label, false);
      if (paths?.[0]) apply(paths[0]);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "File selection failed.");
    } finally { setPicking(false); }
  };
  const exportDraft = async () => {
    setError("");
    setSaving(true);
    try {
      const path = await saveTextFile("Save SingleCell FASTQ configuration", "singlecell-fastq-manifest.json",
        `${JSON.stringify(draft, null, 2)}\n`, "settings");
      if (path) setSavedPath(path);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Configuration export failed.");
    } finally { setSaving(false); }
  };
  const pathField = (label: string, value: string, apply: (path: string) => void) =>
    <div className="directory-field"><label>{label}<input value={value} onChange={(event) => apply(event.target.value)} placeholder="Absolute local file path" disabled={picking}/></label><div className="directory-actions"><button className="button secondary" type="button" disabled={picking} onClick={() => void choose(label, apply)}>Browse</button></div></div>;

  return <div className="page-stack wizard-page">
    <header className="page-header"><div><p className="eyebrow">New pipeline configuration</p><h1>SingleCell RNA-seq</h1><p className="lede">FASTQs → cell counts → QC, clustering, UMAP and exploratory markers.</p></div><button className="button secondary" type="button" onClick={onBack} disabled={saving || picking}>Back to pipeline selection</button></header>
    <div className="warning-list" role="status"><strong>In development — configuration and export only</strong><p>SingleCell installation and running from the app are not available yet. The STARsolo and Seurat workflow still needs scientific validation. Exporting here saves a standalone configuration, not a runnable project in the app.</p></div>
    {error && <div className="inline-error" role="alert">{error}</div>}
    <section className="wizard-card form-stack">
      <h2>Reference</h2>
      <div className="field-pair"><label>Species<input value={draft.reference.species} onChange={(event) => reference({ species: event.target.value })} placeholder="Species used by your reference"/></label><label>Genome build and annotation release<input value={draft.reference.genome_build} onChange={(event) => reference({ genome_build: event.target.value })} placeholder="Build and matching annotation release"/></label></div>
      {pathField("Genome FASTA (uncompressed)", draft.reference.fasta, (fasta) => reference({ fasta }))}
      {pathField("Annotation GTF (uncompressed)", draft.reference.gtf, (gtf) => reference({ gtf }))}
      <label>Mitochondrial gene IDs<input value={draft.reference.mitochondrial_gene_ids.join(", ")} onChange={(event) => reference({ mitochondrial_gene_ids: event.target.value.split(",").map((value) => value.trim()) })} placeholder="Comma-separated gene IDs from this reference"/></label>
      <p className="field-help">Use reference gene IDs, not assumed human or mouse gene-name prefixes.</p>
      <details><summary>Reference index settings</summary><div className="field-pair"><label>Splice-junction overhang<input type="number" min={1} max={1000} value={draft.reference.sjdb_overhang} onChange={(event) => reference({ sjdb_overhang: Number(event.target.value) })}/></label><label>STAR suffix-index bases<input type="number" min={1} max={14} value={draft.reference.sa_index_n_bases} onChange={(event) => reference({ sa_index_n_bases: Number(event.target.value) })}/></label></div><p className="field-help">Overhang is the maximum intended cDNA read length minus one. Fourteen suffix-index bases is typical for mammalian genomes; small genomes need less. The runner checks this before indexing.</p></details>
    </section>
    <section className="wizard-card form-stack">
      <h2>Libraries and FASTQ files</h2>
      <p className="helper-copy">One library per capture. Add sequencing lanes from the same library together. Donors, conditions and batches are always explicit.</p>
      {draft.samples.map((sample, index) => <fieldset className="form-stack" key={index}>
        <legend>Library {index + 1}</legend>
        <div className="field-pair"><label>Sample ID<input value={sample.sample_id} onChange={(event) => library(index, { sample_id: event.target.value })}/></label><label>Donor ID<input value={sample.donor_id} onChange={(event) => library(index, { donor_id: event.target.value })}/></label></div>
        <div className="field-pair"><label>Condition<input value={sample.condition} onChange={(event) => library(index, { condition: event.target.value })}/></label><label>Technical batch<input value={sample.batch} onChange={(event) => library(index, { batch: event.target.value })}/></label></div>
        <label>Library chemistry<select value={sample.chemistry} onChange={(event) => library(index, { chemistry: event.target.value })}>{singleCellChemistries.map((chemistry) => <option key={chemistry.id} value={chemistry.id} disabled={!chemistry.execution_supported && chemistry.id !== "unknown"}>{chemistry.label}{!chemistry.execution_supported && chemistry.id !== "unknown" ? " — not available yet" : ""}</option>)}</select></label>
        <p className="field-help">{singleCellChemistries.find((chemistry) => chemistry.id === sample.chemistry)?.description}</p>
        <div className="field-pair"><label>Material<select value={sample.material} onChange={(event) => library(index, { material: event.target.value })}><option value="unknown">Not sure yet</option><option value="cells">Whole cells</option><option value="nuclei">Nuclei</option></select></label><label>Counting mode<select value={sample.counting_mode} onChange={(event) => library(index, { counting_mode: event.target.value })}><option value="unknown">Choose counting mode</option><option value="Gene">Exons only (Gene)</option><option value="GeneFull">Exons and introns (GeneFull)</option></select></label></div>
        <p className="field-help">Confirm the chemistry with your sequencing provider. “Not sure yet” can be saved in a draft but blocks execution. Cells versus nuclei does not automatically choose a counting mode. All libraries must use the same mode.</p>
        {pathField("Chemistry-matched barcode whitelist", sample.barcode_whitelist, (barcode_whitelist) => library(index, { barcode_whitelist }))}
        <p className="field-help">Local uncompressed text, one barcode per line. The whitelist must match the selected kit.</p>
        {sample.lanes.map((files, laneIndex) => <fieldset className="form-stack" key={laneIndex}><legend>Lane {laneIndex + 1}</legend>
          {pathField("R1 FASTQ (barcode and UMI, gzip)", files.r1, (path) => lane(index, laneIndex, "r1", path))}
          {pathField("R2 FASTQ (cDNA, gzip)", files.r2, (path) => lane(index, laneIndex, "r2", path))}
          {sample.lanes.length > 1 && <button className="button secondary" type="button" disabled={picking} onClick={() => library(index, { lanes: sample.lanes.filter((_, i) => i !== laneIndex) })}>Remove lane {laneIndex + 1}</button>}
        </fieldset>)}
        <button className="button secondary" type="button" disabled={picking} onClick={() => library(index, { lanes: [...sample.lanes, { r1: "", r2: "" }] })}>Add sequencing lane</button>
        <details><summary>Cell calling and QC</summary><p className="field-help">These numbers are editable examples. Review them for your tissue and experiment. Mitochondrial cutoffs are percentages, from 0 to 100.</p>
          <label>Expected cells<input type="number" min={1} max={1000000} value={sample.expected_cells} onChange={(event) => library(index, { expected_cells: Number(event.target.value) })}/></label>
          <div className="field-pair"><label>Minimum counts<input type="number" min={1} value={sample.qc.min_counts} onChange={(event) => library(index, { qc: { ...sample.qc, min_counts: Number(event.target.value) } })}/></label><label>Minimum genes<input type="number" min={1} value={sample.qc.min_features} onChange={(event) => library(index, { qc: { ...sample.qc, min_features: Number(event.target.value) } })}/></label></div>
          <div className="field-pair"><label>Maximum genes<input type="number" min={1} value={sample.qc.max_features} onChange={(event) => library(index, { qc: { ...sample.qc, max_features: Number(event.target.value) } })}/></label><label>Maximum mitochondrial percent<input type="number" min={0} max={100} value={sample.qc.max_mito_percent} onChange={(event) => library(index, { qc: { ...sample.qc, max_mito_percent: Number(event.target.value) } })}/></label></div>
        </details>
        {draft.samples.length > 1 && <button className="button secondary" type="button" disabled={picking} onClick={() => change({ ...draft, samples: draft.samples.filter((_, i) => i !== index) })}>Remove library {index + 1}</button>}
      </fieldset>)}
      <button className="button secondary" type="button" disabled={picking} onClick={() => change({ ...draft, samples: [...draft.samples, newSingleCellLibrary(nextSingleCellLibraryId(draft.samples))] })}>Add library</button>
    </section>
    <section className="wizard-card form-stack">
      <h2>Analysis</h2><p className="helper-copy">Log normalization, PCA, clustering and UMAP. Batch integration is off. Cluster markers are exploratory; they do not test treatment effects between donors.</p>
      <div className="field-pair"><label>Variable genes<input type="number" min={20} max={10000} value={draft.analysis.variable_features} onChange={(event) => analysis({ variable_features: Number(event.target.value) })}/></label><label>Principal components<input type="number" min={2} max={100} value={draft.analysis.pcs} onChange={(event) => analysis({ pcs: Number(event.target.value) })}/></label></div>
      <div className="field-pair"><label>Clustering resolution<input type="number" min={0.01} max={5} step={0.01} value={draft.analysis.resolution} onChange={(event) => analysis({ resolution: Number(event.target.value) })}/></label><label>Random seed<input type="number" min={1} max={2147483647} value={draft.analysis.seed} onChange={(event) => analysis({ seed: Number(event.target.value) })}/></label></div>
      <label><input type="checkbox" checked={draft.analysis.cluster_markers} onChange={(event) => analysis({ cluster_markers: event.target.checked })}/> Find exploratory cluster markers</label>
    </section>
    <section className="wizard-card form-stack"><h2>Save configuration</h2><p>Drafts may be incomplete. Export does not validate files or start an analysis. The standalone runner checks the saved configuration before execution.</p><button className="button primary" type="button" disabled={saving || picking} onClick={() => void exportDraft()}>{saving ? "Exporting…" : "Export SingleCell configuration"}</button>{savedPath && <div className="success-message" role="status">Configuration saved to <code>{savedPath}</code>. No analysis has started.</div>}</section>
  </div>;
}
