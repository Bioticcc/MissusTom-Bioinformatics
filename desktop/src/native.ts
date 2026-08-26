import { invoke } from "@tauri-apps/api/core";

function isDesktopShell() {
  return "__TAURI_INTERNALS__" in window;
}

export async function selectDirectory(title: string): Promise<string | null> {
  if (!isDesktopShell()) {
    throw new Error("Directory selection is available in the desktop application.");
  }
  return invoke<string | null>("select_directory", { title });
}

export async function openDirectory(path: string): Promise<void> {
  if (!isDesktopShell()) {
    throw new Error("Opening folders is available in the desktop application.");
  }
  await invoke("open_directory", { path });
}
