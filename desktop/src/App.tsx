import { useEffect, useState } from "react";
import { Dashboard } from "./screens/Dashboard";
import { Jobs } from "./screens/Jobs";
import { NewProjectWizard } from "./screens/NewProjectWizard";
import { Results } from "./screens/Results";
import { RunPlanScreen } from "./screens/RunPlanScreen";
import { Settings } from "./screens/Settings";
import { apiRequest } from "./api";
import { isDesktopShell, setRunOverlayActive } from "./native";
import { selectActiveRun } from "./runOverlayState";
import type { ProjectManifest, RunPlan, RunRecord, ViewId } from "./types";

const navigation: Array<{ id: ViewId; label: string; glyph: string }> = [
  { id: "dashboard", label: "Dashboard", glyph: "⌂" },
  { id: "wizard", label: "New project", glyph: "+" },
  { id: "run-plan", label: "Run plan", glyph: "≡" },
  { id: "jobs", label: "Jobs", glyph: "◷" },
  { id: "results", label: "Results", glyph: "▦" },
  { id: "settings", label: "Settings", glyph: "⚙" },
];

export default function App() {
  const [activeView, setActiveView] = useState<ViewId>("dashboard");
  const [manifest, setManifest] = useState<ProjectManifest | null>(null);
  const [runPlan, setRunPlan] = useState<RunPlan | null>(null);
  const [activeRun, setActiveRun] = useState<RunRecord | null>(null);
  const [runPollError, setRunPollError] = useState("");

  useEffect(() => {
    if (!isDesktopShell()) return;
    let live = true;
    let controller: AbortController | undefined;
    let timer: number | undefined;
    const refresh = async () => {
      controller = new AbortController();
      try {
        const runs = await apiRequest<RunRecord[]>("/api/v1/runs", { signal: controller.signal });
        const active = selectActiveRun(runs);
        if (!live || controller.signal.aborted) return;
        setActiveRun(active);
        setRunPollError("");
        try {
          await setRunOverlayActive(Boolean(active));
        } catch (reason) {
          if (live) setRunPollError(reason instanceof Error ? reason.message : "The minimized run window could not be updated.");
        }
      } catch (reason) {
        if (live && !controller.signal.aborted) setRunPollError(reason instanceof Error ? reason.message : "Run status could not be refreshed.");
      } finally {
        if (live && !controller?.signal.aborted) timer = window.setTimeout(() => void refresh(), 2_000);
      }
    };
    void refresh();
    return () => { live = false; controller?.abort(); if (timer !== undefined) window.clearTimeout(timer); };
  }, []);

  const projectReady = (nextManifest: ProjectManifest, nextPlan: RunPlan) => {
    setManifest(nextManifest);
    setRunPlan(nextPlan);
    setActiveView("run-plan");
  };

  const runStarted = (record: RunRecord) => {
    setActiveRun(record);
    setActiveView("jobs");
  };

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">
            MT
          </div>
          <div>
            <strong>Missus Tom</strong>
            <span>Yan Lab workbench</span>
          </div>
        </div>

        <nav aria-label="Primary navigation">
          {navigation.map((item) => (
            <button
              type="button"
              className={activeView === item.id ? "nav-item active" : "nav-item"}
              key={item.id}
              onClick={() => setActiveView(item.id)}
              aria-current={activeView === item.id ? "page" : undefined}
            >
              <span aria-hidden="true" className="nav-glyph">
                {item.glyph}
              </span>
              {item.label}
            </button>
          ))}
        </nav>

        <div className="sidebar-foot">
          <span className="version-chip">v0.3.0</span>
          <p>Bulk RNA-seq workbench</p>
        </div>
      </aside>

      <main className="main-content" id="main-content">
        {runPollError && <div className="inline-error" role="alert">{runPollError}</div>}
        {activeView === "dashboard" && (
          <Dashboard onNew={() => setActiveView("wizard")} onDemo={projectReady} onOpen={projectReady} />
        )}
        {activeView === "wizard" && <NewProjectWizard onProjectReady={projectReady} />}
        {activeView === "run-plan" && (
          <RunPlanScreen manifest={manifest} plan={runPlan} onStarted={runStarted} />
        )}
        {activeView === "jobs" && <Jobs activeRun={activeRun} />}
        {activeView === "results" && <Results activeRun={activeRun} />}
        {activeView === "settings" && <Settings />}
      </main>
    </div>
  );
}
