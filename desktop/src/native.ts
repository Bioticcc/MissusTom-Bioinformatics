import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { getCurrentWindow } from "@tauri-apps/api/window";

type TextExportKind = "settings" | "log";

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
