use std::collections::BTreeSet;

use tauri::{AppHandle, Emitter};

use super::{
    monitor::{emit_backend_event, fail_generation},
    state::{lock_error, ProcessMode, ScientificBridge},
    BackendEvent, BackendMessage, BackendMode, ScientificEnvelope,
};

pub(super) fn is_negotiated_scientific(
    bridge: &ScientificBridge,
) -> Result<bool, String> {
    let state = bridge.state.lock().map_err(lock_error)?;
    if !state.accepts_writes() {
        return Err("python sidecar is not authorized to receive writes".to_string());
    }
    let process = state
        .process
        .as_ref()
        .ok_or_else(|| "python sidecar is not running".to_string())?;
    if process.mode != ProcessMode::ScientificV1 {
        return Err("scientific envelopes may only be sent to a ScientificV1 sidecar".to_string());
    }
    Ok(process.negotiated)
}

pub(super) fn action_is_authorized(
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
        return Err(
            "scientific welcome does not correlate to the pending protocol.hello".to_string(),
        );
    }
    Ok(())
}

pub(super) fn emit_backend_line(
    app: &AppHandle,
    bridge: &ScientificBridge,
    generation: u64,
    line: &str,
) -> Result<(), String> {
    let mode = {
        let state = bridge.state.lock().map_err(lock_error)?;
        if !is_running_generation(&state, generation) {
            return Ok(());
        }
        state
            .process
            .as_ref()
            .ok_or_else(|| "python bridge running state has no process ownership".to_string())?
            .mode
            .backend_mode()
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
        Err(error) if mode == BackendMode::ScientificV1 => fail_generation(
            bridge,
            generation,
            app,
            format!("invalid scientific server frame: {error}; line={line}"),
        ),
        Err(error) => emit_backend_event(
            app,
            BackendEvent::error(format!("invalid backend event JSON: {error}; line={line}")),
        ),
    }
    Ok(())
}

fn is_running_generation(
    state: &super::state::BridgeState,
    generation: u64,
) -> bool {
    state.phase == super::BridgePhase::Running && state.generation == generation
}

fn record_welcome(
    bridge: &ScientificBridge,
    generation: u64,
    envelope: &ScientificEnvelope,
) -> Result<bool, String> {
    let capabilities = envelope
        .welcome_capabilities()
        .ok_or_else(|| "scientific sidecar returned an incompatible protocol welcome".to_string())?
        .into_iter()
        .collect();
    let correlation_id = envelope.value()["correlation_id"]
        .as_str()
        .ok_or_else(|| "scientific welcome must correlate to protocol.hello".to_string())?;
    let mut state = bridge.state.lock().map_err(lock_error)?;
    if !is_running_generation(&state, generation) {
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
        &capabilities
            .iter()
            .map(|name| (*name).to_string())
            .collect(),
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
pub(crate) fn parse_backend_line_for_test(
    scientific: bool,
    line: &str,
) -> Result<(), String> {
    BackendMessage::from_json_line_for_mode(
        line,
        if scientific {
            BackendMode::ScientificV1
        } else {
            BackendMode::Legacy
        },
    )
    .map(|_| ())
}
