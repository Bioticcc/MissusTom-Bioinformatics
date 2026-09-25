use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tauri::{
    AppHandle, Manager, State, WebviewUrl, WebviewWindow, WebviewWindowBuilder, WindowEvent,
};
use tauri_plugin_dialog::DialogExt;

const MAIN_WINDOW_LABEL: &str = "main";
const RUN_OVERLAY_LABEL: &str = "run-overlay";
const RUN_OVERLAY_WIDTH: f64 = 360.0;
const RUN_OVERLAY_HEIGHT: f64 = 300.0;
const RUN_OVERLAY_MARGIN: f64 = 16.0;
const PACKAGED_API_HOST: &str = "127.0.0.1";
const PACKAGED_API_PORT: u16 = 8765;
const HEALTH_ATTEMPTS: u8 = 30;
const HEALTH_RETRY_DELAY: Duration = Duration::from_millis(200);

struct RunOverlayState {
    active: Arc<AtomicBool>,
}

struct DependencyInstallState {
    active: AtomicBool,
}

struct BackendState {
    child: Mutex<Option<Child>>,
    ready: AtomicBool,
}

impl Default for BackendState {
    fn default() -> Self {
        Self {
            child: Mutex::new(None),
            ready: AtomicBool::new(false),
        }
    }
}

#[derive(Serialize)]
struct BackendStatus {
    base_url: String,
    ready: bool,
    packaged: bool,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "snake_case")]
enum TextExportKind {
    Settings,
    Log,
}

impl TextExportKind {
    fn allowed_extensions(&self) -> &'static [&'static str] {
        match self {
            Self::Settings => &["json"],
            Self::Log => &["log", "txt"],
        }
    }

    fn filter_name(&self) -> &'static str {
        match self {
            Self::Settings => "JSON files",
            Self::Log => "Log files",
        }
    }
}

fn enforce_export_extension(
    mut requested: PathBuf,
    export_kind: &TextExportKind,
) -> Result<PathBuf, String> {
    if requested.extension().is_none() {
        requested.set_extension(export_kind.allowed_extensions()[0]);
    }
    let extension = requested
        .extension()
        .and_then(|extension| extension.to_str())
        .map(str::to_ascii_lowercase);
    if !extension
        .as_deref()
        .is_some_and(|extension| export_kind.allowed_extensions().contains(&extension))
    {
        return Err(format!(
            "The selected export must use one of: {}.",
            export_kind.allowed_extensions().join(", ")
        ));
    }
    Ok(requested)
}

