import { useState } from "react";
import { saveTextFile, selectFiles } from "../native";
import type { SingleCellSeuratManifest } from "../singleCellSetup";

export function SingleCellSetup({ draft, onChange, onBack }: {
  draft: SingleCellSeuratManifest;
  onChange: (draft: SingleCellSeuratManifest) => void;
  onBack: () => void;
}) {
  const [error, setError] = useState("");
  const [savedPath, setSavedPath] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [picking, setPicking] = useState(false);
  const change = (value: SingleCellSeuratManifest) => {
    setSavedPath(null);
    onChange(value);
  };
  const input = (value: Partial<SingleCellSeuratManifest["input"]>) =>
    change({ ...draft, input: { ...draft.input, ...value } });
  const column = (value: Partial<SingleCellSeuratManifest["input"]["metadata_columns"]>) =>
    input({ metadata_columns: { ...draft.input.metadata_columns, ...value } });
  const reference = (value: Partial<SingleCellSeuratManifest["reference"]>) =>
    change({ ...draft, reference: { ...draft.reference, ...value } });
  const qc = (value: Partial<SingleCellSeuratManifest["qc"]>) =>
    change({ ...draft, qc: { ...draft.qc, ...value } });
  const analysis = (value: Partial<SingleCellSeuratManifest["analysis"]>) =>
    change({ ...draft, analysis: { ...draft.analysis, ...value } });
  const chooseObject = async () => {
    setError("");
    setPicking(true);
    try {
      const paths = await selectFiles("Select Seurat object (.rds)", false);
      if (paths?.[0]) input({ seurat_rds: paths[0] });
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "File selection failed.");
    } finally { setPicking(false); }
  };
  const exportDraft = async () => {
    setError("");
    setSaving(true);
    try {
      const path = await saveTextFile("Save SingleCell configuration", "singlecell-seurat-manifest.json",
        `${JSON.stringify(draft, null, 2)}\n`, "settings");
      if (path) setSavedPath(path);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Configuration export failed.");
    } finally { setSaving(false); }
  };

  return <div className="page-stack wizard-page">
    <header className="page-header"><div><p className="eyebrow">New pipeline configuration</p><h1>SingleCell RNA-seq</h1><p className="lede">Seurat object → QC, clustering, UMAP and exploratory markers.</p></div><button className="button secondary" type="button" onClick={onBack} disabled={saving || picking}>Back to pipeline selection</button></header>
    <div className="warning-list" role="status"><strong>In development — configuration and export only</strong><p>SingleCell installation and running from the app are not available yet. The Seurat workflow still needs scientific validation. Exporting here saves a standalone configuration, not a runnable project in the app.</p></div>
    {error && <div className="inline-error" role="alert">{error}</div>}
    <section className="wizard-card form-stack">
      <h2>Seurat object</h2>
      <p className="helper-copy">Choose one object saved with <code>saveRDS()</code>. Only open objects from sources you trust. Your file is never changed. The analysis starts again from its raw counts, so earlier normalization, reductions and clusters are not reused.</p>
      <div className="directory-field"><label>Seurat object (.rds)<input value={draft.input.seurat_rds} onChange={(event) => input({ seurat_rds: event.target.value })} placeholder="Absolute local file path" disabled={picking}/></label><div className="directory-actions"><button className="button secondary" type="button" disabled={picking} onClick={() => void chooseObject()}>Browse</button></div></div>
      <label>Assay with raw counts<input value={draft.input.assay} onChange={(event) => input({ assay: event.target.value })}/></label>
      <h3>Metadata columns</h3>
      <p className="field-help">Enter the column names from the object's cell metadata. Every cell needs a value in each column.</p>
      <div className="field-pair"><label>Sample column<input value={draft.input.metadata_columns.sample_id} onChange={(event) => column({ sample_id: event.target.value })}/></label><label>Donor column<input value={draft.input.metadata_columns.donor_id} onChange={(event) => column({ donor_id: event.target.value })}/></label></div>
      <div className="field-pair"><label>Condition column<input value={draft.input.metadata_columns.condition} onChange={(event) => column({ condition: event.target.value })}/></label><label>Technical batch column<input value={draft.input.metadata_columns.batch} onChange={(event) => column({ batch: event.target.value })}/></label></div>
    </section>
    <section className="wizard-card form-stack">
      <h2>Reference</h2>
      <div className="field-pair"><label>Species<input value={draft.reference.species} onChange={(event) => reference({ species: event.target.value })} placeholder="Species used by your reference"/></label><label>Genome build and annotation release<input value={draft.reference.genome_build} onChange={(event) => reference({ genome_build: event.target.value })} placeholder="Build and matching annotation release"/></label></div>
      <label>Mitochondrial feature IDs<input value={draft.reference.mitochondrial_gene_ids.join(", ")} onChange={(event) => reference({ mitochondrial_gene_ids: event.target.value.split(",").map((value) => value.trim()) })} placeholder="Comma-separated feature names from this object"/></label>
      <p className="field-help">Use the feature names exactly as they appear in the object. Human or mouse name prefixes are not assumed.</p>
    </section>
    <section className="wizard-card form-stack">
      <h2>Cell QC</h2>
      <p className="field-help">These numbers are editable examples. Review them for your tissue and experiment, especially if the object was already filtered. Mitochondrial cutoffs are percentages, from 0 to 100.</p>
      <div className="field-pair"><label>Minimum counts<input type="number" min={1} value={draft.qc.min_counts} onChange={(event) => qc({ min_counts: Number(event.target.value) })}/></label><label>Minimum genes<input type="number" min={1} value={draft.qc.min_features} onChange={(event) => qc({ min_features: Number(event.target.value) })}/></label></div>
      <div className="field-pair"><label>Maximum genes<input type="number" min={1} value={draft.qc.max_features} onChange={(event) => qc({ max_features: Number(event.target.value) })}/></label><label>Maximum mitochondrial percent<input type="number" min={0} max={100} value={draft.qc.max_mito_percent} onChange={(event) => qc({ max_mito_percent: Number(event.target.value) })}/></label></div>
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
