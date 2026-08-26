import { useState } from "react";

export function Settings() {
  const [diagnostics, setDiagnostics] = useState(false);
  return (
    <div className="page-stack">
      <header className="page-header"><div><p className="eyebrow">Application configuration</p><h1>Settings</h1><p className="lede">Settings are not persisted in version 0.3.0.</p></div></header>
      <div className="two-column settings-grid">
        <section className="panel form-stack">
          <h2>Project defaults</h2>
          <label>Default project directory<input placeholder="/absolute/path/to/projects" /></label>
          <label>Reference-resource directory<input placeholder="/absolute/path/to/references" /></label>
          <label>Execution profile<select defaultValue="local"><option value="local">Local</option><option value="docker">Docker</option><option value="apptainer">Apptainer</option></select></label>
          <label>Container preference<select defaultValue="none"><option value="none">No preference</option><option value="docker">Docker</option><option value="apptainer">Apptainer</option></select></label>
        </section>
        <section className="panel form-stack">
          <h2>Resource limits</h2>
          <div className="field-pair"><label>CPU limit<input type="number" min="1" defaultValue="4" /></label><label>Memory (GiB)<input type="number" min="1" defaultValue="8" /></label></div>
          <label className="check-field"><input type="checkbox" checked={diagnostics} onChange={(event) => setDiagnostics(event.target.checked)} /><span><strong>Prepare local diagnostic reports</strong><small>No report is transmitted. Remote diagnostics are out of scope.</small></span></label>
          <button className="button secondary" type="button" disabled>Save preferences (not implemented)</button>
        </section>
      </div>
    </div>
  );
}
