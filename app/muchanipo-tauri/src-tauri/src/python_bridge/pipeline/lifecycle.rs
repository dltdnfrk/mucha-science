use std::{
    process::{Child, ChildStdin, ExitStatus},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use tauri::AppHandle;

use crate::events::BackendEvent;

use super::super::{
    backend_events::{emit_backend_event, with_app_run_id},
    state::{
        clear_runtime_state, lock_error, BridgeExecutionState, LaunchReceipt, PythonBridge,
        RuntimeExecution, TerminalKind,
    },
};

pub(super) struct SpawnedChild {
    pub(super) child: Child,
    pub(super) stdin: ChildStdin,
    pub(super) receipt: LaunchReceipt,
}

pub(super) struct WaitContext {
    pub(super) app: AppHandle,
    pub(super) bridge: PythonBridge,
    pub(super) app_run_id: String,
    pub(super) generation: u64,
    pub(super) child: Arc<Mutex<Child>>,
}

pub(super) fn install_child(state: &mut BridgeExecutionState, spawned: SpawnedChild) {
    state.runtime = Some(RuntimeExecution {
        receipt: spawned.receipt,
        child: Arc::new(Mutex::new(spawned.child)),
        stdin: Some(spawned.stdin),
        started_at: Instant::now(),
    });
}

pub(super) fn clear_telemetry_for_start(bridge: &PythonBridge) {
    if let Ok(mut buffer) = bridge.event_buffer.lock() {
        buffer.clear();
    }
    if let Ok(mut last_event_at) = bridge.last_event_at.lock() {
        *last_event_at = None;
    }
}

pub(super) fn spawn_child_waiter(context: WaitContext) {
    thread::spawn(move || {
        let status = wait_for_child(&context.child);
        let terminal_kind = match status.as_ref() {
            Ok(status) if status.success() => TerminalKind::Completed,
            Ok(_) | Err(_) => TerminalKind::Failed,
        };
        if let Ok(mut execution) = context.bridge.execution.lock() {
            if let Some(owner) = execution.owner.as_mut() {
                let _ = owner.terminalize(
                    &context.app_run_id,
                    context.generation,
                    terminal_kind,
                    true,
                    true,
                );
            }
        }
        match status {
            Ok(status) if status.success() => {}
            Ok(status) => emit_wait_error(
                &context,
                format!("python pipeline exited with {status}"),
            ),
            Err(error) => emit_wait_error(
                &context,
                format!("failed to wait for python pipeline: {error}"),
            ),
        }
        clear_runtime_state(
            &context.bridge,
            &context.app_run_id,
            context.generation,
        );
    });
}

fn wait_for_child(child: &Arc<Mutex<Child>>) -> Result<ExitStatus, String> {
    loop {
        let result = child
            .lock()
            .map_err(lock_error)?
            .try_wait()
            .map_err(|error| error.to_string())?;
        if let Some(status) = result {
            return Ok(status);
        }
        thread::sleep(Duration::from_millis(20));
    }
}

fn emit_wait_error(context: &WaitContext, message: String) {
    emit_backend_event(
        &context.app,
        with_app_run_id(BackendEvent::error(message), &context.app_run_id),
    );
}
