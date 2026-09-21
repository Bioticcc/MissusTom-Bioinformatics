import { useEffect, useState } from "react";
import { apiRequest } from "../api";
import { CheckList } from "../components/CheckList";
import { selectFiles } from "../native";
import type { HumanDemoProject, OpenProjectResult, ProjectManifest, ProjectSummary, RunPlan, SystemPreflight } from "../types";

export function Dashboard({
  onNew,
  onDemo,
  onOpen,
}: {
  onNew: () => void;
  onDemo: (manifest: ProjectManifest, plan: RunPlan) => void;
  onOpen: (manifest: ProjectManifest, plan: RunPlan) => void;
}) {
  const [preflight, setPreflight] = useState<SystemPreflight | null>(null);
  const [error, setError] = useState("");
  const [demoError, setDemoError] = useState("");
  const [loadingDemo, setLoadingDemo] = useState(false);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [projectsError, setProjectsError] = useState("");
  const [openingPath, setOpeningPath] = useState("");

  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    void apiRequest<SystemPreflight>("/api/v1/system/preflight", { signal: controller.signal }).then((result) => {
      if (active) setPreflight(result);
    }).catch((reason: unknown) => {
      if (!active || controller.signal.aborted) return;
      setError(reason instanceof Error ? reason.message : "System readiness could not be checked.");
    });
    void apiRequest<ProjectSummary[]>("/api/v1/projects", { signal: controller.signal }).then((result) => {
      if (active) setProjects(result);
    }).catch((reason: unknown) => {
      if (!active || controller.signal.aborted) return;
      setProjectsError(reason instanceof Error ? reason.message : "Recent projects could not be loaded.");
    });
    return () => {
      active = false;
      controller.abort();
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

  const openProject = async (manifestPath: string) => {
    setOpeningPath(manifestPath);
    setProjectsError("");
    try {
      const project = await apiRequest<OpenProjectResult>("/api/v1/projects/open", {
        method: "POST",
        body: JSON.stringify({ manifest_path: manifestPath }),
      });
      onOpen(project.manifest, project.plan);
    } catch (reason) {
      setProjectsError(reason instanceof Error ? reason.message : "The saved project could not be opened.");
    } finally {
      setOpeningPath("");
    }
  };

  const chooseProject = async () => {
    try {
      const selected = await selectFiles("Open saved Missus Tom project");
      if (selected?.[0]) await openProject(selected[0]);
    } catch (reason) {
      setProjectsError(reason instanceof Error ? reason.message : "Project selection could not be opened.");
    }
  };

  return (
    <div className="page-stack">
      <header className="page-header hero-header">
        <div>
          <p className="eyebrow">Yan Lab · local bioinformatics</p>
          <h1>Bioinformatics project configuration</h1>
          <p className="lede">Configure pipeline-specific inputs, resources, and workflow parameters.</p>
        </div>
        <div className="header-actions">
          <button type="button" className="button primary large" onClick={loadDemo} disabled={loadingDemo}>
            {loadingDemo ? "Loading…" : "Load human demo"}
          </button>
          <button type="button" className="button secondary large" onClick={onNew}>
            New project
          </button>
          <button type="button" className="button secondary large" onClick={() => void chooseProject()} disabled={Boolean(openingPath)}>
            Open project
          </button>
        </div>
      </header>

      {demoError && <div className="inline-error" role="alert">{demoError}</div>}

      <section className="development-banner" aria-label="Development notice">
        <span className="notice-icon" aria-hidden="true">
          i
        </span>
        <div>
          <strong>Local pipeline workbench</strong>
          <p>Create human bulk RNA-seq or mouse ONT analysis projects. The bundled human demo remains available for supported execution checks.</p>
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
            <span className="count-pill">{projects.length}</span>
          </div>
          {projectsError && <div className="inline-error" role="alert">{projectsError}</div>}
          {projects.length === 0 ? <div className="empty-state compact"><div className="empty-orbit" aria-hidden="true">◌</div><h3>No saved projects</h3><p>Open a saved manifest or create a project to begin.</p></div> : <div className="recent-project-list">
            {projects.map((project) => <article className="recent-project" key={project.manifest_path}><div><h3>{project.project_name}</h3><p>{project.project_identifier} · Updated {new Date(project.updated_at).toLocaleString()}</p><small>{project.manifest_path}</small></div><button type="button" className="button secondary" disabled={!project.available || openingPath === project.manifest_path} onClick={() => void openProject(project.manifest_path)}>{openingPath === project.manifest_path ? "Opening…" : project.available ? "Open" : "Unavailable"}</button></article>)}
          </div>}
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