fn validate_export_destination(requested: PathBuf) -> Result<PathBuf, String> {
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
    match std::fs::symlink_metadata(&destination) {
        Ok(metadata) => {
            if metadata.file_type().is_symlink() || !metadata.is_file() {
                return Err(
                    "The export destination must be a regular file, not a link or directory."
                        .to_string(),
                );
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => return Err(format!("Could not inspect the export destination: {error}")),
    }
    Ok(destination)
}

#[cfg(unix)]
fn replace_export_entry(temporary: &Path, destination: &Path) -> std::io::Result<()> {
    // POSIX rename atomically replaces a directory entry and does not follow a final-component
    // symlink, including one substituted after destination validation.
    std::fs::rename(temporary, destination)
}

#[cfg(not(unix))]
fn replace_export_entry(temporary: &Path, destination: &Path) -> std::io::Result<()> {
    // Keep the conservative rename-only behavior on platforms where replacement semantics differ:
    // an existing destination can fail, but no selected path is reopened for writing.
    std::fs::rename(temporary, destination)
}

fn write_export_atomically(destination: &Path, contents: &str) -> Result<(), String> {
    let parent = destination
        .parent()
        .ok_or_else(|| "The export destination has no parent directory.".to_string())?;
    let file_name = destination
        .file_name()
        .ok_or_else(|| "The export destination has no file name.".to_string())?
        .to_string_lossy();
    let nonce = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|error| format!("Could not create a temporary export name: {error}"))?
        .as_nanos();
    let mut temporary = None;
    for attempt in 0..32 {
        let candidate = parent.join(format!(
            ".{file_name}.missus-tom-{}-{nonce}-{attempt}.tmp",
            std::process::id()
        ));
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&candidate)
        {
            Ok(mut file) => {
                if let Err(error) = file.write_all(contents.as_bytes()) {
                    let _ = std::fs::remove_file(&candidate);
                    return Err(format!("Could not write the settings export: {error}"));
                }
                if let Err(error) = file.sync_all() {
                    let _ = std::fs::remove_file(&candidate);
                    return Err(format!("Could not finalize the settings export: {error}"));
                }
                temporary = Some(candidate);
                break;
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => return Err(format!("Could not create the settings export: {error}")),
        }
    }
    let temporary =
        temporary.ok_or_else(|| "Could not create a unique temporary export file.".to_string())?;

    let result = replace_export_entry(&temporary, destination);
    if let Err(error) = result {
        let _ = std::fs::remove_file(&temporary);
        return Err(format!("Could not finalize the settings export: {error}"));
    }
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum CloseDecision {
    ExitAndStopBackend,
    KeepRunningForActiveWork,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum StartupDecision {
    AlreadyStarted,
    StartOwnedBackend,
    RejectOccupiedPort,
}

impl Default for RunOverlayState {
    fn default() -> Self {
        Self {
            active: Arc::new(AtomicBool::new(false)),
        }
    }
}

impl Default for DependencyInstallState {
    fn default() -> Self {
        Self {
            active: AtomicBool::new(false),
        }
    }
}

fn packaged_api_base() -> String {
    format!("http://{PACKAGED_API_HOST}:{PACKAGED_API_PORT}")
}

fn sidecar_paths(executable_dir: &Path) -> (PathBuf, PathBuf) {
    (
        executable_dir.join("missus-tom-backend"),
        executable_dir.join("ont-analysis-runner"),
    )
}

fn parse_health_response(response: &str) -> bool {
    let Some((status_line, body)) = response.split_once("\r\n") else {
        return false;
    };
    if !status_line.starts_with("HTTP/1.")
        || !status_line.split_whitespace().any(|part| part == "200")
    {
        return false;
    }
    let Some((_, body)) = body.split_once("\r\n\r\n") else {
        return false;
    };
    serde_json::from_str::<serde_json::Value>(body)
        .ok()
        .and_then(|value| {
            value
                .pointer("/data/status")
                .and_then(serde_json::Value::as_str)
                .map(str::to_owned)
        })
        .as_deref()
        == Some("ok")
}

fn health_is_ready() -> bool {
    use std::io::{Read, Write};
    use std::net::{SocketAddr, TcpStream};

    let address: SocketAddr = format!("{PACKAGED_API_HOST}:{PACKAGED_API_PORT}")
        .parse()
        .expect("packaged API address is valid");
    let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(150)) else {
        return false;
    };
    let _ = stream.set_read_timeout(Some(Duration::from_millis(250)));
    let _ = stream.set_write_timeout(Some(Duration::from_millis(250)));
    if stream
        .write_all(b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n")
        .is_err()
    {
        return false;
    }
    let mut response = String::new();
    stream.read_to_string(&mut response).is_ok() && parse_health_response(&response)
}

fn packaged_port_is_available() -> bool {
    std::net::TcpListener::bind((PACKAGED_API_HOST, PACKAGED_API_PORT)).is_ok()
}

fn startup_decision(port_is_available: bool, child_exists: bool) -> StartupDecision {
    if child_exists {
        StartupDecision::AlreadyStarted
    } else if port_is_available {
        StartupDecision::StartOwnedBackend
    } else {
        StartupDecision::RejectOccupiedPort
    }
}

fn close_decision(run_is_active: bool, install_is_active: bool) -> CloseDecision {
    if run_is_active || install_is_active {
        CloseDecision::KeepRunningForActiveWork
    } else {
        CloseDecision::ExitAndStopBackend
    }
}

fn start_packaged_backend(app: &AppHandle) -> Result<(), String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("Could not locate packaged resources: {error}"))?;
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("Could not locate application data: {error}"))?;
    let executable_dir = std::env::current_exe()
        .map_err(|error| format!("Could not locate the packaged executable: {error}"))?
        .parent()
        .ok_or_else(|| "The packaged executable has no parent directory.".to_string())?
        .to_path_buf();
    std::fs::create_dir_all(&app_data_dir)
        .map_err(|error| format!("Could not create application data directory: {error}"))?;

    let (backend, ont_runner) = sidecar_paths(&executable_dir);
    if !backend.is_file() || !ont_runner.is_file() {
        return Err(
            "Packaged backend sidecars are missing. Rebuild the Linux sidecars before bundling."
                .to_string(),
        );
    }

    let state = app.state::<BackendState>();
    let child = state
        .child
        .lock()
        .map_err(|_| "Backend lifecycle state is unavailable.".to_string())?;
    match startup_decision(packaged_port_is_available(), child.is_some()) {
        StartupDecision::AlreadyStarted => return Ok(()),
        StartupDecision::RejectOccupiedPort => {
            return Err(
                "The packaged backend port is already in use; refusing to adopt or stop that process."
                    .to_string(),
            );
        }
        StartupDecision::StartOwnedBackend => {}
    }
    drop(child);
    let mut child = state
        .child
        .lock()
        .map_err(|_| "Backend lifecycle state is unavailable.".to_string())?;
    let started = Command::new(&backend)
        .args([] as [&str; 0])
        .env("MISSUS_TOM_API_HOST", PACKAGED_API_HOST)
        .env("MISSUS_TOM_API_PORT", PACKAGED_API_PORT.to_string())
        .env("MISSUS_TOM_RESOURCE_ROOT", &resource_dir)
        .env("MISSUS_TOM_STATE_DIR", &app_data_dir)
        .env("MISSUS_TOM_ONT_RUNNER", &ont_runner)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|error| format!("Could not start the packaged backend: {error}"))?;
    *child = Some(started);
    drop(child);

    for _ in 0..HEALTH_ATTEMPTS {
        if health_is_ready() {
            state.ready.store(true, Ordering::Release);
            return Ok(());
        }
        std::thread::sleep(HEALTH_RETRY_DELAY);
    }
    stop_owned_backend(&state);
    Err("The packaged backend did not become ready on its dedicated local port.".to_string())
}

