use std::{
    process::{Child, ChildStdin},
    sync::{Arc, Mutex},
    time::Instant,
};

#[derive(Clone, Default)]
pub struct PythonBridge {
    pub(super) stdin: Arc<Mutex<Option<ChildStdin>>>,
    pub(super) child: Arc<Mutex<Option<Child>>>,
    pub(super) child_pid: Arc<Mutex<Option<u32>>>,
    pub(super) child_started_at: Arc<Mutex<Option<Instant>>>,
    pub(super) last_event_at: Arc<Mutex<Option<Instant>>>,
    pub(super) active_app_run_id: Arc<Mutex<Option<String>>>,
    pub(super) event_buffer: Arc<Mutex<Vec<String>>>,
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

pub(super) fn clear_runtime_state_for_app_run_id(
    bridge: &PythonBridge,
    app_run_id: &str,
) {
    let Ok(mut active_app_run_id) = bridge.active_app_run_id.lock() else {
        return;
    };
    if active_app_run_id.as_deref() != Some(app_run_id) {
        return;
    }

    if let Ok(mut stdin) = bridge.stdin.lock() {
        *stdin = None;
    }
    if let Ok(mut pid) = bridge.child_pid.lock() {
        *pid = None;
    }
    if let Ok(mut started_at) = bridge.child_started_at.lock() {
        *started_at = None;
    }
    *active_app_run_id = None;
}

pub(super) fn lock_error<T>(error: std::sync::PoisonError<T>) -> String {
    format!("python bridge state lock poisoned: {error}")
}

#[cfg(test)]
mod tests {
    use std::time::Instant;

    use super::*;

    #[test]
    fn stale_waiter_does_not_clear_newer_app_run_runtime_state() {
        let bridge = PythonBridge::default();
        *bridge.active_app_run_id.lock().expect("active app run lock") =
            Some("run-new".to_string());
        *bridge.child_pid.lock().expect("child pid lock") = Some(4242);
        *bridge
            .child_started_at
            .lock()
            .expect("child started lock") = Some(Instant::now());

        clear_runtime_state_for_app_run_id(&bridge, "run-old");

        assert_eq!(
            bridge
                .active_app_run_id
                .lock()
                .expect("active app run lock")
                .as_deref(),
            Some("run-new")
        );
        assert_eq!(
            *bridge.child_pid.lock().expect("child pid lock"),
            Some(4242)
        );
        assert!(bridge
            .child_started_at
            .lock()
            .expect("child started lock")
            .is_some());

        clear_runtime_state_for_app_run_id(&bridge, "run-new");

        assert!(bridge
            .active_app_run_id
            .lock()
            .expect("active app run lock")
            .is_none());
        assert_eq!(*bridge.child_pid.lock().expect("child pid lock"), None);
        assert!(bridge
            .child_started_at
            .lock()
            .expect("child started lock")
            .is_none());
    }
}
