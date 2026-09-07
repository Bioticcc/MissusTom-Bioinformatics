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
fn select_files(title: String, multiple: bool) -> Result<Option<Vec<String>>, String> {
    let mut command = Command::new("zenity");
    command.args(["--file-selection", "--title", &title]);
    if multiple {
        command.args(["--multiple", "--separator=\n"]);
    }
    let output = command
        .output()
        .map_err(|error| format!("Could not start the file selector: {error}"))?;

    if !output.status.success() {
        if output.status.code() == Some(1) {
            return Ok(None);
        }
        return Err("The file selector did not complete successfully.".to_string());
    }

    let selected = String::from_utf8(output.stdout)
        .map_err(|_| "The file selector returned an invalid path.".to_string())?;
    let mut files = Vec::new();
    for value in selected.lines().filter(|value| !value.trim().is_empty()) {
        let canonical = PathBuf::from(value.trim())
            .canonicalize()
            .map_err(|error| format!("Could not resolve the selected file: {error}"))?;
        if !canonical.is_file() {
            return Err("A selected path is not a file.".to_string());
        }
        files.push(canonical.to_string_lossy().into_owned());
    }
    Ok((!files.is_empty()).then_some(files))
}

#[tauri::command]
fn save_text_file(
    title: String,
    suggested_name: String,
    contents: String,
) -> Result<Option<String>, String> {
    let output = Command::new("zenity")
        .args([
            "--file-selection",
            "--save",
            "--confirm-overwrite",
            "--title",
            &title,
            "--filename",
            &suggested_name,
            "--file-filter=JSON files | *.json",
        ])
        .output()
        .map_err(|error| format!("Could not start the file saver: {error}"))?;

    if !output.status.success() {
        if output.status.code() == Some(1) {
            return Ok(None);
        }
        return Err("The file saver did not complete successfully.".to_string());
    }

    let selected = String::from_utf8(output.stdout)
        .map_err(|_| "The file saver returned an invalid path.".to_string())?;
    let selected = selected.trim();
    if selected.is_empty() {
        return Ok(None);
    }
    let mut requested = PathBuf::from(selected);
    if requested.extension().is_none() {
        requested.set_extension("json");
    }
    if !requested.is_absolute() {
        return Err("The export path must be absolute.".to_string());
    }
    let parent = requested
        .parent()
        .ok_or_else(|| "The export path has no parent directory.".to_string())?
        .canonicalize()
        .map_err(|error| format!("Could not resolve the export directory: {error}"))?;
    if !parent.is_dir() {
        return Err("The export destination is not a directory.".to_string());
    }
    let file_name = requested
        .file_name()
        .ok_or_else(|| "The export path has no file name.".to_string())?;
    let destination = parent.join(file_name);
    if destination.exists() && !destination.is_file() {
        return Err("The export destination is not a file.".to_string());
    }
    std::fs::write(&destination, contents)
        .map_err(|error| format!("Could not write the settings export: {error}"))?;
    Ok(Some(destination.to_string_lossy().into_owned()))
}

#[tauri::command]
fn read_text_file(path: String) -> Result<String, String> {
    let requested = PathBuf::from(path)
        .canonicalize()
        .map_err(|error| format!("Could not resolve the settings file: {error}"))?;
    if !requested.is_file() {
        return Err("The selected settings path is not a file.".to_string());
    }
    let size = requested
        .metadata()
        .map_err(|error| format!("Could not inspect the settings file: {error}"))?
        .len();
    if size > 50 * 1024 * 1024 {
        return Err("The settings file is larger than the 50 MiB limit.".to_string());
    }
    std::fs::read_to_string(requested)
        .map_err(|error| format!("Could not read the settings file as UTF-8: {error}"))
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
        .invoke_handler(tauri::generate_handler![
            select_directory,
            select_files,
            save_text_file,
            read_text_file,
            open_directory
        ])
        .run(tauri::generate_context!())
        .expect("error while running Missus Tom");
}
