use std::{
    io::{BufRead, BufReader, Write},
    process::{ChildStderr, ChildStdout},
    thread,
};

use tauri::AppHandle;

use crate::events::BackendEvent;

use super::super::{
    backend_events::{
        emit_backend_event, emit_backend_line, stderr_line_to_backend_event, with_app_run_id,
    },
    logging::{open_run_log, stderr_log_path_for_app_run_id, stdout_log_path_for_app_run_id},
    replay::should_buffer_backend_line,
    state::{mark_backend_event_seen, push_event_buffer, PythonBridge},
};

pub(super) struct OutputReaders {
    pub(super) app: AppHandle,
    pub(super) bridge: PythonBridge,
    pub(super) stdout: ChildStdout,
    pub(super) stderr: ChildStderr,
    pub(super) app_run_id: String,
}

struct StdoutReader {
    app: AppHandle,
    bridge: PythonBridge,
    stdout: ChildStdout,
    app_run_id: String,
}

struct StderrReader {
    app: AppHandle,
    stderr: ChildStderr,
    app_run_id: String,
}

pub(super) fn spawn_output_readers(readers: OutputReaders) {
    let stdout_reader = StdoutReader {
        app: readers.app.clone(),
        bridge: readers.bridge,
        stdout: readers.stdout,
        app_run_id: readers.app_run_id.clone(),
    };
    let stderr_reader = StderrReader {
        app: readers.app,
        stderr: readers.stderr,
        app_run_id: readers.app_run_id,
    };
    thread::spawn(move || read_stdout(stdout_reader));
    thread::spawn(move || read_stderr(stderr_reader));
}

fn read_stdout(reader: StdoutReader) {
    let log_path = stdout_log_path_for_app_run_id(&reader.app_run_id);
    let mut log = open_run_log(&log_path, &reader.app_run_id);
    for line in BufReader::new(reader.stdout).lines() {
        match line {
            Ok(line) if line.trim().is_empty() => {}
            Ok(line) => {
                if let Some(ref mut file) = log {
                    let _ = writeln!(file, "{line}");
                }
                mark_backend_event_seen(&reader.bridge);
                if let Some(tagged_line) = emit_backend_line(&reader.app, &line, &reader.app_run_id)
                {
                    if should_buffer_backend_line(&line) {
                        push_event_buffer(&reader.bridge, &tagged_line);
                    }
                }
            }
            Err(error) => emit_backend_event(
                &reader.app,
                with_app_run_id(
                    BackendEvent::error(format!("failed to read python stdout: {error}")),
                    &reader.app_run_id,
                ),
            ),
        }
    }
}

fn read_stderr(reader: StderrReader) {
    let log_path = stderr_log_path_for_app_run_id(&reader.app_run_id);
    let mut log = open_run_log(&log_path, &reader.app_run_id);
    for line in BufReader::new(reader.stderr).lines() {
        match line {
            Ok(line) if line.trim().is_empty() => {}
            Ok(line) => {
                if let Some(ref mut file) = log {
                    let _ = writeln!(file, "{line}");
                }
                emit_backend_event(
                    &reader.app,
                    with_app_run_id(stderr_line_to_backend_event(&line), &reader.app_run_id),
                );
            }
            Err(error) => emit_backend_event(
                &reader.app,
                with_app_run_id(
                    BackendEvent::error(format!("failed to read python stderr: {error}")),
                    &reader.app_run_id,
                ),
            ),
        }
    }
}
