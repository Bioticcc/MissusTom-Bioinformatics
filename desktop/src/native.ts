import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { getCurrentWindow } from "@tauri-apps/api/window";

type TextExportKind = "settings" | "log";
export type UninstallStatus = { supported: boolean; package_name?: string | null; command?: string | null; message: string };
export type PerformanceDiagnosticsStatus = { active: boolean; state_label?: string | null; started_at?: string | null; sample_count: number; };
export type PerformanceDiagnosticsResult = { path: string; state_label: string; started_at: string; stopped_at: string; sample_count: number; };

export function isDesktopShell() {
  return "__TAURI_INTERNALS__" in window;
}

export async function selectDirectory(title: string): Promise<string | null> {
  if (!isDesktopShell()) {
    throw new Error("Directory selection is available in the desktop application.");
  }
  return open({ title, directory: true });
}

export async function selectFiles(title: string, multiple = false): Promise<string[] | null> {
  if (!isDesktopShell()) {
    throw new Error("File selection is available in the desktop application.");
  }
  const selected = await open({ title, multiple });
  if (selected === null) return null;
  return Array.isArray(selected) ? selected : [selected];
}

export async function saveTextFile(
  title: string,
  suggestedName: string,
  contents: string,
  exportKind: TextExportKind,
): Promise<string | null> {
  if (!isDesktopShell()) {
    throw new Error("Exporting files is available in the desktop application.");
  }
  return invoke<string | null>("save_text_file", { title, suggestedName, contents, exportKind });
}

export async function readTextFile(path: string): Promise<string> {
  if (!isDesktopShell()) {
    throw new Error("Importing files is available in the desktop application.");
  }
  return invoke<string>("read_text_file", { path });
}

export async function openDirectory(path: string): Promise<void> {
  if (!isDesktopShell()) {
    throw new Error("Opening folders is available in the desktop application.");
  }
  await invoke("open_directory", { path });
}

export async function setRunOverlayActive(active: boolean): Promise<void> {
  if (!isDesktopShell()) return;
  await invoke("set_run_overlay_active", { active });
}

export async function setDependencyInstallActive(active: boolean): Promise<void> {
  if (!isDesktopShell()) return;
  await invoke("set_dependency_install_active", { active });
}

export async function restoreMainWindow(): Promise<void> {
  if (!isDesktopShell()) return;
  await invoke("restore_main_window");
}

export async function startOverlayDragging(): Promise<void> {
  if (!isDesktopShell()) return;
  await getCurrentWindow().startDragging();
}

export async function startMainWindowDragging(): Promise<void> {
  if (!isDesktopShell()) return;
  await getCurrentWindow().startDragging();
}

export async function minimizeMainWindow(): Promise<void> {
  if (!isDesktopShell()) return;
  await getCurrentWindow().minimize();
}

export async function toggleMaximizeMainWindow(): Promise<void> {
  if (!isDesktopShell()) return;
  await getCurrentWindow().toggleMaximize();
}

export async function closeMainWindow(): Promise<void> {
  if (!isDesktopShell()) return;
  await invoke("close_main_window");
}

export async function isMainWindowMaximized(): Promise<boolean> {
  if (!isDesktopShell()) return false;
  return getCurrentWindow().isMaximized();
}

export async function getUninstallStatus(): Promise<UninstallStatus> {
  if (!isDesktopShell()) return { supported: false, message: "Application removal is unavailable from a development build." };
  return invoke<UninstallStatus>("uninstall_status");
}

export async function getPerformanceDiagnosticsStatus(): Promise<PerformanceDiagnosticsStatus> {
  if (!isDesktopShell()) return { active: false, sample_count: 0 };
  return invoke<PerformanceDiagnosticsStatus>("performance_diagnostics_status");
}

export async function startPerformanceDiagnostics(stateLabel: string): Promise<PerformanceDiagnosticsStatus> {
  if (!isDesktopShell()) throw new Error("Performance diagnostics are available in the desktop application.");
  return invoke<PerformanceDiagnosticsStatus>("start_performance_diagnostics", { stateLabel });
}

export async function stopPerformanceDiagnostics(): Promise<PerformanceDiagnosticsResult> {
  if (!isDesktopShell()) throw new Error("Performance diagnostics are available in the desktop application.");
  return invoke<PerformanceDiagnosticsResult>("stop_performance_diagnostics");
}
