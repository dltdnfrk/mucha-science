// Scientific (ai-scientist.v1) sidecar bridge: generation-based lifecycle,
// manifest-verified packaged sidecar resolution, and negotiated envelope IO.
// Split out of python_bridge.rs during the main <- ai-scientist merge so the
// legacy research-pipeline bridge and this state machine stay independent.
use std::{
    collections::BTreeSet,
    fs,
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
    process::{Child, ChildStdin, Command, Stdio},
    sync::{Arc, Mutex},
    thread,
    time::{Duration, Instant},
};

use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_shell::ShellExt;

use crate::scientific_events::{
    BackendAction, BackendEvent, BackendMessage, BackendMode, ScientificEnvelope,
};

const SHUTDOWN_TIMEOUT: Duration = Duration::from_secs(2);
const MONITOR_INTERVAL: Duration = Duration::from_millis(20);
const MAX_JSONL_FRAME_BYTES: usize = 64 * 1024;
const MAX_STDERR_LINE_BYTES: usize = 16 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum BridgePhase { Stopped, Starting, Running, Stopping, Quarantined }

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ProcessMode { Legacy, ScientificV1 }

impl ProcessMode {
    fn backend_mode(self) -> BackendMode {
        match self {
            Self::Legacy => BackendMode::Legacy,
            Self::ScientificV1 => BackendMode::ScientificV1,
        }
    }
}

struct RunningProcess {
    child: Child,
    stdin: ChildStdin,
    mode: ProcessMode,
    negotiated: bool,
    pending_hello: Option<String>,
    capabilities: BTreeSet<String>,
}

struct BridgeState {
    generation: u64,
    phase: BridgePhase,
    stdout_eof: bool,
    process: Option<RunningProcess>,
}

impl Default for BridgeState {
    fn default() -> Self {
        Self {
            generation: 0,
            phase: BridgePhase::Stopped,
            stdout_eof: false,
            process: None,
        }
    }
}

impl BridgeState {
    fn reserve_start(&mut self) -> Result<u64, String> {
        match self.phase {
            BridgePhase::Stopped => {
                self.generation = self.generation.wrapping_add(1);
                self.phase = BridgePhase::Starting;
                self.stdout_eof = false;
                Ok(self.generation)
            }
            BridgePhase::Starting => Err("python sidecar is already starting".to_string()),
            BridgePhase::Running => Err("python sidecar is already running".to_string()),
            BridgePhase::Stopping => Err("python sidecar is stopping".to_string()),
            BridgePhase::Quarantined => Err("python sidecar cleanup must complete before starting another sidecar".to_string()),
        }
    }

    fn reset_start(&mut self, generation: u64) {
        if self.generation == generation
            && matches!(self.phase, BridgePhase::Starting | BridgePhase::Stopping)
            && self.process.is_none()
        {
            self.phase = BridgePhase::Stopped;
            self.stdout_eof = false;
        }
    }

    fn quarantine(&mut self, generation: u64) -> bool {
        if self.phase == BridgePhase::Running && self.generation == generation {
            self.phase = BridgePhase::Quarantined;
            true
        } else {
            false
        }
    }

    fn accepts_writes(&self) -> bool {
        self.phase == BridgePhase::Running
    }

    fn mark_stdout_eof(&mut self, generation: u64) -> Result<(), String> {
        if self.phase != BridgePhase::Running || self.generation != generation {
            return Ok(());
        }
        let process = self
            .process
            .as_mut()
            .ok_or_else(|| "python bridge running state has no process ownership".to_string())?;
        self.stdout_eof = true;
        match process.child.try_wait() {
            Ok(Some(_)) => Ok(()),
            Ok(None) => Err("python sidecar stdout closed before the child exited".to_string()),
            Err(error) => Err(format!("failed to inspect python sidecar after stdout closed: {error}")),
        }
    }

    #[cfg(test)]
    pub(crate) fn phase(&self) -> BridgePhase {
        self.phase
    }

    #[cfg(test)]
    pub(crate) fn generation(&self) -> u64 {
        self.generation
    }
}

#[derive(Clone, Default)]
pub struct ScientificBridge { state: Arc<Mutex<BridgeState>> }
#[cfg(test)]
impl ScientificBridge {
    pub(crate) fn reserve_start_for_test(&self) -> Result<u64, String> {
        self.state.lock().map_err(lock_error)?.reserve_start()
    }

