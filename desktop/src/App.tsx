import { useEffect, useRef, useState } from "react";
import { Dashboard } from "./screens/Dashboard";
import { Jobs } from "./screens/Jobs";
import { NewProjectWizard } from "./screens/NewProjectWizard";
import { Results } from "./screens/Results";
import { RunPlanScreen } from "./screens/RunPlanScreen";
import { Settings } from "./screens/Settings";
import { Setup } from "./screens/Setup";
import { apiRequest, getBackendStatus } from "./api";
import { TitleBar } from "./components/TitleBar";
import { isDesktopShell, setDependencyInstallActive, setRunOverlayActive } from "./native";
import { selectActiveRun } from "./runOverlayState";
import { loadSetupState, resetSetupState } from "./setupState";
import type { DependencyJobStatus, HealthStatus, ProjectManifest, RunPlan, RunRecord, ViewId } from "./types";
import { APP_VERSION, formatBuildLabel } from "./appVersion";

const navigation: Array<{ id: ViewId; label: string; glyph: string }> = [
  { id: "dashboard", label: "Dashboard", glyph: "⌂" },
  { id: "setup", label: "Setup", glyph: "⌘" },
  { id: "wizard", label: "New project", glyph: "+" },
  { id: "run-plan", label: "Run plan", glyph: "≡" },
  { id: "jobs", label: "Jobs", glyph: "◷" },
  { id: "results", label: "Results", glyph: "▦" },
  { id: "settings", label: "Settings", glyph: "⚙" },
];

