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

export async function selectFiles(title: string, multiple = false): Promise<string[] | null> {
  if (!isDesktopShell()) {
    throw new Error("File selection is available in the desktop application.");
  }
  return invoke<string[] | null>("select_files", { title, multiple });
}

export async function saveTextFile(
  title: string,
  suggestedName: string,
  contents: string,
): Promise<string | null> {
  if (!isDesktopShell()) {
    throw new Error("Exporting files is available in the desktop application.");
  }
  return invoke<string | null>("save_text_file", { title, suggestedName, contents });
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