    pub(crate) fn reset_start_for_test(&self, generation: u64) -> Result<(), String> {
        let mut state = self.state.lock().map_err(lock_error)?;
        state.reset_start(generation);
        Ok(())
    }


    pub(crate) fn lifecycle_for_test(&self) -> Result<(BridgePhase, u64), String> {
        let state = self.state.lock().map_err(lock_error)?;
        Ok((state.phase(), state.generation()))
    }
    pub(crate) fn quarantine_for_test(&self, generation: u64) -> Result<(), String> {
        let mut state = self.state.lock().map_err(lock_error)?;
        if state.phase == BridgePhase::Starting && state.generation == generation {
            state.phase = BridgePhase::Running;
        }
        if state.quarantine(generation) {
            Ok(())
        } else {
            Err("test generation could not be quarantined".to_string())
        }
    }

    pub(crate) fn accepts_writes_for_test(&self) -> Result<bool, String> {
        Ok(self.state.lock().map_err(lock_error)?.accepts_writes())
    }

    pub(crate) fn quarantine_owned_process_for_test(&self, generation: u64) -> Result<(), String> {
        let mut command = Command::new("sh");
        command
            .args(["-c", "sleep 30"])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        let mut child = command
            .spawn()
            .map_err(|error| format!("failed to spawn test sidecar: {error}"))?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| "test sidecar has no stdin".to_string())?;
        let process = RunningProcess {
            child,
            stdin,
            mode: ProcessMode::Legacy,
            negotiated: false,
            pending_hello: None,
            capabilities: BTreeSet::new(),
        };
        let mut state = self.state.lock().map_err(lock_error)?;
        if state.phase != BridgePhase::Starting || state.generation != generation {
            return Err("test sidecar start was unexpectedly superseded".to_string());
        }
        state.phase = BridgePhase::Quarantined;
        state.process = Some(process);
        Ok(())
    }

    pub(crate) fn has_process_for_test(&self) -> Result<bool, String> {
        Ok(self.state.lock().map_err(lock_error)?.process.is_some())
    }
    pub(crate) fn write_is_rejected_for_test(&self) -> Result<(), String> {
        write_legacy_line(self, "{\"event\":\"test\"}\n")
    }
}

// The merged app serves the legacy research pipeline through
// python_bridge::start_pipeline; this bridge only manages the scientific sidecar.

#[tauri::command]
pub async fn start_scientific_sidecar(_sidecar_path: Option<String>, app: AppHandle, bridge: State<'_, ScientificBridge>) -> Result<(), String> {
    resolve_sidecar_path(&app)?;
    let app_data_dir = app.path().app_data_dir().map_err(|error| format!("failed to resolve app-local MUCHANIPO_HOME: {error}"))?;
    let muchanipo_home = establish_muchanipo_home(app_data_dir)?;
    let scientific_home = muchanipo_home
        .to_str()
        .ok_or_else(|| "app-local MUCHANIPO_HOME is not valid UTF-8".to_string())?
        .to_owned();
    let command: Command = app
        .shell()
        .sidecar(SCIENTIFIC_SIDECAR_BASE)
        .map_err(|error| format!("failed to resolve bundled scientific sidecar: {error}"))?
        .args(["serve", "--topic", "scientific-cycle", "--scientific-mode", "--scientific-home", &scientific_home])
        .env("MUCHANIPO_HOME", muchanipo_home)
        .into();
    start_process(command, app, bridge.inner().clone(), ProcessMode::ScientificV1)
}

#[tauri::command]
pub async fn write_envelope(envelope: Value, bridge: State<'_, ScientificBridge>) -> Result<(), String> {
    let envelope = ScientificEnvelope::from_value(envelope)?;
    let line = envelope.clone().into_action_json_line(is_negotiated_scientific(&bridge)?)?;
    write_scientific_line(&bridge, &envelope, &line)
}

#[tauri::command]
pub async fn stop_scientific_sidecar(bridge: State<'_, ScientificBridge>) -> Result<(), String> {
    shutdown_bridge(bridge.inner())
}

