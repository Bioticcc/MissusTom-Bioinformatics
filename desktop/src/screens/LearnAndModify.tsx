import { useEffect, useMemo, useState } from "react";
import { apiRequest } from "../api";
import { SourceEditor } from "../components/SourceEditor";
import type { PipelineDifference, PipelineRevision, PipelineSourceContent, PipelineSourceStatus } from "../types";

const ACKNOWLEDGEMENT = "I Understand";

export function LearnAndModify({ isRunActive }: { isRunActive: boolean }) {
  const [sources, setSources] = useState<PipelineSourceStatus[]>([]);
  const [pipeline, setPipeline] = useState("bulk-rnaseq");
  const [selectedPath, setSelectedPath] = useState<string>();
  const [file, setFile] = useState<PipelineSourceContent>();
  const [draft, setDraft] = useState("");
  const [editing, setEditing] = useState(false);
  const [acknowledging, setAcknowledging] = useState(false);
  const [ack, setAck] = useState("");
  const [difference, setDifference] = useState<string>();
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const source = sources.find((entry) => entry.pipeline_identifier === pipeline);
  const dirty = editing && file !== undefined && draft !== file.content;

  const selectPipeline = (nextPipeline: string) => {
    if (!dirty || window.confirm("Discard unsaved script changes?")) setPipeline(nextPipeline);
  };

  const reload = async () => {
    const result = await apiRequest<PipelineSourceStatus[]>("/api/v1/pipeline-sources");
    setSources(result);
    return result;
  };
  useEffect(() => { void reload().catch((reason) => setMessage(reason instanceof Error ? reason.message : "Pipeline sources could not be loaded.")); }, []);
  useEffect(() => { setSelectedPath(undefined); setFile(undefined); setEditing(false); setDifference(undefined); }, [pipeline]);
  const choose = async (path: string) => {
    if (dirty && !window.confirm("You have unsaved script changes. Discard them?")) return;
    try {
      const content = await apiRequest<PipelineSourceContent>(`/api/v1/pipeline-sources/${pipeline}/files/${path}`);
      setSelectedPath(path); setFile(content); setDraft(content.content); setEditing(false); setDifference(undefined); setMessage("");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "The source file could not be loaded."); }
  };
  const save = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const revision = await apiRequest<PipelineRevision>(`/api/v1/pipeline-sources/${pipeline}/revisions`, { method: "POST", body: JSON.stringify({ path: file.path, content: draft, expected_revision_id: source?.active_revision_id ?? null }) });
      await apiRequest<PipelineSourceStatus>(`/api/v1/pipeline-sources/${pipeline}/revisions/${revision.revision_id}/activate`, { method: "POST" });
      await reload();
      const saved = await apiRequest<PipelineSourceContent>(`/api/v1/pipeline-sources/${pipeline}/files/${file.path}`);
      setFile(saved); setDraft(saved.content); setEditing(false); setMessage("Saved as a new custom revision and activated for future runs.");
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Changes could not be saved."); } finally { setBusy(false); }
  };
  const restore = async () => {
    if (!window.confirm("Restore the official pipeline for future runs? Saved custom revisions will be kept.")) return;
    try { await apiRequest<PipelineSourceStatus>(`/api/v1/pipeline-sources/${pipeline}/restore`, { method: "POST" }); await reload(); if (selectedPath) await choose(selectedPath); setMessage("Official pipeline restored for future runs."); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "The original pipeline could not be restored."); }
  };
  const showDifference = async () => { if (!file) return; try { const result = await apiRequest<PipelineDifference>(`/api/v1/pipeline-sources/${pipeline}/differences/${file.path}`); setDifference(result.diff || "No differences from the official source."); } catch (reason) { setMessage(reason instanceof Error ? reason.message : "Differences could not be loaded."); } };
  const files = useMemo(() => source?.files ?? [], [source]);
  return <div className="page-stack learn-page">
    <header className="page-header"><div><p className="eyebrow">Pipeline source</p><h1>Learn and Modify</h1><p className="lede"><strong className="learn-development-notice">Dev here! Files are currently not formatted for ease of readability for non developers, as this was sort of a recent idea to include to the software. If you are downloading the software for use and this warning is still here, that means we have NOT reformatted/restructured our scripts with this learning in mind. If you want to still use this feature, go ahead, its functional! Just hard to read :)</strong>Explore the code behind your scientific pipelines and learn how your data are processed. Select a pipeline to view its files. Experienced users can create a custom version, while the official pipeline always remains available.</p></div></header>
    <fieldset className="run-mode-panel setup-mode-panel learn-pipeline-selector">
      <legend>Pipeline</legend>
      <label className={`run-mode-option${pipeline === "bulk-rnaseq" ? " selected" : ""}`}><input type="radio" name="learn-pipeline" checked={pipeline === "bulk-rnaseq"} onChange={() => selectPipeline("bulk-rnaseq")} /><span><strong>Bulk RNA-seq (paired-end) {sources.find((item) => item.pipeline_identifier === "bulk-rnaseq")?.source_type === "custom" && <span className="modified-pipeline-badge"><span aria-hidden="true">!</span> Modified by user</span>}</strong><small>Explore the Nextflow workflow, resource settings, and R analysis that create counts, comparisons, tables, and figures.</small></span></label>
      <label className={`run-mode-option${pipeline === "ont-analysis" ? " selected" : ""}`}><input type="radio" name="learn-pipeline" checked={pipeline === "ont-analysis"} onChange={() => selectPipeline("ont-analysis")} /><span><strong>ONT (Oxford Nanopore) Analysis (mouse) {sources.find((item) => item.pipeline_identifier === "ont-analysis")?.source_type === "custom" && <span className="modified-pipeline-badge"><span aria-hidden="true">!</span> Modified by user</span>}</strong><small>Explore the main runner, five processing stages, and their Python, R, and shell helpers.</small></span></label>
      <p className={source?.source_type === "custom" ? "custom-status run-mode-note modified-pipeline-warning" : "run-mode-note"}>{source?.source_type === "custom" ? `Modified pipeline active (${source.active_revision_id}). All new and existing projects using ${source.display_name} will use this modified version for their next run. The official installed version remains available for restoration.` : source?.source_type === "custom-unavailable" ? "Custom pipeline active but unavailable. Restore the official pipeline before running." : "Original pipeline active. The installed version remains unchanged."}</p>
    </fieldset>
    <section className="panel learn-workspace">
      <aside className="source-explorer"><h2>{source?.display_name ?? "Pipeline files"}</h2>{files.map((item) => <button type="button" key={item.path} className={selectedPath === item.path ? "source-file selected" : "source-file"} onClick={() => void choose(item.path)}><span aria-hidden="true">⌑</span>{item.path}</button>)}</aside>
      <div className="source-viewer">{file ? <><div className="source-toolbar"><div><strong>{file.path}</strong><span>{editing ? "Editing Custom Script" : "Read-only source"}</span></div><div className="button-row">{!editing && <button className="button secondary" type="button" onClick={() => setAcknowledging(true)}>Modify Script</button>}{source?.source_type === "custom" && !editing && <button className="button secondary" type="button" onClick={() => void showDifference()}>View Differences</button>}{source?.source_type === "custom" && <button className="button secondary" type="button" disabled={isRunActive} onClick={() => void restore()}>Restore Original Pipeline</button>}</div></div><SourceEditor path={file.path} value={editing ? draft : file.content} editable={editing} onChange={setDraft} />{editing && <div className="button-row"><button className="button" type="button" disabled={!dirty || busy} onClick={() => void save()}>Save Changes</button><button className="button secondary" type="button" onClick={() => { setDraft(file.content); setEditing(false); }}>Cancel</button>{dirty && <span className="dirty-indicator">Unsaved changes</span>}</div>}{difference !== undefined && <pre className="source-difference">{difference}</pre>}</> : <p className="field-help">Select a source file to view its complete contents.</p>}</div>
    </section>
    {message && <p className="settings-message" role="status">{message}</p>}
    {acknowledging && <div className="modal-backdrop" role="presentation"><section className="panel warning-dialog modify-warning-dialog" role="dialog" aria-modal="true" aria-labelledby="modify-warning-title"><h2 id="modify-warning-title">Experimental custom code</h2><div className="modification-risk-summary"><p><strong>Pipeline failure:</strong> Modified code can prevent a run from starting, make scientific calculations fail, or remove expected outputs.</p><p><strong>Incorrect results:</strong> Code can run successfully while producing inaccurate or misleading scientific results.</p><p><strong>Permanent data loss:</strong> A shell command could delete files using your filesystem permissions. CPU and memory limits do not prevent file access.</p></div><p><strong>You are responsible</strong> for reviewing the safety of custom code and the scientific correctness of its results. Custom modifications are unsupported experimental behavior.</p><p className="acknowledgement-instruction">Please type "I Understand" in the box (without quotations) and click proceed.</p><input aria-label="Modification acknowledgement" value={ack} onChange={(event) => setAck(event.target.value)} autoFocus /><div className="button-row warning-actions"><button className="button primary" type="button" disabled={ack !== ACKNOWLEDGEMENT} onClick={() => { setAcknowledging(false); setAck(""); setEditing(true); }}>Proceed</button><button className="button secondary" type="button" onClick={() => { setAcknowledging(false); setAck(""); }}>Cancel</button></div></section></div>}
  </div>;
}
