use std::{
    fs::{self, OpenOptions},
    io::Write,
    path::{Path, PathBuf},
    process::{Command, ExitStatus},
    thread,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use super::{
    execution_contract::{HandshakeIdentity, LaunchReceipt, ProcessIdentity},
    execution_store::read_json,
};

const HANDSHAKE_TIMEOUT: Duration = Duration::from_secs(5);
const HANDSHAKE_POLL: Duration = Duration::from_millis(20);

pub(super) fn now_unix_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis().min(u128::from(u64::MAX)) as u64)
        .unwrap_or_default()
}

pub(super) fn canonical_executable(path: &str) -> Result<PathBuf, String> {
    fs::canonicalize(path)
        .map_err(|error| format!("failed to canonicalize Python executable {path}: {error}"))
}

pub(super) fn executable_digest(path: &Path) -> Result<String, String> {
    let output = Command::new("/usr/bin/shasum")
        .args(["-a", "256"])
        .arg(path)
        .output()
        .map_err(|error| format!("failed to hash executable {}: {error}", path.display()))?;
    if !output.status.success() {
        return Err(format!(
            "failed to hash executable {}: {}",
            path.display(),
            String::from_utf8_lossy(&output.stderr).trim()
        ));
    }
    String::from_utf8(output.stdout)
        .map_err(|error| format!("executable digest was not UTF-8: {error}"))?
        .split_whitespace()
        .next()
        .filter(|digest| digest.len() == 64)
        .map(ToString::to_string)
        .ok_or_else(|| "executable digest output was malformed".to_string())
}

pub(super) fn owner_boot_id() -> Result<String, String> {
    let output = Command::new("/usr/sbin/sysctl")
        .args(["-n", "kern.boottime"])
        .output()
        .map_err(|error| format!("failed to read owner boot identity: {error}"))?;
    if !output.status.success() {
        return Err("failed to read owner boot identity".to_string());
    }
    let value = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if value.is_empty() {
        Err("owner boot identity was empty".to_string())
    } else {
        Ok(value)
    }
}

#[cfg(unix)]
pub(super) fn configure_process_group(command: &mut Command) {
    use std::os::unix::process::CommandExt;
    command.process_group(0);
}

#[cfg(not(unix))]
pub(super) fn configure_process_group(_command: &mut Command) {}

pub(super) fn handshake_path(receipt: &LaunchReceipt) -> PathBuf {
    receipt.receipt_path.with_extension("handshake.json")
}

pub(super) fn cancel_path(receipt: &LaunchReceipt) -> PathBuf {
    receipt.receipt_path.with_extension("cancel")
}

pub(super) fn finalizer_path(receipt: &LaunchReceipt) -> PathBuf {
    receipt.receipt_path.with_extension("terminal")
}

pub(super) fn await_verified_handshake(
    receipt: &LaunchReceipt,
    pid: u32,
) -> Result<(HandshakeIdentity, ProcessIdentity), String> {
    let path = handshake_path(receipt);
    let deadline = std::time::Instant::now() + HANDSHAKE_TIMEOUT;
    while std::time::Instant::now() < deadline {
        if path.exists() {
            let handshake: HandshakeIdentity = read_json(&path)?;
            let observed = observe_process(pid, receipt)?
                .ok_or_else(|| "child exited before handshake verification".to_string())?;
            return Ok((handshake, observed));
        }
        thread::sleep(HANDSHAKE_POLL);
    }
    Err("timed out waiting for child execution handshake".to_string())
}

pub(super) fn observe_process(
    pid: u32,
    receipt: &LaunchReceipt,
) -> Result<Option<ProcessIdentity>, String> {
    let start = ps_field(pid, "lstart")?;
    let pgid = ps_field(pid, "pgid")?;
    let (Some(process_start_time), Some(pgid)) = (start, pgid) else {
        return Ok(None);
    };
    let pgid = pgid
        .trim()
        .parse::<u32>()
        .map_err(|error| format!("invalid process group for child {pid}: {error}"))?;
    Ok(Some(ProcessIdentity {
        pid,
        process_start_time: process_start_time.trim().to_string(),
        pgid,
        launch_nonce: receipt.launch_nonce.clone(),
        generation: receipt.generation,
        owner_boot_id: receipt.owner_boot_id.clone(),
        executable_digest: receipt.executable_digest.clone(),
    }))
}

fn ps_field(pid: u32, field: &str) -> Result<Option<String>, String> {
    let output = Command::new("/bin/ps")
        .args(["-o", &format!("{field}="), "-p", &pid.to_string()])
        .output()
        .map_err(|error| format!("failed to inspect child {pid}: {error}"))?;
    if !output.status.success() {
        return Ok(None);
    }
    let value = String::from_utf8_lossy(&output.stdout).trim().to_string();
    Ok((!value.is_empty()).then_some(value))
}

pub(super) fn write_cancel_token(path: &Path, receipt: &LaunchReceipt) -> Result<(), String> {
    let mut file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(path)
        .or_else(|error| {
            if error.kind() == std::io::ErrorKind::AlreadyExists {
                OpenOptions::new().write(true).open(path)
            } else {
                Err(error)
            }
        })
        .map_err(|error| format!("failed to create cancellation token: {error}"))?;
    writeln!(
        file,
        "{} {} {}",
        receipt.app_run_id, receipt.generation, receipt.launch_nonce
    )
    .and_then(|_| file.flush())
    .and_then(|_| file.sync_all())
    .map_err(|error| format!("failed to persist cancellation token: {error}"))
}

pub(super) fn signal_verified_process_group(
    identity: &ProcessIdentity,
) -> Result<ExitStatus, String> {
    if identity.pgid == 0 || identity.pgid != identity.pid {
        return Err("refusing to signal an unowned process group".to_string());
    }
    Command::new("/bin/kill")
        .args(["-TERM", &format!("-{}", identity.pgid)])
        .status()
        .map_err(|error| format!("failed to signal owned process group: {error}"))
}