pub(crate) fn shutdown_bridge_for_exit(bridge: &ScientificBridge) -> Result<(), String> {
    shutdown_bridge(bridge)
}

fn shutdown_bridge(bridge: &ScientificBridge) -> Result<(), String> {
    let (generation, process) = {
        let mut state = bridge.state.lock().map_err(lock_error)?;
        match state.phase {
            BridgePhase::Starting => {
                state.phase = BridgePhase::Stopping;
                return Ok(());
            }
            BridgePhase::Running | BridgePhase::Quarantined => {
                let generation = state.generation;
                let process = state
                    .process
                    .take()
                    .ok_or_else(|| "python bridge active state has no process ownership".to_string())?;
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

fn start_process(mut command: Command, app: AppHandle, bridge: ScientificBridge, mode: ProcessMode) -> Result<(), String> {
    let generation = { let mut state = bridge.state.lock().map_err(lock_error)?; state.reserve_start()? };
    let mut child = match command.stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn() {
        Ok(child) => child,
        Err(error) => { reset_failed_start(&bridge, generation)?; return Err(format!("failed to start python sidecar: {error}")); }
    };
    let stdout = match child.stdout.take() { Some(stdout) => stdout, None => return fail_start_with_child(&bridge, generation, child, "failed to open python stdout") };
    let stderr = match child.stderr.take() { Some(stderr) => stderr, None => return fail_start_with_child(&bridge, generation, child, "failed to open python stderr") };
    let stdin = match child.stdin.take() { Some(stdin) => stdin, None => return fail_start_with_child(&bridge, generation, child, "failed to open python stdin") };
    let mut process = Some(RunningProcess { child, stdin, mode, negotiated: false, pending_hello: None, capabilities: BTreeSet::new() });
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
        let process = process.expect("uninstalled process must remain owned");
        match terminate_process(process) {
            Ok(()) => {
                reset_failed_start(&bridge, generation)?;
                return Err(error);
            }
            Err((process, termination_error)) => {
                retain_quarantined_process(&bridge, generation, process)?;
                return Err(format!("{error}; failed to terminate superseded sidecar: {termination_error}"));
            }
        }
    }

    let stdout_app = app.clone();
    let bridge_for_stdout = bridge.clone();
    thread::spawn(move || {
        let mut reader = BufReader::new(stdout);
        loop {
            match read_bounded_line(&mut reader, MAX_JSONL_FRAME_BYTES) {
                Ok(Some(line)) if line.trim().is_empty() => {}
                Ok(Some(line)) => if let Err(error) = emit_backend_line(&stdout_app, &bridge_for_stdout, generation, &line) { emit_backend_event(&stdout_app, BackendEvent::error(error)); },
                Ok(None) => {
                    if let Err(error) = mark_stdout_eof(&bridge_for_stdout, generation) {
                        fail_generation(&bridge_for_stdout, generation, &stdout_app, error);
                    }
                    break;
                }
                Err(error) => {
                    fail_generation(&bridge_for_stdout, generation, &stdout_app, error);
                    break;
                }
            }
        }
    });
    let stderr_app = app.clone();
    let bridge_for_stderr = bridge.clone();
    thread::spawn(move || {
        let mut reader = BufReader::new(stderr);
        loop {
            match read_bounded_line(&mut reader, MAX_STDERR_LINE_BYTES) {
                Ok(Some(line)) if line.trim().is_empty() => {}
                Ok(Some(line)) => eprintln!("python sidecar stderr: {line}"),
                Ok(None) => break,
                Err(error) => {
                    fail_generation(&bridge_for_stderr, generation, &stderr_app, error);
                    break;
                }
            }
        }
    });
    let monitor_app = app;
    thread::spawn(move || monitor_exited_child(&bridge, &monitor_app, generation));
    Ok(())
}

fn read_bounded_line(reader: &mut impl BufRead, maximum: usize) -> Result<Option<String>, String> {
    let mut line = Vec::new();
    loop {
        let buffer = reader.fill_buf().map_err(|error| format!("failed to read python output: {error}"))?;
        if buffer.is_empty() {
            return if line.is_empty() { Ok(None) } else { String::from_utf8(line).map(Some).map_err(|_| "python output was not valid UTF-8".to_string()) };
        }
        let take = buffer.iter().position(|byte| *byte == b'\n').map(|index| index + 1).unwrap_or(buffer.len());
        if line.len().saturating_add(take) > maximum {
            reader.consume(take);
            return Err(format!("python output frame exceeds the {} byte limit", maximum));
        }
        line.extend_from_slice(&buffer[..take]);
        reader.consume(take);
        if line.ends_with(b"\n") {
            line.pop();
            if line.ends_with(b"\r") { line.pop(); }
            return String::from_utf8(line).map(Some).map_err(|_| "python output was not valid UTF-8".to_string());
        }
    }
}

fn fail_start_with_child(bridge: &ScientificBridge, generation: u64, mut child: Child, message: &str) -> Result<(), String> {
    let _ = child.kill(); let _ = child.wait(); reset_failed_start(bridge, generation)?; Err(message.to_string())
}
fn reset_failed_start(bridge: &ScientificBridge, generation: u64) -> Result<(), String> { let mut state = bridge.state.lock().map_err(lock_error)?; state.reset_start(generation); Ok(()) }
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


fn retain_termination_failure<T>(owned: T, error: String) -> Result<(), (T, String)> {
    Err((owned, error))
}

fn terminate_process(mut process: RunningProcess) -> Result<(), (RunningProcess, String)> {
    match process.child.try_wait() {
        Ok(Some(_)) => return Ok(()),
        Err(error) => return retain_termination_failure(process, format!("failed to inspect python sidecar: {error}")),
        Ok(None) => {}
    }
    if let Err(error) = process.child.kill() { return retain_termination_failure(process, format!("failed to stop python sidecar: {error}; bridge ownership was retained")); }
    let deadline = Instant::now() + SHUTDOWN_TIMEOUT;
    loop { match process.child.try_wait() {
        Ok(Some(_)) => return Ok(()),
        Ok(None) if Instant::now() < deadline => thread::sleep(MONITOR_INTERVAL),
        Ok(None) => return retain_termination_failure(process, "python sidecar did not stop within two seconds; bridge ownership was retained".to_string()),
        Err(error) => return retain_termination_failure(process, format!("failed while stopping python sidecar: {error}; bridge ownership was retained")),
    }}
}

fn is_negotiated_scientific(bridge: &ScientificBridge) -> Result<bool, String> {
    let state = bridge.state.lock().map_err(lock_error)?;
    if !state.accepts_writes() {
        return Err("python sidecar is not authorized to receive writes".to_string());
    }
    let process = state.process.as_ref().ok_or_else(|| "python sidecar is not running".to_string())?;
    if process.mode != ProcessMode::ScientificV1 {
        return Err("scientific envelopes may only be sent to a ScientificV1 sidecar".to_string());
    }
    Ok(process.negotiated)
}

fn write_legacy_line(bridge: &ScientificBridge, line: &str) -> Result<(), String> {
    let mut state = bridge.state.lock().map_err(lock_error)?;
    if !state.accepts_writes() {
        return Err("python sidecar is not authorized to receive writes".to_string());
    }
    let process = state.process.as_mut().ok_or_else(|| "python sidecar is not running".to_string())?;
    if process.mode != ProcessMode::Legacy {
        return Err("legacy actions may only be sent to a Legacy sidecar".to_string());
    }
    process.stdin.write_all(line.as_bytes()).and_then(|_| process.stdin.flush()).map_err(|error| format!("failed to write backend action: {error}"))
}

fn write_scientific_line(
    bridge: &ScientificBridge,
    envelope: &ScientificEnvelope,
    line: &str,
) -> Result<(), String> {
    let name = envelope.value()["name"]
        .as_str()
        .expect("validated scientific envelope name");
    let message_id = envelope.value()["message_id"]
        .as_str()
        .expect("validated scientific envelope message_id");
    let mut state = bridge.state.lock().map_err(lock_error)?;
    if !state.accepts_writes() {
        return Err("python sidecar is not authorized to receive writes".to_string());
    }
    let process = state.process.as_mut().ok_or_else(|| "python sidecar is not running".to_string())?;
    if process.mode != ProcessMode::ScientificV1 {
        return Err("scientific envelopes may only be sent to a ScientificV1 sidecar".to_string());
    }
    if !action_is_authorized(
        process.negotiated,
        process.pending_hello.is_some(),
        &process.capabilities,
        name,
    ) {
        return Err(format!("scientific action `{name}` is not authorized by the current sidecar capabilities"));
    }
    process
        .stdin
        .write_all(line.as_bytes())
        .and_then(|_| process.stdin.flush())
        .map_err(|error| format!("failed to write backend action: {error}"))?;
    if name == "protocol.hello" {
        process.pending_hello = Some(message_id.to_string());
    }
    Ok(())
}

fn action_is_authorized(
    negotiated: bool,
    hello_pending: bool,
    capabilities: &BTreeSet<String>,
    name: &str,
) -> bool {
    (name == "protocol.hello" && !negotiated && !hello_pending)
        || (negotiated && capabilities.contains(name))
}

fn accept_welcome(
    negotiated: bool,
    pending_hello: Option<&str>,
    correlation_id: &str,
) -> Result<(), String> {
    if negotiated {
        return Err("scientific sidecar replayed protocol.welcome.response".to_string());
    }
    if pending_hello != Some(correlation_id) {
        return Err("scientific welcome does not correlate to the pending protocol.hello".to_string());
    }
    Ok(())
}

#[cfg(test)]
pub(crate) fn action_is_authorized_for_test(
    negotiated: bool,
    hello_pending: bool,
    capabilities: &[&str],
    name: &str,
) -> bool {
    action_is_authorized(
        negotiated,
        hello_pending,
        &capabilities.iter().map(|name| (*name).to_string()).collect(),
        name,
    )
}

#[cfg(test)]
pub(crate) fn accept_welcome_for_test(
    negotiated: bool,
    pending_hello: Option<&str>,
    correlation_id: &str,
) -> Result<(), String> {
    accept_welcome(negotiated, pending_hello, correlation_id)
}

#[cfg(test)]
pub(crate) fn parse_backend_line_for_test(scientific: bool, line: &str) -> Result<(), String> {
    BackendMessage::from_json_line_for_mode(
        line,
        if scientific { BackendMode::ScientificV1 } else { BackendMode::Legacy },
    ).map(|_| ())
}

#[cfg(test)]
pub(crate) fn bounded_line_for_test(input: &[u8], maximum: usize) -> Result<Option<String>, String> {
    read_bounded_line(&mut BufReader::new(input), maximum)
}

fn emit_backend_line(app: &AppHandle, bridge: &ScientificBridge, generation: u64, line: &str) -> Result<(), String> {
    let mode = {
        let state = bridge.state.lock().map_err(lock_error)?;
        if state.phase != BridgePhase::Running || state.generation != generation { return Ok(()); }
        state.process.as_ref().ok_or_else(|| "python bridge running state has no process ownership".to_string())?.mode.backend_mode()
    };
    match BackendMessage::from_json_line_for_mode(line, mode) {
        Ok(BackendMessage::Legacy(event)) => emit_backend_event(app, event),
        Ok(BackendMessage::Scientific(envelope)) => {
            if envelope.is_welcome() {
                match record_welcome(bridge, generation, &envelope) {
                    Ok(false) => return Ok(()),
                    Ok(true) => {}
                    Err(error) => {
                        fail_generation(bridge, generation, app, error);
                        return Ok(());
                    }
                }
            }
            if let Err(error) = app.emit("backend_event", envelope.value()) {
                eprintln!("failed to emit backend_event: {error}");
            }
        }
        Err(error) if mode == BackendMode::ScientificV1 => {
            fail_generation(
                bridge,
                generation,
                app,
                format!("invalid scientific server frame: {error}; line={line}"),
            );
        }
        Err(error) => emit_backend_event(app, BackendEvent::error(format!("invalid backend event JSON: {error}; line={line}"))),
    }
    Ok(())
}

fn record_welcome(
    bridge: &ScientificBridge,
    generation: u64,
    envelope: &ScientificEnvelope,
) -> Result<bool, String> {
    if !envelope.supports_v1() {
        return Err("scientific sidecar returned an incompatible protocol welcome".to_string());
    }
    let capabilities = envelope
        .value()
        .get("payload")
        .and_then(Value::as_object)
        .and_then(|payload| payload.get("capabilities"))
        .and_then(Value::as_array)
        .ok_or_else(|| "scientific sidecar welcome omitted capabilities".to_string())?
        .iter()
        .filter_map(Value::as_str)
        .map(str::to_owned)
        .collect();
    let correlation_id = envelope.value()["correlation_id"]
        .as_str()
        .ok_or_else(|| "scientific welcome must correlate to protocol.hello".to_string())?;
    let mut state = bridge.state.lock().map_err(lock_error)?;
    if state.phase != BridgePhase::Running || state.generation != generation {
        return Ok(false);
    }
    let process = state
        .process
        .as_mut()
        .ok_or_else(|| "python bridge running state has no process ownership".to_string())?;
    if process.mode != ProcessMode::ScientificV1 {
        return Err("legacy sidecar attempted scientific protocol negotiation".to_string());
    }
    accept_welcome(
        process.negotiated,
        process.pending_hello.as_deref(),
        correlation_id,
    )?;
    process.pending_hello = None;
    process.negotiated = true;
    process.capabilities = capabilities;
    Ok(true)
}

fn mark_stdout_eof(bridge: &ScientificBridge, generation: u64) -> Result<(), String> {
    bridge
        .state
        .lock()
        .map_err(lock_error)?
        .mark_stdout_eof(generation)
}
fn fail_generation(bridge: &ScientificBridge, generation: u64, app: &AppHandle, message: String) {
    if quarantine_generation(bridge, generation) {
        if let Err(error) = shutdown_bridge(bridge) {
            emit_backend_event(app, BackendEvent::error(format!("{message}; failed to stop sidecar: {error}")));
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

fn monitor_exited_child(bridge: &ScientificBridge, app: &AppHandle, generation: u64) {
    loop {
        let result = (|| {
            let mut state = bridge.state.lock().map_err(lock_error)?;
            if state.phase != BridgePhase::Running || state.generation != generation { return Ok(None); }
            let stdout_eof = state.stdout_eof;
            let process = state.process.as_mut().ok_or_else(|| "python bridge running state has no process ownership".to_string())?;
            match process.child.try_wait() {
                Ok(Some(status)) if stdout_eof => {
                    state.process = None;
                    state.phase = BridgePhase::Stopped;
                    Ok(Some(status))
                }
                Ok(Some(_)) | Ok(None) => Ok(None),
                Err(error) => Err(format!("failed to check python sidecar: {error}")),
            }
        })();
        match result {
            Ok(Some(status)) => {
                if !status.success() { emit_backend_event(app, BackendEvent::error(format!("python sidecar exited with {status}"))); }
                return;
            }
            Ok(None) => {
                if !is_current_generation(bridge, generation) { return; }
                thread::sleep(MONITOR_INTERVAL);
            }
            Err(error) => {
                fail_generation(bridge, generation, app, error);
                return;
            }
        }
    }
}

fn is_current_generation(bridge: &ScientificBridge, generation: u64) -> bool {
    bridge.state.lock().map(|state| state.phase == BridgePhase::Running && state.generation == generation).unwrap_or(false)
}

fn emit_backend_event(app: &AppHandle, event: BackendEvent) { if let Err(error) = app.emit("backend_event", event) { eprintln!("failed to emit backend_event: {error}"); } }

pub(crate) const SCIENTIFIC_SIDECAR_BASE: &str = "muchanipo-service";
#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
const SCIENTIFIC_TARGET: &str = "aarch64-apple-darwin";
#[cfg(all(target_os = "macos", target_arch = "x86_64"))]
const SCIENTIFIC_TARGET: &str = "x86_64-apple-darwin";
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
const SCIENTIFIC_TARGET: &str = "x86_64-unknown-linux-gnu";
#[cfg(all(target_os = "windows", target_arch = "x86_64"))]
const SCIENTIFIC_TARGET: &str = "x86_64-pc-windows-msvc";
#[cfg(not(any(
    all(target_os = "macos", target_arch = "aarch64"),
    all(target_os = "macos", target_arch = "x86_64"),
    all(target_os = "linux", target_arch = "x86_64"),
    all(target_os = "windows", target_arch = "x86_64"),
)))]
compile_error!("Muchanipo scientific sidecar has no native artifact for this target");

pub(crate) fn scientific_sidecar_name() -> String {
    let suffix = if cfg!(windows) { ".exe" } else { "" };
    format!("{SCIENTIFIC_SIDECAR_BASE}-{SCIENTIFIC_TARGET}{suffix}")
}

pub(crate) fn establish_muchanipo_home(app_data_dir: PathBuf) -> Result<PathBuf, String> {
    fs::create_dir_all(&app_data_dir)
        .map_err(|error| format!("failed to create app-local data directory: {error}"))?;
    let app_data_root = app_data_dir
        .canonicalize()
        .map_err(|error| format!("failed to canonicalize app-local data directory: {error}"))?;
    if !app_data_root.is_dir() {
        return Err("app-local data directory is not a directory".to_string());
    }

    let muchanipo_home = app_data_root.join("muchanipo");
    match fs::symlink_metadata(&muchanipo_home) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            return Err("app-local MUCHANIPO_HOME must not be a symbolic link".to_string());
        }
        Ok(metadata) if !metadata.is_dir() => {
            return Err("app-local MUCHANIPO_HOME is not a directory".to_string());
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            fs::create_dir(&muchanipo_home)
                .map_err(|error| format!("failed to create app-local MUCHANIPO_HOME: {error}"))?;
        }
        Err(error) => {
            return Err(format!("failed to inspect app-local MUCHANIPO_HOME: {error}"));
        }
    }

    let canonical_home = muchanipo_home
        .canonicalize()
        .map_err(|error| format!("failed to canonicalize app-local MUCHANIPO_HOME: {error}"))?;
    if canonical_home.parent() != Some(app_data_root.as_path()) {
        return Err("app-local MUCHANIPO_HOME must be a direct canonical descendant of app data".to_string());
    }
    Ok(canonical_home)
}

