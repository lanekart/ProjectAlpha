use serde::{Deserialize, Serialize};
use std::fs;
use std::path::PathBuf;
use std::process::Command;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, WebviewWindow};

#[derive(Debug, Serialize)]
struct CommandResult {
    ok: bool,
    message: String,
}

#[derive(Debug, Serialize, Deserialize, Clone, Copy, PartialEq)]
struct WindowPosition {
    x: i32,
    y: i32,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ApprovedApplication {
    Chrome,
    Safari,
    Edge,
    Spotify,
    Calculator,
    Notes,
    Terminal,
    ProjectAlpha,
}

impl ApprovedApplication {
    fn from_id(app_id: &str) -> Option<Self> {
        match app_id {
            "chrome" => Some(Self::Chrome),
            "safari" => Some(Self::Safari),
            "edge" => Some(Self::Edge),
            "spotify" => Some(Self::Spotify),
            "calculator" => Some(Self::Calculator),
            "notes" => Some(Self::Notes),
            "terminal" => Some(Self::Terminal),
            "project-alpha" => Some(Self::ProjectAlpha),
            _ => None,
        }
    }

    fn label(self) -> &'static str {
        match self {
            Self::Chrome => "Google Chrome",
            Self::Safari => "Safari",
            Self::Edge => "Microsoft Edge",
            Self::Spotify => "Spotify",
            Self::Calculator => "Calculator",
            Self::Notes => "Notes",
            Self::Terminal => "Terminal",
            Self::ProjectAlpha => "Project Alpha",
        }
    }

    #[cfg(target_os = "macos")]
    fn mac_bundle(self) -> Option<&'static str> {
        match self {
            Self::Chrome => Some("Google Chrome"),
            Self::Safari => Some("Safari"),
            Self::Edge => Some("Microsoft Edge"),
            Self::Spotify => Some("Spotify"),
            Self::Calculator => Some("Calculator"),
            Self::Notes => Some("Notes"),
            Self::Terminal => Some("Terminal"),
            Self::ProjectAlpha => None,
        }
    }

    #[cfg(target_os = "windows")]
    fn windows_executable(self) -> Option<&'static str> {
        match self {
            Self::Chrome => Some("chrome.exe"),
            Self::Safari => None,
            Self::Edge => Some("msedge.exe"),
            Self::Spotify => Some("Spotify.exe"),
            Self::Calculator => Some("calc.exe"),
            Self::Notes => None,
            Self::Terminal => Some("wt.exe"),
            Self::ProjectAlpha => None,
        }
    }
}

fn app_data_file(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("Could not resolve app data directory: {error}"))?;
    fs::create_dir_all(&dir)
        .map_err(|error| format!("Could not create app data directory: {error}"))?;
    Ok(dir.join("iris-window-position.json"))
}

fn robot_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    app.get_webview_window("main")
        .ok_or_else(|| "IRIS window is not available.".to_string())
}

#[tauri::command]
fn save_window_position(app: AppHandle, position: WindowPosition) -> Result<(), String> {
    let file = app_data_file(&app)?;
    let payload = serde_json::to_string_pretty(&position)
        .map_err(|error| format!("Could not serialize position: {error}"))?;
    fs::write(file, payload).map_err(|error| format!("Could not save position: {error}"))
}

#[tauri::command]
fn load_window_position(app: AppHandle) -> Result<Option<WindowPosition>, String> {
    let file = app_data_file(&app)?;
    if !file.exists() {
        return Ok(None);
    }

    let payload = fs::read_to_string(file)
        .map_err(|error| format!("Could not read saved position: {error}"))?;
    serde_json::from_str(&payload)
        .map(Some)
        .map_err(|error| format!("Could not parse saved position: {error}"))
}

#[tauri::command]
fn hide_robot_window(app: AppHandle) -> Result<(), String> {
    let window = robot_window(&app)?;
    window
        .hide()
        .map_err(|error| format!("Could not hide IRIS: {error}"))
}

#[tauri::command]
fn restore_robot_window(app: AppHandle) -> Result<(), String> {
    let window = robot_window(&app)?;
    window
        .show()
        .and_then(|_| window.set_focus())
        .map_err(|error| format!("Could not restore IRIS: {error}"))?;
    app.emit("iris://restore", ())
        .map_err(|error| format!("Could not notify IRIS UI: {error}"))
}

#[tauri::command]
fn open_approved_application(app_id: String) -> Result<CommandResult, String> {
    let app = ApprovedApplication::from_id(&app_id).ok_or_else(|| {
        format!("{app_id} is not approved. Add it in IRIS settings before use.")
    })?;

    open_application(app)?;
    Ok(CommandResult {
        ok: true,
        message: format!("Opening {}.", app.label()),
    })
}

