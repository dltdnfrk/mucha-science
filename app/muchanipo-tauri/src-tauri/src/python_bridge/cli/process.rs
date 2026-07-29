use std::{
    io::{Read, Write},
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

use super::path::merged_cli_path;
use crate::python_bridge::workspace::workspace_root;

pub(super) struct CapturedCommand {
    pub(super) success: bool,
    pub(super) code: Option<i32>,
    pub(super) stdout: String,
    pub(super) stderr: String,
    pub(super) timed_out: bool,
}

pub(super) fn run_command_with_timeout(
    bin: &str,
    args: &[&str],
    input: Option<&str>,
    timeout: Duration,
) -> Result<CapturedCommand, std::io::Error> {
    let mut child = Command::new(bin)
        .args(args)
        .current_dir(workspace_root())
        .env("PATH", merged_cli_path())
        .stdin(if input.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()?;

    let stdout_reader = child.stdout.take().map(|mut pipe| {
        thread::spawn(move || {
            let mut output = String::new();
            let _ = pipe.read_to_string(&mut output);
            output
        })
    });
    let stderr_reader = child.stderr.take().map(|mut pipe| {
        thread::spawn(move || {
            let mut output = String::new();
            let _ = pipe.read_to_string(&mut output);
            output
        })
    });

    if let Some(body) = input {
        if let Some(mut stdin) = child.stdin.take() {
            if let Err(error) = stdin.write_all(body.as_bytes()) {
                let _ = child.kill();
                let _ = child.wait();
                return Err(error);
            }
        }
    }

    let started = Instant::now();
    let mut timed_out = false;
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if started.elapsed() >= timeout {
            timed_out = true;
            let _ = child.kill();
            break child.wait()?;
        }
        thread::sleep(Duration::from_millis(50));
    };

    let stdout = stdout_reader
        .and_then(|handle| handle.join().ok())
        .unwrap_or_default();
    let stderr = stderr_reader
        .and_then(|handle| handle.join().ok())
        .unwrap_or_default();

    Ok(CapturedCommand {
        success: status.success() && !timed_out,
        code: status.code(),
        stdout,
        stderr,
        timed_out,
    })
}