fn resolve_sidecar_path(app: &AppHandle) -> Result<PathBuf, String> {
    let resource_dir = app.path().resource_dir().map_err(|error| format!("failed to resolve bundled scientific sidecar: {error}"))?;
    let executable = std::env::current_exe()
        .map_err(|error| format!("failed to resolve bundled scientific sidecar: {error}"))?;
    let executable_dir = executable
        .parent()
        .ok_or_else(|| "bundled scientific sidecar executable has no parent directory".to_string())?;
    resolve_packaged_sidecar_path(&resource_dir, executable_dir)
}

pub(crate) fn resolve_packaged_sidecar_path(resource_dir: &Path, executable_dir: &Path) -> Result<PathBuf, String> {
    let resource_root = resource_dir.canonicalize().map_err(|error| format!("failed to canonicalize bundled resource root: {error}"))?;
    if !resource_root.is_dir() { return Err("bundled resource root is not a directory".to_string()); }
    let sidecar = executable_dir.join(format!("{SCIENTIFIC_SIDECAR_BASE}{}", if cfg!(windows) { ".exe" } else { "" }));
    let metadata = fs::symlink_metadata(&sidecar).map_err(|_| format!("bundled scientific sidecar is missing: {}", sidecar.display()))?;
    if metadata.file_type().is_symlink() { return Err("bundled scientific sidecar must not be a symbolic link".to_string()); }
    if !metadata.is_file() { return Err(format!("bundled scientific sidecar is missing: {}", sidecar.display())); }
    let canonical_sidecar = sidecar.canonicalize().map_err(|error| format!("failed to canonicalize bundled scientific sidecar: {error}"))?;
    verify_sidecar_manifest(&resource_root, &canonical_sidecar, &scientific_sidecar_name())?;
    Ok(canonical_sidecar)
}

