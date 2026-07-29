use std::io::Write;

use tauri::State;

use crate::events::BackendAction;

use super::state::{lock_error, PythonBridge};

#[tauri::command]
pub async fn send_action(
    action: BackendAction,
    bridge: State<'_, PythonBridge>,
) -> Result<(), String> {
    let line = action
        .into_json_line()
        .map_err(|error| format!("failed to encode backend action: {error}"))?;
    let mut execution = bridge.execution.lock().map_err(lock_error)?;
    let stdin = execution
        .runtime
        .as_mut()
        .and_then(|runtime| runtime.stdin.as_mut())
        .ok_or_else(|| "pipeline is not running".to_string())?;
    stdin
        .write_all(line.as_bytes())
        .and_then(|_| stdin.flush())
        .map_err(|error| format!("failed to write backend action: {error}"))
}
