use std::process::Command;

use serde_json::Value;
use tauri::{AppHandle, Manager, State};
use tauri_plugin_shell::ShellExt;

use super::{
    io::write_scientific_line,
    process::{shutdown_bridge, start_process},
    protocol::is_negotiated_scientific,
    sidecar::{establish_muchanipo_home, resolve_sidecar_path, SCIENTIFIC_SIDECAR_BASE},
    state::{ProcessMode, ScientificBridge},
    ScientificEnvelope,
};

#[tauri::command]
pub async fn start_scientific_sidecar(
    _sidecar_path: Option<String>,
    app: AppHandle,
    bridge: State<'_, ScientificBridge>,
) -> Result<(), String> {
    resolve_sidecar_path(&app)?;
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("failed to resolve app-local MUCHANIPO_HOME: {error}"))?;
    let muchanipo_home = establish_muchanipo_home(app_data_dir)?;
    let scientific_home = muchanipo_home
        .to_str()
        .ok_or_else(|| "app-local MUCHANIPO_HOME is not valid UTF-8".to_string())?
        .to_owned();
    let command: Command = app
        .shell()
        .sidecar(SCIENTIFIC_SIDECAR_BASE)
        .map_err(|error| format!("failed to resolve bundled scientific sidecar: {error}"))?
        .args([
            "serve",
            "--topic",
            "scientific-cycle",
            "--scientific-mode",
            "--scientific-home",
            &scientific_home,
        ])
        .env("MUCHANIPO_HOME", muchanipo_home)
        .into();
    start_process(
        command,
        app,
        bridge.inner().clone(),
        ProcessMode::ScientificV1,
    )
}

#[tauri::command]
pub async fn write_envelope(
    envelope: Value,
    bridge: State<'_, ScientificBridge>,
) -> Result<(), String> {
    let envelope = ScientificEnvelope::from_value(envelope)?;
    let line = envelope
        .clone()
        .into_action_json_line(is_negotiated_scientific(&bridge)?)?;
    write_scientific_line(&bridge, &envelope, &line)
}

#[tauri::command]
pub async fn stop_scientific_sidecar(
    bridge: State<'_, ScientificBridge>,
) -> Result<(), String> {
    shutdown_bridge(bridge.inner())
}