fn stop_owned_backend(state: &BackendState) {
    let Ok(mut child) = state.child.lock() else {
        return;
    };
    if let Some(mut child) = child.take() {
        let _ = child.kill();
        let _ = child.wait();
    }
    state.ready.store(false, Ordering::Release);
}

fn should_show_overlay(active: bool, main_is_minimized: bool) -> bool {
    active && main_is_minimized
}

fn bottom_left_overlay_position(
    work_area_position: (i32, i32),
    work_area_size: (u32, u32),
    scale: f64,
) -> (i32, i32) {
    let width = (RUN_OVERLAY_WIDTH * scale).round() as i64;
    let height = (RUN_OVERLAY_HEIGHT * scale).round() as i64;
    let margin = (RUN_OVERLAY_MARGIN * scale).round() as i64;
    let left = i64::from(work_area_position.0);
    let top = i64::from(work_area_position.1);
    let right = left + i64::from(work_area_size.0);
    let bottom = top + i64::from(work_area_size.1);
    let x = (left + margin).min(right - width).max(left);
    let y = (bottom - height - margin).max(top);

    (x as i32, y as i32)
}

fn initial_overlay_position(main: &WebviewWindow) -> Option<(i32, i32)> {
    let monitor = main
        .current_monitor()
        .ok()
        .flatten()
        .or_else(|| main.primary_monitor().ok().flatten())?;
    let work_area = monitor.work_area();
    Some(bottom_left_overlay_position(
        (work_area.position.x, work_area.position.y),
        (work_area.size.width, work_area.size.height),
        monitor.scale_factor(),
    ))
}

