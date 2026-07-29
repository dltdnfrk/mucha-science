use std::{
    collections::BTreeSet,
    io::{BufReader, Write},
    process::{Child, Command, Stdio},
    thread,
    time::{Duration, Instant},
};

use tauri::AppHandle;

use super::{
    io::{read_bounded_line, MAX_JSONL_FRAME_BYTES, MAX_STDERR_LINE_BYTES},
    monitor::{emit_backend_event, fail_generation, monitor_exited_child},
    protocol::emit_backend_line,
    state::{lock_error, BridgePhase, ProcessMode, RunningProcess, ScientificBridge},
    BackendEvent,
};

const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);
pub(super) const MONITOR_INTERVAL: Duration = Duration::from_millis(20);

pub(super) fn start_process(
    mut command: Command,
    app: AppHandle,
    bridge: ScientificBridge,
    mode: ProcessMode,
) -> Result<(), String> {
    let generation = bridge.state.lock().map_err(lock_error)?.reserve_start()?;
    let mut child = match command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
    {
        Ok(child) => child,
        Err(error) => {
            reset_failed_start(&bridge, generation)?;
            return Err(format!("failed to start python sidecar: {error}"));
        }
    };
    let stdout = match child.stdout.take() {
        Some(stdout) => stdout,
        None => {
            return fail_start_with_child(
                &bridge,
                generation,
                child,
                "failed to open python stdout",
            );
        }
    };
    let stderr = match child.stderr.take() {
        Some(stderr) => stderr,
        None => {
            return fail_start_with_child(
                &bridge,
                generation,
                child,
                "failed to open python stderr",
            );
        }
    };
    let stdin = match child.stdin.take() {
        Some(stdin) => stdin,
        None => {
            return fail_start_with_child(
                &bridge,
                generation,
                child,
                "failed to open python stdin",
            );
        }
    };
    let mut process = Some(RunningProcess {
        child,
        stdin,
        mode,
        negotiated: false,
        pending_hello: None,
        capabilities: BTreeSet::new(),
    });
    let install_error = {
        let mut state = bridge.state.lock().map_err(lock_error)?;
        if state.phase == BridgePhase::Starting && state.generation == generation {
            state.phase = BridgePhase::Running;
            state.process = process.take();
            None
        } else {
            Some("python sidecar start was superseded by a newer bridge generation".to_string())
        }
    };
    if let Some(error) = install_error {
        let owned_process = process.ok_or_else(|| {
            "superseded sidecar process ownership was unexpectedly lost".to_string()
        })?;
        match terminate_process(owned_process) {
            Ok(()) => {
                reset_failed_start(&bridge, generation)?;
                return Err(error);
            }
            Err((owned_process, termination_error)) => {
                retain_quarantined_process(&bridge, generation, owned_process)?;
                return Err(format!(
                    "{error}; failed to terminate superseded sidecar: {termination_error}"
                ));
            }
        }
    }

    spawn_stdout_reader(app.clone(), bridge.clone(), generation, stdout);
    spawn_stderr_reader(app.clone(), bridge.clone(), generation, stderr);
    thread::spawn(move || monitor_exited_child(&bridge, &app, generation));
    Ok(())
}

fn spawn_stdout_reader(
    app: AppHandle,
    bridge: ScientificBridge,
    generation: u64,
    stdout: impl std::io::Read + Send + 'static,
) {
    thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        loop {
            match read_bounded_line(&mut reader, MAX_JSONL_FRAME_BYTES) {
                Ok(Some(line)) if line.trim().is_empty() => {}
                Ok(Some(line)) => {
                    if let Err(error) = emit_backend_line(&app, &bridge, generation, &line) {
                        emit_backend_event(&app, BackendEvent::error(error));
                    }
                }
                Ok(None) => {
                    if let Err(error) = mark_stdout_eof(&bridge, generation) {
                        fail_generation(&bridge, generation, &app, error);
                    }
                    break;
                }
                Err(error) => {
                    fail_generation(&bridge, generation, &app, error);
                    break;
                }
            }
        }
    });
}

fn spawn_stderr_reader(
    app: AppHandle,
    bridge: ScientificBridge,
    generation: u64,
    stderr: impl std::io::Read + Send + 'static,
) {
    thread::spawn(move || {
        let mut reader = BufReader::new(stderr);
        loop {
            match read_bounded_line(&mut reader, MAX_STDERR_LINE_BYTES) {
                Ok(Some(line)) if line.trim().is_empty() => {}
                Ok(Some(line)) => eprintln!("python sidecar stderr: {line}"),
                Ok(None) => break,
                Err(error) => {
                    fail_generation(&bridge, generation, &app, error);
                    break;
                }
            }
        }
    });
}

fn fail_start_with_child(
    bridge: &ScientificBridge,
    generation: u64,
    mut child: Child,
    message: &str,
) -> Result<(), String> {
    let _ = child.kill();
    let _ = child.wait();
    reset_failed_start(bridge, generation)?;
    Err(message.to_string())
}

fn reset_failed_start(bridge: &ScientificBridge, generation: u64) -> Result<(), String> {
    bridge
        .state
        .lock()
        .map_err(lock_error)?
        .reset_start(generation);
    Ok(())
}

fn retain_quarantined_process(
    bridge: &ScientificBridge,
    generation: u64,
    process: RunningProcess,
) -> Result<(), String> {
    let mut state = bridge.state.lock().map_err(lock_error)?;
    if state.generation != generation || state.process.is_some() {
        return Err("superseded sidecar ownership could not be retained safely".to_string());
    }
    state.phase = BridgePhase::Quarantined;
    state.process = Some(process);
    Ok(())
}

fn terminate_process(mut process: RunningProcess) -> Result<(), (RunningProcess, String)> {
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

pub(crate) fn shutdown_bridge_for_exit(bridge: &ScientificBridge) -> Result<(), String> {
    shutdown_bridge(bridge)
}

fn mark_stdout_eof(bridge: &ScientificBridge, generation: u64) -> Result<(), String> {
    bridge
        .state
        .lock()
        .map_err(lock_error)?
        .mark_stdout_eof(generation)
}
