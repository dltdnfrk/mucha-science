// Prevents additional console window on Windows in release.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod events;
mod python_bridge;
mod scientific_bridge;
mod scientific_events;

use python_bridge::{
    check_cli_smoke, check_cli_status, get_buffered_events, open_cli_auth, pipeline_runtime_status,
    send_action, start_pipeline, PythonBridge,
};
use scientific_bridge::{
    shutdown_bridge_for_exit, start_scientific_sidecar, stop_scientific_sidecar, write_envelope,
    ScientificBridge,
};
use tauri::Manager;

#[tauri::command]
fn ping() -> &'static str {
    "pong"
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(PythonBridge::default())
        .manage(ScientificBridge::default())
        .invoke_handler(tauri::generate_handler![
            ping,
            start_pipeline,
            send_action,
            check_cli_status,
            check_cli_smoke,
            open_cli_auth,
            get_buffered_events,
            pipeline_runtime_status,
            start_scientific_sidecar,
            write_envelope,
            stop_scientific_sidecar
        ])
        .build(tauri::generate_context!())
        .expect("error while building Muchanipo Tauri app")
        .run(|app, event| {
            if matches!(event, tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. }) {
                if let Err(error) = shutdown_bridge_for_exit(app.state::<ScientificBridge>().inner()) {
                    eprintln!("failed to stop scientific sidecar during app exit: {error}");
                }
            }
        });
}
