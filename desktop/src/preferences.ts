export interface ProjectDefaults {
  projectParentDirectory: string;
  cpus: number;
  memoryGb: number;
}

const storageKey = "missus-tom.project-defaults.v1";
const performanceDiagnosticsStorageKey = "missus-tom.performance-diagnostics.v1";
const safeDefaults: ProjectDefaults = { projectParentDirectory: "", cpus: 4, memoryGb: 16 };
export interface PerformanceDiagnosticsPreferences { hotkey: string; stateLabel: string; }
const safePerformanceDiagnosticsPreferences: PerformanceDiagnosticsPreferences = { hotkey: "Control+Shift+KeyR", stateLabel: "idle" };

function positiveInteger(value: unknown, fallback: number) {
  return typeof value === "number" && Number.isInteger(value) && value > 0 ? value : fallback;
}

export function loadProjectDefaults(): ProjectDefaults {
  try {
    const raw = window.localStorage.getItem(storageKey);
    if (!raw) return safeDefaults;
    const value = JSON.parse(raw) as Partial<ProjectDefaults>;
    return {
      projectParentDirectory: typeof value.projectParentDirectory === "string" ? value.projectParentDirectory : "",
      cpus: positiveInteger(value.cpus, safeDefaults.cpus),
      memoryGb: positiveInteger(value.memoryGb, safeDefaults.memoryGb),
    };
  } catch {
    return safeDefaults;
  }
}

export function saveProjectDefaults(defaults: ProjectDefaults): void {
  window.localStorage.setItem(storageKey, JSON.stringify(defaults));
}

export function loadPerformanceDiagnosticsPreferences(): PerformanceDiagnosticsPreferences {
  try {
    const raw = window.localStorage.getItem(performanceDiagnosticsStorageKey);
    if (!raw) return safePerformanceDiagnosticsPreferences;
    const value = JSON.parse(raw) as Partial<PerformanceDiagnosticsPreferences>;
    return {
      hotkey: typeof value.hotkey === "string" && value.hotkey.length <= 80 ? value.hotkey : safePerformanceDiagnosticsPreferences.hotkey,
      stateLabel: typeof value.stateLabel === "string" && value.stateLabel.length <= 64 ? value.stateLabel : safePerformanceDiagnosticsPreferences.stateLabel,
    };
  } catch {
    return safePerformanceDiagnosticsPreferences;
  }
}

export function savePerformanceDiagnosticsPreferences(preferences: PerformanceDiagnosticsPreferences): void {
  window.localStorage.setItem(performanceDiagnosticsStorageKey, JSON.stringify(preferences));
}