fn sync_run_overlay<R: tauri::Runtime>(app: &tauri::AppHandle<R>, active: bool) {
    let Some(main) = app.get_webview_window(MAIN_WINDOW_LABEL) else {
        return;
    };
    let Some(overlay) = app.get_webview_window(RUN_OVERLAY_LABEL) else {
        return;
    };

    let should_show = should_show_overlay(active, main.is_minimized().unwrap_or(false));
    if should_show {
        // `show` does not request focus; the window was also created unfocused.
        if !overlay.is_visible().unwrap_or(false) {
            let _ = overlay.show();
        }
    } else if overlay.is_visible().unwrap_or(false) {
        let _ = overlay.hide();
    }
}

fn require_caller(window: &WebviewWindow, expected_label: &str) -> Result<(), String> {
    if window.label() == expected_label {
        Ok(())
    } else {
        Err("This command is not available from this window.".to_string())
    }
}

#[tauri::command]
fn set_run_overlay_active(
    window: WebviewWindow,
    state: State<'_, RunOverlayState>,
    active: bool,
) -> Result<(), String> {
    require_caller(&window, MAIN_WINDOW_LABEL)?;
    state.active.store(active, Ordering::Release);
    sync_run_overlay(&window.app_handle(), active);
    Ok(())
}

#[tauri::command]
fn set_dependency_install_active(
    window: WebviewWindow,
    state: State<'_, DependencyInstallState>,
    active: bool,
) -> Result<(), String> {
    require_caller(&window, MAIN_WINDOW_LABEL)?;
    state.active.store(active, Ordering::Release);
    Ok(())
}

#[tauri::command]
fn backend_status(state: State<'_, BackendState>) -> BackendStatus {
    let packaged_ready =
        !cfg!(debug_assertions) && state.ready.load(Ordering::Acquire) && health_is_ready();
    BackendStatus {
        base_url: if cfg!(debug_assertions) {
            "http://127.0.0.1:8000".to_string()
        } else {
            packaged_api_base()
        },
        ready: !cfg!(debug_assertions) && packaged_ready,
        packaged: !cfg!(debug_assertions),
    }
}

#[tauri::command]
fn restore_main_window(window: WebviewWindow) -> Result<(), String> {
    require_caller(&window, RUN_OVERLAY_LABEL)?;
    let app = window.app_handle();
    let main = app
        .get_webview_window(MAIN_WINDOW_LABEL)
        .ok_or_else(|| "The main window is unavailable.".to_string())?;

    main.unminimize()
        .map_err(|error| format!("Could not restore the main window: {error}"))?;
    main.show()
        .map_err(|error| format!("Could not show the main window: {error}"))?;
    main.set_focus()
        .map_err(|error| format!("Could not focus the main window: {error}"))?;
    if let Some(overlay) = app.get_webview_window(RUN_OVERLAY_LABEL) {
        let _ = overlay.hide();
    }
    Ok(())
}