export default function App() {
  const [setupRequired, setSetupRequired] = useState(
    () => isDesktopShell() && !loadSetupState(window.localStorage).completed,
  );
  const [activeView, setActiveView] = useState<ViewId>(() => (
    isDesktopShell() && !loadSetupState(window.localStorage).completed ? "setup" : "dashboard"
  ));
  const [manifest, setManifest] = useState<ProjectManifest | null>(null);
  const [runPlan, setRunPlan] = useState<RunPlan | null>(null);
  const [activeRun, setActiveRun] = useState<RunRecord | null>(null);
  const [polledRuns, setPolledRuns] = useState<RunRecord[] | null>(null);
  const [runPollError, setRunPollError] = useState("");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const runLifecycleGeneration = useRef(0);
  const runStartPending = useRef(false);

  useEffect(() => {
    let live = true;
    const controller = new AbortController();
    void apiRequest<HealthStatus>("/health", { signal: controller.signal }, { requestKind: "short" })
      .then((payload) => {
        if (live) setHealth(payload);
      })
      .catch(() => {
        if (live) setHealth(null);
      });
    return () => { live = false; controller.abort(); };
  }, []);

  useEffect(() => {
    let live = true;
    void getBackendStatus().then((status) => {
      if (live && status?.packaged && !loadSetupState(window.localStorage).completed) {
        setSetupRequired(true);
        setActiveView("setup");
      }
    });
    return () => { live = false; };
  }, []);

  useEffect(() => {
    if (!isDesktopShell()) return;
    let live = true;
    let controller: AbortController | undefined;
    let timer: number | undefined;
    const refresh = async () => {
      let hasActive = false;
      const generation = runLifecycleGeneration.current;
      controller = new AbortController();
      try {
        const runs = await apiRequest<RunRecord[]>("/api/v1/runs", { signal: controller.signal });
        const active = selectActiveRun(runs);
        if (
          !live
          || controller.signal.aborted
          || generation !== runLifecycleGeneration.current
        ) return;
        hasActive = Boolean(active);
        setPolledRuns(runs);
        setActiveRun(active);
        setRunPollError("");
        if (active) runStartPending.current = false;
        try {
          if (active || !runStartPending.current) {
            await setRunOverlayActive(Boolean(active));
          }
        } catch (reason) {
          if (live) setRunPollError(reason instanceof Error ? reason.message : "The minimized run window could not be updated.");
        }
      } catch (reason) {
        if (live && !controller.signal.aborted) setRunPollError(reason instanceof Error ? reason.message : "Run status could not be refreshed.");
      } finally {
        if (live && !controller?.signal.aborted) {
          timer = window.setTimeout(
            () => void refresh(),
            hasActive || runStartPending.current ? 2_000 : 7_000,
          );
        }
      }
    };
    void refresh();
    return () => { live = false; controller?.abort(); if (timer !== undefined) window.clearTimeout(timer); };
  }, []);

  useEffect(() => {
    if (!isDesktopShell()) return;
    let live = true;
    let controller: AbortController | undefined;
    let timer: number | undefined;
    const refresh = async () => {
      controller = new AbortController();
      try {
        const status = await apiRequest<DependencyJobStatus>(
          "/api/v1/dependencies/jobs/active", { signal: controller.signal }, { requestKind: "short" },
        );
        if (live && !controller.signal.aborted) await setDependencyInstallActive(status.active);
      } catch {
        // Preserve the last native busy state when status cannot be confirmed.
      } finally {
        if (live && !controller?.signal.aborted) timer = window.setTimeout(() => void refresh(), 5_000);
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
    // Invalidate polls that began while the start request was pending.
    runLifecycleGeneration.current += 1;
    runStartPending.current = false;
    setActiveRun(record);
    setActiveView("jobs");
  };

  const runStarting = async () => {
    // Invalidate any run-list response that began before this start request.
    runLifecycleGeneration.current += 1;
    runStartPending.current = true;
    try {
      await setRunOverlayActive(true);
    } catch (reason) {
      setRunPollError(reason instanceof Error ? reason.message : "Run lifecycle protection could not be enabled.");
    }
  };

  const runStartFailed = () => {
    // The response may have been lost after backend admission. Keep native busy
    // until a poll started after this settlement confirms the authoritative state.
    runLifecycleGeneration.current += 1;
    runStartPending.current = false;
  };

  return (
    <div className={isDesktopShell() ? "desktop-root" : undefined}>
      <TitleBar />
      <div className="app-shell">
        <aside className="sidebar">
        <div className="brand-block">
          <div className="brand-mark" aria-hidden="true">
            MT
          </div>
          <div>
            <strong>Missus Tom</strong>
            <span>Local bioinformatics workbench</span>
          </div>
        </div>

        <nav aria-label="Primary navigation">
          {(setupRequired ? navigation.filter((item) => item.id === "setup") : navigation).map((item) => (
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
          <span className="version-chip">{formatBuildLabel(health?.version ?? APP_VERSION, health?.build_revision)}</span>
          <p>Local bioinformatics workbench</p>
        </div>
        </aside>

        <main className="main-content" id="main-content">
        {runPollError && <div className="inline-error" role="alert">{runPollError}</div>}
        {activeView === "dashboard" && (
          <Dashboard onNew={() => setActiveView("wizard")} onDemo={projectReady} onOpen={projectReady} />
        )}
        {activeView === "setup" && <Setup
          activeRun={activeRun}
          isRunActive={Boolean(activeRun)}
          onContinue={() => { setSetupRequired(false); setActiveView("dashboard"); }}
        />}
        {activeView === "wizard" && <NewProjectWizard onProjectReady={projectReady} />}
        {activeView === "run-plan" && (
          <RunPlanScreen
            manifest={manifest}
            plan={runPlan}
            onStarting={runStarting}
            onStartFailed={runStartFailed}
            onStarted={runStarted}
          />
        )}
        {activeView === "jobs" && <Jobs activeRun={activeRun} polledRuns={polledRuns} />}
        {activeView === "results" && <Results activeRun={activeRun} />}
        {activeView === "settings" && <Settings onResetSetup={() => { resetSetupState(window.localStorage); setSetupRequired(true); setActiveView("setup"); }} isRunActive={Boolean(activeRun)} />}
        </main>
      </div>
    </div>
  );
}
