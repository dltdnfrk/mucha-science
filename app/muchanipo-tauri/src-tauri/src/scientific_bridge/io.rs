use std::io::{BufRead, BufReader, Write};

use super::{
    protocol::action_is_authorized,
    state::{lock_error, ProcessMode, ScientificBridge},
    ScientificEnvelope,
};

pub(super) const MAX_JSONL_FRAME_BYTES: usize = 64 * 1024;
pub(super) const MAX_STDERR_LINE_BYTES: usize = 16 * 1024;

pub(super) fn read_bounded_line(
    reader: &mut impl BufRead,
    maximum: usize,
) -> Result<Option<String>, String> {
    let mut line = Vec::new();
    loop {
        let buffer = reader
            .fill_buf()
            .map_err(|error| format!("failed to read python output: {error}"))?;
        if buffer.is_empty() {
            return if line.is_empty() {
                Ok(None)
            } else {
                String::from_utf8(line)
                    .map(Some)
                    .map_err(|_| "python output was not valid UTF-8".to_string())
            };
        }
        let take = buffer
            .iter()
            .position(|byte| *byte == b'\n')
            .map_or(buffer.len(), |index| index + 1);
        if line.len().saturating_add(take) > maximum {
            reader.consume(take);
            return Err(format!(
                "python output frame exceeds the {maximum} byte limit"
            ));
        }
        line.extend_from_slice(&buffer[..take]);
        reader.consume(take);
        if line.ends_with(b"\n") {
            line.pop();
            if line.ends_with(b"\r") {
                line.pop();
            }
            return String::from_utf8(line)
                .map(Some)
                .map_err(|_| "python output was not valid UTF-8".to_string());
        }
    }
}

pub(super) fn write_legacy_line(bridge: &ScientificBridge, line: &str) -> Result<(), String> {
    let mut state = bridge.state.lock().map_err(lock_error)?;
    if !state.accepts_writes() {
        return Err("python sidecar is not authorized to receive writes".to_string());
    }
    let process = state
        .process
        .as_mut()
        .ok_or_else(|| "python sidecar is not running".to_string())?;
    if process.mode != ProcessMode::Legacy {
        return Err("legacy actions may only be sent to a Legacy sidecar".to_string());
    }
    process
        .stdin
        .write_all(line.as_bytes())
        .and_then(|_| process.stdin.flush())
        .map_err(|error| format!("failed to write backend action: {error}"))
}

pub(super) fn write_scientific_line(
    bridge: &ScientificBridge,
    envelope: &ScientificEnvelope,
    line: &str,
) -> Result<(), String> {
    let name = envelope.value()["name"]
        .as_str()
        .ok_or_else(|| "scientific envelope name must be a nonempty string".to_string())?;
    let message_id = envelope.value()["message_id"]
        .as_str()
        .ok_or_else(|| "scientific envelope message_id must be a nonempty string".to_string())?;
    let mut state = bridge.state.lock().map_err(lock_error)?;
    if !state.accepts_writes() {
        return Err("python sidecar is not authorized to receive writes".to_string());
    }
    let process = state
        .process
        .as_mut()
        .ok_or_else(|| "python sidecar is not running".to_string())?;
    if process.mode != ProcessMode::ScientificV1 {
        return Err("scientific envelopes may only be sent to a ScientificV1 sidecar".to_string());
    }
    if !action_is_authorized(
        process.negotiated,
        process.pending_hello.is_some(),
        &process.capabilities,
        name,
    ) {
        return Err(format!(
            "scientific action `{name}` is not authorized by the current sidecar capabilities"
        ));
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

#[cfg(test)]
pub(crate) fn bounded_line_for_test(
    input: &[u8],
    maximum: usize,
) -> Result<Option<String>, String> {
    read_bounded_line(&mut BufReader::new(input), maximum)
}
