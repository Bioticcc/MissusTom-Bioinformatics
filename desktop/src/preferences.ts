export interface ProjectDefaults {
  projectParentDirectory: string;
  cpus: number;
  memoryGb: number;
}

const storageKey = "missus-tom.project-defaults.v1";
const safeDefaults: ProjectDefaults = { projectParentDirectory: "", cpus: 4, memoryGb: 16 };

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
