use std::{
    process::{Child, ChildStdin},
    sync::{Arc, Mutex},
    time::Instant,
};

pub(super) use super::{
    execution_contract::{
        CancellationDecision, LaunchDecision, LaunchReceipt, LaunchRequest, TerminalKind,
    },
    execution_owner::ExecutionOwner,
    execution_platform::{
        await_verified_handshake, cancel_path, canonical_executable, configure_process_group,
        executable_digest, finalizer_path, handshake_path, now_unix_ms, observe_process,
        owner_boot_id, signal_verified_process_group, write_cancel_token,
    },
};

#[derive(Clone, Default)]
pub struct PythonBridge {
    pub(super) execution: Arc<Mutex<BridgeExecutionState>>,
    pub(super) last_event_at: Arc<Mutex<Option<Instant>>>,
    pub(super) event_buffer: Arc<Mutex<Vec<String>>>,
}

#[derive(Default)]
pub(super) struct BridgeExecutionState {
    pub(super) owner: Option<ExecutionOwner>,
    pub(super) runtime: Option<RuntimeExecution>,
}

pub(super) struct RuntimeExecution {
    pub(super) receipt: LaunchReceipt,
    pub(super) child: Arc<Mutex<Child>>,
    pub(super) stdin: Option<ChildStdin>,
    pub(super) started_at: Instant,
}

const EVENT_BUFFER_CAP: usize = 2000;

pub(super) fn push_event_buffer(bridge: &PythonBridge, line: &str) {
    if let Ok(mut buffer) = bridge.event_buffer.lock() {
        if buffer.len() >= EVENT_BUFFER_CAP {
            buffer.drain(0..EVENT_BUFFER_CAP / 4);
        }
        buffer.push(line.to_string());
    }
}

pub(super) fn mark_backend_event_seen(bridge: &PythonBridge) {
    if let Ok(mut last_event_at) = bridge.last_event_at.lock() {
        *last_event_at = Some(Instant::now());
    }
}

pub(super) fn clear_runtime_state(bridge: &PythonBridge, app_run_id: &str, generation: u64) {
    let Ok(mut execution) = bridge.execution.lock() else {
        return;
    };
    let matches_generation = execution.runtime.as_ref().is_some_and(|runtime| {
        runtime.receipt.app_run_id == app_run_id && runtime.receipt.generation == generation
    });
    if matches_generation {
        execution.runtime = None;
    }
}

pub(super) fn lock_error<T>(error: std::sync::PoisonError<T>) -> String {
    format!("python bridge state lock poisoned: {error}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn event_buffer_evicts_oldest_quarter_at_capacity() {
        let bridge = PythonBridge::default();
        for index in 0..EVENT_BUFFER_CAP {
            push_event_buffer(&bridge, &index.to_string());
        }

        push_event_buffer(&bridge, "newest");

        let buffer = bridge.event_buffer.lock().expect("event buffer lock");
        assert_eq!(buffer.len(), EVENT_BUFFER_CAP - EVENT_BUFFER_CAP / 4 + 1);
        assert_eq!(buffer.first().map(String::as_str), Some("500"));
        assert_eq!(buffer.last().map(String::as_str), Some("newest"));
    }
}
