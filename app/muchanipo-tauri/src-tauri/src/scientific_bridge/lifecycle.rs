use std::{
    thread,
    time::{Duration, Instant},
};

use super::{
    process::MONITOR_INTERVAL,
    state::{lock_error, BridgePhase, RunningProcess, ScientificBridge},
};

const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);

pub(super) fn terminate_process(
    mut process: RunningProcess,
) -> Result<(), (RunningProcess, String)> {
    match process.child.try_wait() {
        Ok(Some(_)) => return Ok(()),
        Err(error) => {
            return Err((
                process,
                format!("failed to inspect python sidecar: {error}"),
            ));
        }
        Ok(None) => {}
    }
    if let Err(error) = process.child.kill() {
        return Err((
            process,
            format!("failed to stop python sidecar: {error}; bridge ownership was retained"),
        ));
    }
    let deadline = Instant::now() + SHUTDOWN_TIMEOUT;
    loop {
        match process.child.try_wait() {
            Ok(Some(_)) => return Ok(()),
            Ok(None) if Instant::now() < deadline => thread::sleep(MONITOR_INTERVAL),
            Ok(None) => {
                return Err((
                    process,
                    "python sidecar did not stop within two seconds; bridge ownership was retained"
                        .to_string(),
                ));
            }
            Err(error) => {
                return Err((
                    process,
                    format!(
                        "failed while stopping python sidecar: {error}; bridge ownership was retained"
                    ),
                ));
            }
        }
    }
}

pub(super) fn shutdown_bridge(bridge: &ScientificBridge) -> Result<(), String> {
    let (generation, process) = {
        let mut state = bridge.state.lock().map_err(lock_error)?;
        match state.phase {
            BridgePhase::Starting => {
                state.phase = BridgePhase::Stopping;
                return Ok(());
            }
            BridgePhase::Running | BridgePhase::Quarantined => {
                let generation = state.generation;
                let process = state.process.take().ok_or_else(|| {
                    "python bridge active state has no process ownership".to_string()
                })?;
                state.phase = BridgePhase::Stopping;
                (generation, process)
            }
            BridgePhase::Stopped | BridgePhase::Stopping => return Ok(()),
        }
    };
    match terminate_process(process) {
        Ok(()) => {
            let mut state = bridge.state.lock().map_err(lock_error)?;
            if state.generation == generation && state.phase == BridgePhase::Stopping {
                state.phase = BridgePhase::Stopped;
                state.stdout_eof = false;
            }
            Ok(())
        }
        Err((process, error)) => {
            let mut state = bridge.state.lock().map_err(lock_error)?;
            if state.generation == generation && state.phase == BridgePhase::Stopping {
                state.phase = BridgePhase::Quarantined;
                state.process = Some(process);
            }
            Err(error)
        }
    }
}

pub(crate) fn shutdown_bridge_for_exit(
    bridge: &ScientificBridge,
) -> Result<(), String> {
    shutdown_bridge(bridge)
}
