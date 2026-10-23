import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { getUninstallStatus, selectDirectory, type UninstallStatus } from "../native";
import { loadProjectDefaults, saveProjectDefaults } from "../preferences";
import type { PipelineSourceStatus } from "../types";

const UNINSTALL_ACKNOWLEDGEMENT = "UNINSTALL MISSUS TOM";

export function Settings({ onResetSetup, isRunActive }: { onResetSetup: () => void; isRunActive: boolean }) {
  const [defaults, setDefaults] = useState(loadProjectDefaults);
  const [message, setMessage] = useState("");
  const [uninstall, setUninstall] = useState<UninstallStatus>({ supported: false, message: "Checking installation type…" });
  const [showUninstall, setShowUninstall] = useState(false);
  const [uninstallAck, setUninstallAck] = useState("");
  const save = () => { saveProjectDefaults(defaults); setMessage("Defaults saved on this desktop. They apply to new projects."); };
  useEffect(() => { void getUninstallStatus().then(setUninstall).catch((reason) => setUninstall({ supported: false, message: reason instanceof Error ? reason.message : "The installation type could not be verified." })); }, []);
  const chooseProjectParent = async () => {
    try { const directory = await selectDirectory("Select default project parent folder"); if (directory) setDefaults((current) => ({ ...current, projectParentDirectory: directory })); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : "The project folder could not be selected."); }
  };
  const restorePipelines = async () => {
    if (!window.confirm("Restore official Bulk RNA-seq and ONT pipelines for future runs? Custom revisions will be kept.")) return;
    try { await Promise.all(["bulk-rnaseq", "ont-analysis"].map((pipeline) => apiRequest<PipelineSourceStatus>(`/api/v1/pipeline-sources/${pipeline}/restore`, { method: "POST" }))); setMessage("Official pipelines restored. Projects and results were not changed."); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : "The official pipelines could not be restored."); }
  };
  const proceed = async () => {
    if (!uninstall.command) return;
    try { await navigator.clipboard.writeText(uninstall.command); setMessage("The verified uninstall command was copied to the clipboard."); }
    catch { setMessage(`Run this verified command in a terminal: ${uninstall.command}`); }
  };
  return <div className="page-stack">
    <header className="page-header"><div><p className="eyebrow">Application configuration</p><h1>Settings</h1><p className="lede">Local defaults for newly created projects.</p></div></header>
    <section className="panel form-stack"><h2>First-launch setup</h2><p>Reset saved setup choices and return to the first-launch screen. Installed tools, projects, and results are kept.</p><button className="button secondary" type="button" disabled={isRunActive} onClick={onResetSetup}>Reset first-launch setup</button>{isRunActive && <p className="field-help">Finish the active workflow before resetting setup.</p>}</section>
    <div className="two-column settings-grid">
      <section className="panel form-stack"><h2>New project location</h2><label>Default project parent folder<input value={defaults.projectParentDirectory} onChange={(event) => setDefaults((current) => ({ ...current, projectParentDirectory: event.target.value }))} placeholder="/absolute/path/to/projects" /></label><div className="directory-actions"><button className="button secondary" type="button" onClick={() => void chooseProjectParent()}>Select folder</button><p className="field-help">A new project name fills in a folder under this location. You can still change it in project setup.</p></div></section>
      <section className="panel form-stack"><h2>Workflow resource budget</h2><div className="field-pair"><label>Total workflow CPU budget<input type="number" min="1" value={defaults.cpus} onChange={(event) => setDefaults((current) => ({ ...current, cpus: Math.max(1, Number(event.target.value) || 1) }))} /></label><label>Total workflow RAM budget (GiB)<input type="number" min="1" value={defaults.memoryGb} onChange={(event) => setDefaults((current) => ({ ...current, memoryGb: Math.max(1, Number(event.target.value) || 1) }))} /></label></div><p className="field-help">These limits cover the workflow as a whole. Leave resources available for the desktop and other local work.</p><button className="button secondary" type="button" onClick={save}>Save local defaults</button></section>
    </div>
    <section className="panel form-stack"><h2>Application Removal</h2><p>Remove Missus Tom from your system. Uninstalling the application does not automatically delete your saved research projects, FASTQ files, reference datasets, or analysis results.</p><button className="button secondary" type="button" disabled={isRunActive} onClick={() => void restorePipelines()}>Restore Original Pipelines</button><hr /><p className="field-help">{isRunActive ? "Finish the active workflow before uninstalling." : uninstall.message}</p><button className="button danger" type="button" disabled={isRunActive || !uninstall.supported} onClick={() => setShowUninstall(true)}>Uninstall Missus Tom</button><p className="field-help">Custom revisions and managed dependencies may remain installed. Project folders and scientific results are never selected for removal.</p></section>
    {message && <p className="settings-message" role="status">{message}</p>}
    {showUninstall && <div className="modal-backdrop" role="presentation"><section className="panel warning-dialog" role="dialog" aria-modal="true" aria-labelledby="uninstall-title"><h2 id="uninstall-title">Uninstall Missus Tom?</h2><p>The installed application will be removed and must be reinstalled to use it again. Running analyses cannot continue through an uninstall. Administrator authorization may be required.</p><p>Projects, scientific results, FASTQ/BAM files, references, and custom pipeline revisions are not automatically deleted. Application-managed dependencies and caches may remain installed.</p><label>Type <code>{UNINSTALL_ACKNOWLEDGEMENT}</code> to continue.<input value={uninstallAck} onChange={(event) => setUninstallAck(event.target.value)} autoFocus /></label><div className="button-row"><button className="button danger" type="button" disabled={uninstallAck !== UNINSTALL_ACKNOWLEDGEMENT} onClick={() => void proceed()}>Proceed to Uninstall</button><button className="button secondary" type="button" onClick={() => { setShowUninstall(false); setUninstallAck(""); }}>Cancel</button></div>{uninstall.command && <p className="field-help">After confirmation, run <code>{uninstall.command}</code> in a terminal. Missus Tom will not claim removal is complete until the package manager confirms it.</p>}</section></div>}
  </div>;
}
