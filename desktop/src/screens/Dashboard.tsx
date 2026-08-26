import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { CheckList } from "../components/CheckList";
import type { HumanDemoProject, ProjectManifest, RunPlan, SystemPreflight } from "../types";

export function Dashboard({
  onNew,
  onDemo,
}: {
  onNew: () => void;
  onDemo: (manifest: ProjectManifest, plan: RunPlan) => void;
}) {
  const [preflight, setPreflight] = useState<SystemPreflight | null>(null);
  const [error, setError] = useState("");
  const [demoError, setDemoError] = useState("");
  const [loadingDemo, setLoadingDemo] = useState(false);

  useEffect(() => {
    let active = true;
    apiRequest<SystemPreflight>("/api/v1/system/preflight")
      .then((data) => {
        if (active) setPreflight(data);
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      });
    return () => {
      active = false;
    };
  }, []);

  const passed = preflight?.checks.filter((check) => check.status === "passed").length ?? 0;
  const attention = preflight?.checks.filter((check) => check.status !== "passed").length ?? 0;

  const loadDemo = async () => {
    setLoadingDemo(true);
    setDemoError("");
    try {
      const demo = await apiRequest<HumanDemoProject>("/api/v1/demos/human");
      onDemo(demo.manifest, demo.plan);
    } catch (reason) {
      setDemoError(reason instanceof Error ? reason.message : "The demo could not be loaded.");
    } finally {
      setLoadingDemo(false);
    }
  };

  return (
    <div className="page-stack">
      <header className="page-header hero-header">
        <div>
          <p className="eyebrow">Yan Lab · local bioinformatics</p>
          <h1>Bulk RNA-seq project configuration</h1>
          <p className="lede">Configure inputs, experimental design, and workflow parameters.</p>
        </div>
        <div className="header-actions">
          <button type="button" className="button primary large" onClick={loadDemo} disabled={loadingDemo}>
            {loadingDemo ? "Loading…" : "Load human demo"}
          </button>
          <button type="button" className="button secondary large" onClick={onNew}>
            New project
          </button>
        </div>
      </header>

      {demoError && <div className="inline-error" role="alert">{demoError}</div>}

      <section className="development-banner" aria-label="Development notice">
        <span className="notice-icon" aria-hidden="true">
          i
        </span>
        <div>
          <strong>Controlled human demo</strong>
          <p>Runs local QC, adapter trimming, and kallisto quantification. Differential expression is disabled.</p>
        </div>
      </section>

      <div className="dashboard-grid">
        <section className="panel readiness-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">System</p>
              <h2>Readiness</h2>
            </div>
            <span className={error ? "health-dot offline" : "health-dot"} aria-hidden="true" />
          </div>
          {error ? (
            <div className="inline-error" role="alert">
              {error}
            </div>
          ) : !preflight ? (
            <p className="loading-copy">Checking local tools…</p>
          ) : (
            <>
              <div className="metric-row">
                <div>
                  <strong>{passed}</strong>
                  <span>passed</span>
                </div>
                <div>
                  <strong>{attention}</strong>
                  <span>require review</span>
                </div>
              </div>
              <CheckList checks={preflight.checks} />
            </>
          )}
        </section>

        <section className="panel recent-panel">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Workspace</p>
              <h2>Recent projects</h2>
            </div>
            <span className="count-pill">0</span>
          </div>
          <div className="empty-state compact">
            <div className="empty-orbit" aria-hidden="true">
              ◌
            </div>
            <h3>No saved projects</h3>
            <p>Recent-project loading is not implemented.</p>
          </div>
        </section>
      </div>

      <section className="panel workflow-strip">
        <div>
          <p className="eyebrow">Workflow</p>
          <h2>Project setup sequence</h2>
        </div>
        <ol>
          <li><span>01</span> Discover</li>
          <li><span>02</span> Design</li>
          <li><span>03</span> Validate</li>
          <li><span>04</span> Plan</li>
          <li><span>05</span> Execute</li>
        </ol>
      </section>
    </div>
  );
}
