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
  const [uninstallNextStep, setUninstallNextStep] = useState<"copied" | "manual">();
  const [restoringPipelines, setRestoringPipelines] = useState(false);
  const [restoreStatus, setRestoreStatus] = useState<{ kind: "success" | "error"; text: string }>();
  const save = () => { saveProjectDefaults(defaults); setMessage("Defaults saved on this desktop. They apply to new projects."); };
  useEffect(() => { void getUninstallStatus().then(setUninstall).catch((reason) => setUninstall({ supported: false, message: reason instanceof Error ? reason.message : "The installation type could not be verified." })); }, []);
  const chooseProjectParent = async () => {
    try { const directory = await selectDirectory("Select default project parent folder"); if (directory) setDefaults((current) => ({ ...current, projectParentDirectory: directory })); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : "The project folder could not be selected."); }
  };
  const restorePipelines = async () => {
    if (!window.confirm("Restore official Bulk RNA-seq and ONT pipelines for future runs? Custom revisions will be kept.")) return;
    setRestoringPipelines(true); setRestoreStatus(undefined);
    try { await Promise.all(["bulk-rnaseq", "ont-analysis"].map((pipeline) => apiRequest<PipelineSourceStatus>(`/api/v1/pipeline-sources/${pipeline}/restore`, { method: "POST" }))); setRestoreStatus({ kind: "success", text: "Restored successfully. The official Bulk RNA-seq and ONT pipelines are now active for future runs. Projects, results, and saved custom revisions were not changed." }); }
    catch (reason) { setRestoreStatus({ kind: "error", text: reason instanceof Error ? reason.message : "The official pipelines could not be restored." }); }
    finally { setRestoringPipelines(false); }
  };
  const proceed = async () => {
    if (!uninstall.command) return;
    try { await navigator.clipboard.writeText(uninstall.command); setUninstallNextStep("copied"); }
    catch { setUninstallNextStep("manual"); }
  };
  return <div className="page-stack">
    <header className="page-header"><div><p className="eyebrow">Application configuration</p><h1>Settings</h1><p className="lede">Local defaults for newly created projects.</p></div></header>
    <section className="panel form-stack"><h2>First-launch setup</h2><p>Reset saved setup choices and return to the first-launch screen. Installed tools, projects, and results are kept.</p><button className="button secondary" type="button" disabled={isRunActive} onClick={onResetSetup}>Reset first-launch setup</button>{isRunActive && <p className="field-help">Finish the active workflow before resetting setup.</p>}</section>
    <div className="two-column settings-grid">
      <section className="panel form-stack"><h2>New project location</h2><label>Default project parent folder<input value={defaults.projectParentDirectory} onChange={(event) => setDefaults((current) => ({ ...current, projectParentDirectory: event.target.value }))} placeholder="/absolute/path/to/projects" /></label><div className="directory-actions"><button className="button secondary" type="button" onClick={() => void chooseProjectParent()}>Select folder</button><p className="field-help">A new project name fills in a folder under this location. You can still change it in project setup.</p></div></section>
      <section className="panel form-stack"><h2>Workflow resource budget</h2><div className="field-pair"><label>Total workflow CPU budget<input type="number" min="1" value={defaults.cpus} onChange={(event) => setDefaults((current) => ({ ...current, cpus: Math.max(1, Number(event.target.value) || 1) }))} /></label><label>Total workflow RAM budget (GiB)<input type="number" min="1" value={defaults.memoryGb} onChange={(event) => setDefaults((current) => ({ ...current, memoryGb: Math.max(1, Number(event.target.value) || 1) }))} /></label></div><p className="field-help">These limits cover the workflow as a whole. Leave resources available for the desktop and other local work.</p><button className="button secondary" type="button" onClick={save}>Save local defaults</button></section>
    </div>
    <section className="panel form-stack"><h2>Application Removal</h2><p>Remove Missus Tom from your system. Uninstalling the application does not automatically delete your saved research projects, FASTQ files, reference datasets, or analysis results.</p><button className="button secondary" type="button" disabled={isRunActive || restoringPipelines} onClick={() => void restorePipelines()}>{restoringPipelines ? "Restoring…" : "Restore Original Pipelines"}</button>{restoreStatus && <div className={restoreStatus.kind === "success" ? "success-message restore-pipelines-status" : "inline-error restore-pipelines-status"} role={restoreStatus.kind === "success" ? "status" : "alert"}>{restoreStatus.text}</div>}<hr /><p className="field-help">{isRunActive ? "Finish the active workflow before uninstalling." : uninstall.message}</p><button className="button danger" type="button" disabled={isRunActive || !uninstall.supported} onClick={() => { setUninstallNextStep(undefined); setShowUninstall(true); }}>Uninstall Missus Tom</button><p className="field-help">Custom revisions and managed dependencies may remain installed. Project folders and scientific results are never selected for removal.</p></section>
    {message && <p className="settings-message" role="status">{message}</p>}
    {showUninstall && <div className="modal-backdrop" role="presentation"><section className="panel warning-dialog safety-warning-dialog" role="dialog" aria-modal="true" aria-labelledby="uninstall-title">{uninstallNextStep ? <><h2 id="uninstall-title">Uninstall command ready</h2><div className={uninstallNextStep === "copied" ? "success-message uninstall-command-status" : "warning-list uninstall-command-status"} role="status"><strong>{uninstallNextStep === "copied" ? "Command copied to your clipboard." : "The command could not be copied automatically."}</strong><p>Open a terminal, {uninstallNextStep === "copied" ? "paste the command" : "copy and enter the command below"}, and press Enter:</p><code>{uninstall.command}</code></div><p>Your package manager will ask you to confirm the removal and may request your administrator password. Missus Tom is not removed until that process finishes successfully.</p><div className="button-row warning-actions"><button className="button primary" type="button" onClick={() => { setShowUninstall(false); setUninstallAck(""); setUninstallNextStep(undefined); }}>Done</button><button className="button secondary" type="button" onClick={() => setUninstallNextStep(undefined)}>Back</button></div></> : <><h2 id="uninstall-title">Uninstall Missus Tom?</h2><div className="modification-risk-summary"><p><strong>Application removal:</strong> Missus Tom will be removed and must be reinstalled before you can use it again.</p><p><strong>Running analyses:</strong> Active workflows cannot continue through an uninstall.</p><p><strong>Administrator approval:</strong> Your package manager may ask for authorization before removing the application.</p></div><p><strong>Your research data will be kept.</strong> Projects, scientific results, FASTQ/BAM files, references, and custom pipeline revisions are not automatically deleted. Application-managed dependencies and caches may remain installed.</p><p className="acknowledgement-instruction">Please type "{UNINSTALL_ACKNOWLEDGEMENT}" in the box (without quotations) and click proceed.</p><input aria-label="Uninstall acknowledgement" value={uninstallAck} onChange={(event) => setUninstallAck(event.target.value)} autoFocus /><div className="button-row warning-actions"><button className="button primary" type="button" disabled={uninstallAck !== UNINSTALL_ACKNOWLEDGEMENT} onClick={() => void proceed()}>Proceed to Uninstall</button><button className="button secondary" type="button" onClick={() => { setShowUninstall(false); setUninstallAck(""); }}>Cancel</button></div>{uninstall.command && <p className="field-help">This prepares the verified uninstall command. You will run it in a terminal so the package manager can request authorization and confirm removal.</p>}</>}</section></div>}
  </div>;
}