fn verify_sidecar_manifest(resource_root: &Path, sidecar: &Path, name: &str) -> Result<(), String> {
    let manifest_path = resource_root.join("binaries").join(format!("{name}.manifest.json"));
    let metadata = fs::symlink_metadata(&manifest_path).map_err(|_| "bundled scientific sidecar manifest is missing".to_string())?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("bundled scientific sidecar manifest must be a regular file".to_string());
    }
    let manifest: Value = serde_json::from_slice(&fs::read(&manifest_path).map_err(|error| format!("failed to read bundled scientific sidecar manifest: {error}"))?)
        .map_err(|error| format!("bundled scientific sidecar manifest is invalid JSON: {error}"))?;
    let expected_name = manifest.get("artifact").and_then(Value::as_str).ok_or_else(|| "bundled scientific sidecar manifest omits artifact".to_string())?;
    let expected_target = manifest.get("target").and_then(Value::as_str).ok_or_else(|| "bundled scientific sidecar manifest omits target".to_string())?;
    let expected_hash = manifest.get("artifact_sha256").and_then(Value::as_str).ok_or_else(|| "bundled scientific sidecar manifest omits artifact SHA-256".to_string())?;
    if expected_name != name || expected_target != SCIENTIFIC_TARGET || !is_sha256(expected_hash) {
        return Err("bundled scientific sidecar manifest does not identify this native artifact".to_string());
    }
    let actual_hash = sha256_file(sidecar)?;
    if actual_hash != expected_hash {
        return Err("bundled scientific sidecar SHA-256 does not match its manifest".to_string());
    }
    Ok(())
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}

