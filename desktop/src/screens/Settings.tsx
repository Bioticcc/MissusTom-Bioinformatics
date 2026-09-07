import { useState } from "react";
import { selectDirectory } from "../native";
import { loadProjectDefaults, saveProjectDefaults } from "../preferences";

export function Settings() {
  const [defaults, setDefaults] = useState(loadProjectDefaults);
  const [message, setMessage] = useState("");
  const save = () => { saveProjectDefaults(defaults); setMessage("Defaults saved on this desktop. They apply to new projects."); };
  const chooseProjectParent = async () => {
    try {
      const directory = await selectDirectory("Select default project parent folder");
      if (directory) setDefaults((current) => ({ ...current, projectParentDirectory: directory }));
    } catch (reason) { setMessage(reason instanceof Error ? reason.message : "The project folder could not be selected."); }
  };
  return <div className="page-stack">
    <header className="page-header"><div><p className="eyebrow">Application configuration</p><h1>Settings</h1><p className="lede">Local defaults for newly created projects.</p></div></header>
    <div className="two-column settings-grid">
      <section className="panel form-stack"><h2>New project location</h2><label>Default project parent folder<input value={defaults.projectParentDirectory} onChange={(event) => setDefaults((current) => ({ ...current, projectParentDirectory: event.target.value }))} placeholder="/absolute/path/to/projects" /></label><div className="directory-actions"><button className="button secondary" type="button" onClick={() => void chooseProjectParent()}>Select folder</button><p className="field-help">A new project name fills in a folder under this location. You can still change it in project setup.</p></div></section>
      <section className="panel form-stack"><h2>Workflow resource budget</h2><div className="field-pair"><label>Total workflow CPU budget<input type="number" min="1" value={defaults.cpus} onChange={(event) => setDefaults((current) => ({ ...current, cpus: Math.max(1, Number(event.target.value) || 1) }))} /></label><label>Total workflow RAM budget (GiB)<input type="number" min="1" value={defaults.memoryGb} onChange={(event) => setDefaults((current) => ({ ...current, memoryGb: Math.max(1, Number(event.target.value) || 1) }))} /></label></div><p className="field-help">These limits cover the workflow as a whole. Leave resources available for the desktop and other local work.</p><button className="button secondary" type="button" onClick={save}>Save local defaults</button>{message && <p className="settings-message" role="status">{message}</p>}</section>
    </div>
  </div>;
}
