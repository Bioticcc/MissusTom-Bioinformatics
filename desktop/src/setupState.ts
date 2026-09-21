export type SetupPipelineIdentifier = "bulk-rnaseq" | "ont-analysis";
export type SetupAction = "dependencies" | "fixtures";
export type SetupActionState = "pending" | "complete" | "skipped" | "failed";

export const setupPipelines: SetupPipelineIdentifier[] = ["bulk-rnaseq", "ont-analysis"];
export const SETUP_STORAGE_KEY = "missus-tom.setup.v1";

export interface SetupPipelineState {
  selected: boolean;
  dependencies: boolean;
  fixtures: boolean;
  outcomes: Record<SetupAction, { state: SetupActionState; reason: string }>;
}

export interface PersistedSetupState {
  version: 1;
  pipelines: Record<SetupPipelineIdentifier, SetupPipelineState>;
  completed: boolean;
}

const pending = (): { state: SetupActionState; reason: string } => ({ state: "pending", reason: "" });

export function defaultSetupState(): PersistedSetupState {
  return {
    version: 1,
    completed: false,
    pipelines: {
      "bulk-rnaseq": { selected: true, dependencies: true, fixtures: true, outcomes: { dependencies: pending(), fixtures: pending() } },
      "ont-analysis": { selected: false, dependencies: false, fixtures: false, outcomes: { dependencies: pending(), fixtures: pending() } },
    },
  };
}

function isActionState(value: unknown): value is SetupActionState {
  return value === "pending" || value === "complete" || value === "skipped" || value === "failed";
}

export function loadSetupState(storage: Pick<Storage, "getItem">): PersistedSetupState {
  try {
    const raw: unknown = JSON.parse(storage.getItem(SETUP_STORAGE_KEY) ?? "");
    if (!raw || typeof raw !== "object") return defaultSetupState();
    const candidate = raw as Partial<PersistedSetupState>;
    if (candidate.version !== 1 || !candidate.pipelines) return defaultSetupState();
    const state = defaultSetupState();
    for (const pipeline of setupPipelines) {
      const value = candidate.pipelines[pipeline];
      if (!value || typeof value.selected !== "boolean" || typeof value.dependencies !== "boolean" || typeof value.fixtures !== "boolean") return defaultSetupState();
      state.pipelines[pipeline] = {
        selected: value.selected,
        dependencies: value.dependencies,
        fixtures: value.fixtures,
        outcomes: {
          dependencies: isActionState(value.outcomes?.dependencies?.state) ? value.outcomes.dependencies : pending(),
          fixtures: isActionState(value.outcomes?.fixtures?.state) ? value.outcomes.fixtures : pending(),
        },
      };
    }
    state.completed = areRequestedActionsComplete(state);
    return state;
  } catch {
    return defaultSetupState();
  }
}

export function saveSetupState(storage: Pick<Storage, "setItem">, state: PersistedSetupState): void {
  storage.setItem(SETUP_STORAGE_KEY, JSON.stringify({ ...state, completed: areRequestedActionsComplete(state) }));
}

export function areRequestedActionsComplete(state: PersistedSetupState): boolean {
  const requested = setupPipelines.flatMap((pipeline) => {
    const value = state.pipelines[pipeline];
    return value.selected ? (["dependencies", "fixtures"] as const).filter((action) => value[action]).map((action) => value.outcomes[action]) : [];
  });
  return requested.length > 0 && requested.every((outcome) => outcome.state === "complete" || outcome.state === "skipped");
}

export function updateSetupSelection(
  state: PersistedSetupState,
  pipeline: SetupPipelineIdentifier,
  field: "selected" | SetupAction,
  value: boolean,
): PersistedSetupState {
  const current = state.pipelines[pipeline];
  const outcomes = { ...current.outcomes };
  if (field === "selected" && !value) {
    outcomes.dependencies = pending();
    outcomes.fixtures = pending();
  } else if (field !== "selected") {
    outcomes[field] = pending();
  }
  const next: PersistedSetupState = {
    ...state,
    completed: false,
    pipelines: { ...state.pipelines, [pipeline]: { ...current, [field]: value, outcomes } },
  };
  return { ...next, completed: areRequestedActionsComplete(next) };
}

export function recordSetupOutcome(
  state: PersistedSetupState,
  pipeline: SetupPipelineIdentifier,
  action: SetupAction,
  outcome: { state: SetupActionState; reason: string },
): PersistedSetupState {
  const current = state.pipelines[pipeline];
  const next: PersistedSetupState = {
    ...state,
    pipelines: {
      ...state.pipelines,
      [pipeline]: { ...current, outcomes: { ...current.outcomes, [action]: outcome } },
    },
  };
  return { ...next, completed: areRequestedActionsComplete(next) };
}

export function selectedActions(state: PersistedSetupState, pipeline: SetupPipelineIdentifier): SetupAction[] {
  const value = state.pipelines[pipeline];
  return value.selected ? (["fixtures", "dependencies"] as SetupAction[]).filter((action) => value[action]) : [];
}
