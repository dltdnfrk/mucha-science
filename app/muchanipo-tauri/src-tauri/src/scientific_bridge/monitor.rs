use std::thread;

use tauri::{AppHandle, Emitter};

use super::{
    process::{shutdown_bridge, MONITOR_INTERVAL},
    state::{lock_error, BridgePhase, ScientificBridge},
    BackendEvent,
};

pub(super) fn fail_generation(
    bridge: &ScientificBridge,
    generation: u64,
    app: &AppHandle,
    message: String,
) {
    if quarantine_generation(bridge, generation) {
        if let Err(error) = shutdown_bridge(bridge) {
            emit_backend_event(
                app,
                BackendEvent::error(format!("{message}; failed to stop sidecar: {error}")),
            );
            return;
        }
    }
    emit_backend_event(app, BackendEvent::error(message));
}

fn quarantine_generation(bridge: &ScientificBridge, generation: u64) -> bool {
    bridge
        .state
        .lock()
        .map(|mut state| state.quarantine(generation))
        .unwrap_or(false)
}

pub(super) fn monitor_exited_child(
    bridge: &ScientificBridge,
    app: &AppHandle,
    generation: u64,
) {
    loop {
        let result = inspect_child(bridge, generation);
        match result {
            Ok(Some(status)) => {
                if !status.success() {
                    emit_backend_event(
                        app,
                        BackendEvent::error(format!("python sidecar exited with {status}")),
                    );
                }
                return;
            }
            Ok(None) => {
                if !is_current_generation(bridge, generation) {
                    return;
                }
                thread::sleep(MONITOR_INTERVAL);
            }
            Err(error) => {
                fail_generation(bridge, generation, app, error);
                return;
            }
        }
    }
}

fn inspect_child(
    bridge: &ScientificBridge,
    generation: u64,
) -> Result<Option<std::process::ExitStatus>, String> {
    let mut state = bridge.state.lock().map_err(lock_error)?;
    if state.phase != BridgePhase::Running || state.generation != generation {
        return Ok(None);
    }
    let stdout_eof = state.stdout_eof;
    let process = state
        .process
        .as_mut()
        .ok_or_else(|| "python bridge running state has no process ownership".to_string())?;
    match process.child.try_wait() {
        Ok(Some(status)) if stdout_eof => {
            state.process = None;
            state.phase = BridgePhase::Stopped;
            Ok(Some(status))
        }
        Ok(Some(_)) | Ok(None) => Ok(None),
        Err(error) => Err(format!("failed to check python sidecar: {error}")),
    }
}

fn is_current_generation(bridge: &ScientificBridge, generation: u64) -> bool {
    bridge
        .state
        .lock()
        .map(|state| state.phase == BridgePhase::Running && state.generation == generation)
        .unwrap_or(false)
}

pub(super) fn emit_backend_event(app: &AppHandle, event: BackendEvent) {
    if let Err(error) = app.emit("backend_event", event) {
        eprintln!("failed to emit backend_event: {error}");
    }
}
