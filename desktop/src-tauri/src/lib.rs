use std::path::{Path, PathBuf};
use std::process::Command;

#[tauri::command]
fn select_directory(title: String) -> Result<Option<String>, String> {
    let output = Command::new("zenity")
        .args(["--file-selection", "--directory", "--title", &title])
        .output()
        .map_err(|error| format!("Could not start the directory selector: {error}"))?;

    if !output.status.success() {
        if output.status.code() == Some(1) {
            return Ok(None);
        }
        return Err("The directory selector did not complete successfully.".to_string());
    }

    let selected = String::from_utf8(output.stdout)
        .map_err(|_| "The directory selector returned an invalid path.".to_string())?;
    let selected = selected.trim();
    if selected.is_empty() {
        return Ok(None);
    }
    let canonical = PathBuf::from(selected)
        .canonicalize()
        .map_err(|error| format!("Could not resolve the selected directory: {error}"))?;
    if !canonical.is_dir() {
        return Err("The selected path is not a directory.".to_string());
    }
    Ok(Some(canonical.to_string_lossy().into_owned()))
}

#[tauri::command]
fn open_directory(path: String) -> Result<(), String> {
    let requested = Path::new(&path);
    if !requested.is_absolute() {
        return Err("The directory path must be absolute.".to_string());
    }
    let canonical = requested
        .canonicalize()
        .map_err(|error| format!("Could not resolve the directory: {error}"))?;
    if !canonical.is_dir() {
        return Err("The requested path is not a directory.".to_string());
    }
    Command::new("xdg-open")
        .arg(canonical)
        .spawn()
        .map_err(|error| format!("Could not open the directory: {error}"))?;
    Ok(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![select_directory, open_directory])
        .run(tauri::generate_context!())
        .expect("error while running Missus Tom");
}