fn sha256_file(path: &Path) -> Result<String, String> {
    use std::io::Read;
    let mut file = fs::File::open(path).map_err(|error| format!("failed to open bundled scientific sidecar for hashing: {error}"))?;
    let mut state = Sha256::new();
    let mut buffer = [0_u8; 64 * 1024];
    loop {
        let count = file.read(&mut buffer).map_err(|error| format!("failed to hash bundled scientific sidecar: {error}"))?;
        if count == 0 { break; }
        state.update(&buffer[..count]);
    }
    Ok(state.finish().iter().map(|byte| format!("{byte:02x}")).collect())
}

struct Sha256 { state: [u32; 8], length: u64, buffer: [u8; 64], used: usize }

impl Sha256 {
    fn new() -> Self {
        Self { state: [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19], length: 0, buffer: [0; 64], used: 0 }
    }
    fn update(&mut self, input: &[u8]) {
        self.length = self.length.wrapping_add((input.len() as u64) * 8);
        for &byte in input {
            self.buffer[self.used] = byte;
            self.used += 1;
            if self.used == 64 { self.block(); self.used = 0; }
        }
    }
    fn finish(mut self) -> [u8; 32] {
        let length = self.length;
        self.update(&[0x80]);
        while self.used != 56 { self.update(&[0]); }
        self.buffer[56..].copy_from_slice(&length.to_be_bytes());
        self.block();
        let mut output = [0; 32];
        for (index, word) in self.state.iter().enumerate() { output[index * 4..index * 4 + 4].copy_from_slice(&word.to_be_bytes()); }
        output
    }
    fn block(&mut self) {
        const K: [u32; 64] = [
            0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
            0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
            0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
            0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
        ];
        let mut words = [0u32; 64];
        for (index, chunk) in self.buffer.chunks_exact(4).take(16).enumerate() { words[index] = u32::from_be_bytes(chunk.try_into().expect("SHA-256 block word")); }
        for index in 16..64 {
            let s0 = words[index - 15].rotate_right(7) ^ words[index - 15].rotate_right(18) ^ (words[index - 15] >> 3);
            let s1 = words[index - 2].rotate_right(17) ^ words[index - 2].rotate_right(19) ^ (words[index - 2] >> 10);
            words[index] = words[index - 16].wrapping_add(s0).wrapping_add(words[index - 7]).wrapping_add(s1);
        }
        let [mut a, mut b, mut c, mut d, mut e, mut f, mut g, mut h] = self.state;
        for index in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let choice = (e & f) ^ ((!e) & g);
            let temporary1 = h.wrapping_add(s1).wrapping_add(choice).wrapping_add(K[index]).wrapping_add(words[index]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let majority = (a & b) ^ (a & c) ^ (b & c);
            let temporary2 = s0.wrapping_add(majority);
            h = g; g = f; f = e; e = d.wrapping_add(temporary1); d = c; c = b; b = a; a = temporary1.wrapping_add(temporary2);
        }
        self.state = [
            self.state[0].wrapping_add(a), self.state[1].wrapping_add(b), self.state[2].wrapping_add(c), self.state[3].wrapping_add(d),
            self.state[4].wrapping_add(e), self.state[5].wrapping_add(f), self.state[6].wrapping_add(g), self.state[7].wrapping_add(h),
        ];
    }
}
fn lock_error<T>(error: std::sync::PoisonError<T>) -> String { format!("python bridge state lock poisoned: {error}") }
