use tauri::State;

use super::{
    state::{lock_error, PythonBridge},
    workspace::workspace_root,
};

#[derive(serde::Serialize)]
pub struct PipelineRuntimeStatus {
    pub running: bool,
    pub stdin_open: bool,
    pub child_tracked: bool,
    pub buffered_event_count: usize,
    pub child_pid: Option<u32>,
    pub app_run_id: Option<String>,
    pub runtime_age_ms: Option<u128>,
    pub last_event_elapsed_ms: Option<u128>,
    pub app_binary_path: Option<String>,
    pub workspace_root: String,
}

#[tauri::command]
pub async fn pipeline_runtime_status(
    bridge: State<'_, PythonBridge>,
) -> Result<PipelineRuntimeStatus, String> {
    let execution = bridge.execution.lock().map_err(lock_error)?;
    let runtime = execution.runtime.as_ref();
    let stdin_open = runtime.is_some_and(|runtime| runtime.stdin.is_some());
    let child_tracked = runtime.is_some();
    let child_running = runtime
        .and_then(|runtime| runtime.child.try_lock().ok())
        .map(|mut child| child.try_wait().ok().flatten().is_none())
        .unwrap_or(child_tracked);
    let child_pid = runtime
        .and_then(|runtime| runtime.receipt.identity.as_ref())
        .map(|identity| identity.pid);
    let app_run_id = runtime.map(|runtime| runtime.receipt.app_run_id.clone());
    let runtime_age_ms = runtime.map(|runtime| runtime.started_at.elapsed().as_millis());
    drop(execution);

    let buffered_event_count = bridge.event_buffer.lock().map_err(lock_error)?.len();
    let last_event_elapsed_ms = bridge
        .last_event_at
        .lock()
        .map_err(lock_error)?
        .as_ref()
        .map(|last_event_at| last_event_at.elapsed().as_millis());

    Ok(PipelineRuntimeStatus {
        running: child_running,
        stdin_open,
        child_tracked,
        buffered_event_count,
        child_pid,
        app_run_id,
        runtime_age_ms,
        last_event_elapsed_ms,
        app_binary_path: std::env::current_exe()
            .ok()
            .map(|path| path.display().to_string()),
        workspace_root: workspace_root().display().to_string(),
    })
}