#[tauri::command]
async fn save_text_file(
    window: WebviewWindow,
    title: String,
    suggested_name: String,
    contents: String,
    export_kind: TextExportKind,
) -> Result<Option<String>, String> {
    let selected = window
        .dialog()
        .file()
        .set_parent(&window)
        .set_title(title)
        .set_file_name(suggested_name)
        .add_filter(export_kind.filter_name(), export_kind.allowed_extensions())
        .blocking_save_file();
    let Some(selected) = selected else {
        return Ok(None);
    };
    let requested = selected
        .into_path()
        .map_err(|_| "The file saver returned an unsupported path.".to_string())?;
    let requested = enforce_export_extension(requested, &export_kind)?;
    let destination = validate_export_destination(requested)?;
    write_export_atomically(&destination, &contents)?;
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
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            app.manage(RunOverlayState::default());
            app.manage(DependencyInstallState::default());
            app.manage(BackendState::default());
            if !cfg!(debug_assertions) {
                start_packaged_backend(&app.handle())?;
            }

            let main = app
                .get_webview_window(MAIN_WINDOW_LABEL)
                .ok_or("The main window is unavailable during startup.")?;
            let overlay_position = initial_overlay_position(&main);
            let overlay = WebviewWindowBuilder::new(
                app,
                RUN_OVERLAY_LABEL,
                WebviewUrl::App("index.html?overlay=run".into()),
            )
            .title("Missus Tom run status")
            .inner_size(RUN_OVERLAY_WIDTH, RUN_OVERLAY_HEIGHT)
            .resizable(false)
            .decorations(false)
            .always_on_top(true)
            .skip_taskbar(true)
            .visible(false)
            .focused(false)
            .build()?;
            if let Some((x, y)) = overlay_position {
                overlay.set_position(tauri::Position::Physical(tauri::PhysicalPosition::new(
                    x, y,
                )))?;
            }

            let handle = app.handle().clone();
            let active = app.state::<RunOverlayState>().active.clone();
            std::thread::spawn(move || loop {
                std::thread::sleep(Duration::from_millis(500));
                sync_run_overlay(&handle, active.load(Ordering::Acquire));
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if window.label() == MAIN_WINDOW_LABEL
                && matches!(event, WindowEvent::CloseRequested { .. })
            {
                let active = window
                    .app_handle()
                    .state::<RunOverlayState>()
                    .active
                    .load(Ordering::Acquire);
                let install_active = window
                    .app_handle()
                    .state::<DependencyInstallState>()
                    .active
                    .load(Ordering::Acquire);
                match close_decision(active, install_active) {
                    CloseDecision::KeepRunningForActiveWork => {
                        if let WindowEvent::CloseRequested { api, .. } = event {
                            api.prevent_close();
                        }
                        let _ = window.hide();
                    }
                    CloseDecision::ExitAndStopBackend => {
                        if let Some(overlay) =
                            window.app_handle().get_webview_window(RUN_OVERLAY_LABEL)
                        {
                            let _ = overlay.close();
                        }
                        stop_owned_backend(&window.app_handle().state::<BackendState>());
                        // The overlay is a second native window, so explicitly exit when the main
                        // window closes instead of allowing it to keep the application alive.
                        window.app_handle().exit(0);
                    }
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            save_text_file,
            read_text_file,
            open_directory,
            set_run_overlay_active,
            set_dependency_install_active,
            restore_main_window,
            backend_status
        ])
        .run(tauri::generate_context!())
        .expect("error while running Missus Tom");
}

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::{
        bottom_left_overlay_position, close_decision, enforce_export_extension,
        parse_health_response, should_show_overlay, sidecar_paths, startup_decision,
        validate_export_destination, write_export_atomically, CloseDecision, StartupDecision,
        TextExportKind,
    };

    #[test]
    fn overlay_is_only_shown_for_an_active_minimized_run() {
        assert!(should_show_overlay(true, true));
        assert!(!should_show_overlay(true, false));
        assert!(!should_show_overlay(false, true));
        assert!(!should_show_overlay(false, false));
    }

    #[test]
    fn overlay_position_uses_the_work_area_and_monitor_scale() {
        assert_eq!(
            bottom_left_overlay_position((-1920, 0), (1920, 1080), 1.0),
            (-1904, 764)
        );
        assert_eq!(
            bottom_left_overlay_position((0, 0), (2880, 1620), 1.5),
            (24, 1146)
        );
    }

    #[test]
    fn packaged_sidecars_use_tauri_runtime_names_next_to_the_app() {
        let (backend, runner) = sidecar_paths(Path::new("/app/bin"));
        assert_eq!(backend, Path::new("/app/bin/missus-tom-backend"));
        assert_eq!(runner, Path::new("/app/bin/ont-analysis-runner"));
    }

    #[test]
    fn health_response_requires_the_expected_api_envelope() {
        assert!(parse_health_response(
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"data\":{\"status\":\"ok\"}}"
        ));
        assert!(!parse_health_response(
            "HTTP/1.1 200 OK\r\n\r\n{\"data\":{\"status\":\"starting\"}}"
        ));
        assert!(!parse_health_response(
            "HTTP/1.1 503 Service Unavailable\r\n\r\n{\"data\":{\"status\":\"ok\"}}"
        ));
    }

    #[test]
    fn active_runs_keep_the_owned_backend_alive_on_close() {
        assert_eq!(
            close_decision(true, false),
            CloseDecision::KeepRunningForActiveWork
        );
        assert_eq!(
            close_decision(false, true),
            CloseDecision::KeepRunningForActiveWork
        );
        assert_eq!(
            close_decision(true, true),
            CloseDecision::KeepRunningForActiveWork
        );
        assert_eq!(
            close_decision(false, false),
            CloseDecision::ExitAndStopBackend
        );
    }

    #[test]
    fn backend_never_adopts_an_occupied_packaged_port() {
        assert_eq!(
            startup_decision(false, false),
            StartupDecision::RejectOccupiedPort
        );
        assert_eq!(
            startup_decision(false, true),
            StartupDecision::AlreadyStarted
        );
        assert_eq!(
            startup_decision(true, false),
            StartupDecision::StartOwnedBackend
        );
    }

    #[test]
    fn text_exports_enforce_their_approved_suffixes() {
        assert_eq!(
            enforce_export_extension(
                Path::new("settings").to_path_buf(),
                &TextExportKind::Settings
            )
            .unwrap(),
            Path::new("settings.json")
        );
        assert!(enforce_export_extension(
            Path::new("settings.txt").to_path_buf(),
            &TextExportKind::Settings,
        )
        .is_err());
        assert!(enforce_export_extension(
            Path::new("command.log").to_path_buf(),
            &TextExportKind::Log
        )
        .is_ok());
        assert!(enforce_export_extension(
            Path::new("command.txt").to_path_buf(),
            &TextExportKind::Log
        )
        .is_ok());
    }

    #[cfg(unix)]
    #[test]
    fn text_exports_reject_dangling_symlink_destinations() {
        use std::os::unix::fs::symlink;

        let directory =
            std::env::temp_dir().join(format!("missus-tom-export-test-{}", std::process::id()));
        std::fs::create_dir_all(&directory).unwrap();
        let destination = directory.join("export.json");
        symlink(directory.join("missing-target"), &destination).unwrap();

        assert!(validate_export_destination(destination).is_err());

        std::fs::remove_file(directory.join("export.json")).unwrap();
        std::fs::remove_dir(directory).unwrap();
    }

    #[cfg(unix)]
    #[test]
    fn atomic_export_replaces_a_substituted_symlink_without_touching_its_target() {
        use std::os::unix::fs::symlink;

        let directory = std::env::temp_dir().join(format!(
            "missus-tom-atomic-export-test-{}",
            std::process::id()
        ));
        std::fs::create_dir_all(&directory).unwrap();
        let target = directory.join("target.txt");
        let destination = directory.join("export.json");
        std::fs::write(&target, "original target").unwrap();
        symlink(&target, &destination).unwrap();

        write_export_atomically(&destination, "replacement export").unwrap();

        assert_eq!(std::fs::read_to_string(&target).unwrap(), "original target");
        assert_eq!(
            std::fs::read_to_string(&destination).unwrap(),
            "replacement export"
        );
        assert!(!std::fs::symlink_metadata(&destination)
            .unwrap()
            .file_type()
            .is_symlink());

        std::fs::remove_file(&destination).unwrap();
        std::fs::remove_file(&target).unwrap();
        std::fs::remove_dir(directory).unwrap();
    }
}