#[tauri::command]
fn request_close_application(app_id: String) -> Result<CommandResult, String> {
    let app = ApprovedApplication::from_id(&app_id).ok_or_else(|| {
        format!("{app_id} is not approved. Add it in IRIS settings before use.")
    })?;

    request_graceful_close(app)?;
    Ok(CommandResult {
        ok: true,
        message: format!("Asked {} to close.", app.label()),
    })
}

#[tauri::command]
fn start_push_to_talk() -> Result<String, String> {
    Err("Push-to-talk capture is scaffolded, but microphone capture is not enabled in this build. Text commands still work.".to_string())
}

#[tauri::command]
fn speak_text(text: String) -> Result<(), String> {
    speak_native(&text)
}

#[cfg(target_os = "macos")]
fn open_application(app: ApprovedApplication) -> Result<(), String> {
    let bundle = app
        .mac_bundle()
        .ok_or_else(|| format!("{} needs a configured launch path.", app.label()))?;
    Command::new("open")
        .args(["-a", bundle])
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not open {}: {error}", app.label()))
}

#[cfg(target_os = "windows")]
fn open_application(app: ApprovedApplication) -> Result<(), String> {
    let executable = app
        .windows_executable()
        .ok_or_else(|| format!("{} is not available on Windows.", app.label()))?;
    Command::new(executable)
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not open {}: {error}", app.label()))
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn open_application(app: ApprovedApplication) -> Result<(), String> {
    Err(format!("{} is not supported on this platform.", app.label()))
}

#[cfg(target_os = "macos")]
fn request_graceful_close(app: ApprovedApplication) -> Result<(), String> {
    let bundle = app
        .mac_bundle()
        .ok_or_else(|| format!("{} needs a configured launch path.", app.label()))?;
    let script = format!("tell application \"{bundle}\" to quit");
    Command::new("osascript")
        .args(["-e", &script])
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not request close for {}: {error}", app.label()))
}

#[cfg(target_os = "windows")]
fn request_graceful_close(app: ApprovedApplication) -> Result<(), String> {
    let executable = app
        .windows_executable()
        .ok_or_else(|| format!("{} is not available on Windows.", app.label()))?;
    Command::new("taskkill")
        .args(["/im", executable])
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not request close for {}: {error}", app.label()))
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn request_graceful_close(app: ApprovedApplication) -> Result<(), String> {
    Err(format!("{} is not supported on this platform.", app.label()))
}

#[cfg(target_os = "macos")]
fn speak_native(text: &str) -> Result<(), String> {
    Command::new("say")
        .arg(text)
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not speak with macOS voice: {error}"))
}

#[cfg(target_os = "windows")]
fn speak_native(text: &str) -> Result<(), String> {
    let escaped = text.replace('\'', "''");
    let script = format!(
        "Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; $s.Speak('{escaped}')"
    );
    Command::new("powershell")
        .args(["-NoProfile", "-Command", &script])
        .spawn()
        .map(|_| ())
        .map_err(|error| format!("Could not speak with Windows voice: {error}"))
}

#[cfg(not(any(target_os = "macos", target_os = "windows")))]
fn speak_native(_text: &str) -> Result<(), String> {
    Err("Native text-to-speech is only configured for macOS and Windows.".to_string())
}

fn install_tray(app: &tauri::App) -> Result<(), Box<dyn std::error::Error>> {
    let restore = MenuItem::with_id(app, "restore", "Restore IRIS", true, None::<&str>)?;
    let pause = MenuItem::with_id(app, "pause", "Pause Listening", true, None::<&str>)?;
    let dnd = MenuItem::with_id(app, "dnd", "Do Not Disturb", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit IRIS", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&restore, &pause, &dnd, &quit])?;

    TrayIconBuilder::new()
        .tooltip("IRIS")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "restore" => {
                let _ = restore_robot_window(app.clone());
            }
            "pause" => {
                let _ = app.emit("iris://pause-listening", ());
            }
            "dnd" => {
                let _ = app.emit("iris://do-not-disturb", ());
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                let _ = restore_robot_window(tray.app_handle().clone());
            }
        })
        .build(app)?;
    Ok(())
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            None,
        ))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            install_tray(app)?;
            if let Some(window) = app.get_webview_window("main") {
                window.set_always_on_top(true)?;
                window.set_skip_taskbar(true)?;
                window.set_decorations(false)?;
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            hide_robot_window,
            restore_robot_window,
            save_window_position,
            load_window_position,
            open_approved_application,
            request_close_application,
            start_push_to_talk,
            speak_text
        ])
        .run(tauri::generate_context!())
        .expect("error while running IRIS");
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_apps_are_allowlisted() {
        assert_eq!(
            ApprovedApplication::from_id("chrome"),
            Some(ApprovedApplication::Chrome)
        );
        assert_eq!(ApprovedApplication::from_id("unknown"), None);
    }

    #[test]
    fn labels_are_human_readable() {
        assert_eq!(ApprovedApplication::Calculator.label(), "Calculator");
    }
}
