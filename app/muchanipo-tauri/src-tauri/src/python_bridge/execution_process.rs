use std::{
    path::PathBuf,
    process::{Command, ExitStatus},
    thread,
    time::Duration,
};

use super::{
    execution_contract::{LaunchReceipt, ProcessIdentity, TerminationAcknowledgement},
    execution_platform::{canonical_executable, executable_digest},
};

const PROCESS_POLL: Duration = Duration::from_millis(20);

pub(crate) fn observe_process(
    pid: u32,
    receipt: &LaunchReceipt,
) -> Result<Option<ProcessIdentity>, String> {
    let Some(observed) = inspect_process(pid)? else {
        return Ok(None);
    };
    Ok(Some(ProcessIdentity {
        pid,
        process_start_time: observed.process_start_time,
        pgid: observed.pgid,
        launch_nonce: receipt.launch_nonce.clone(),
        generation: receipt.generation,
        owner_boot_id: receipt.owner_boot_id.clone(),
        executable_digest: observed.executable_digest,
    }))
}

pub(crate) fn find_owned_process(
    receipt: &LaunchReceipt,
) -> Result<Option<ProcessIdentity>, String> {
    let output = Command::new("/bin/ps")
        .args(["-axo", "pid=,pgid=,comm="])
        .output()
        .map_err(|error| format!("failed to scan execution processes: {error}"))?;
    if !output.status.success() {
        return Err("failed to prove execution process absence".to_string());
    }
    let listing = String::from_utf8_lossy(&output.stdout);
    for line in listing.lines() {
        let mut fields = line.split_whitespace();
        let Some(pid) = fields.next().and_then(|value| value.parse::<u32>().ok()) else {
            continue;
        };
        let Some(pgid) = fields.next().and_then(|value| value.parse::<u32>().ok()) else {
            continue;
        };
        if pid != pgid {
            continue;
        }
        let Some(executable) = fields.next() else {
            continue;
        };
        let Ok(executable) = canonical_executable(executable) else {
            continue;
        };
        if executable != PathBuf::from(&receipt.executable_path) {
            continue;
        }
        if executable_digest(&executable)? != receipt.executable_digest {
            continue;
        }
        let Some(identity) = observe_process(pid, receipt)? else {
            continue;
        };
        if receipt.matches_static_identity(&identity) && identity.pgid == identity.pid {
            return Ok(Some(identity));
        }
    }
    Ok(None)
}

pub(crate) fn process_matches_identity(identity: &ProcessIdentity) -> Result<bool, String> {
    let Some(observed) = inspect_process(identity.pid)? else {
        return Ok(false);
    };
    Ok(observed.process_start_time == identity.process_start_time
        && observed.pgid == identity.pgid
        && observed.executable_digest == identity.executable_digest)
}

pub(crate) fn wait_for_adopted_process(identity: &ProcessIdentity) -> Result<(), String> {
    loop {
        match inspect_process(identity.pid)? {
            Some(_) if !process_matches_identity(identity)? => {
                return Err("adopted process identity was replaced".to_string())
            }
            Some(_) => thread::sleep(PROCESS_POLL),
            None if process_group_exists(identity.pgid)? => thread::sleep(PROCESS_POLL),
            None => return Ok(()),
        }
    }
}

pub(crate) fn signal_verified_process_group(
    identity: &ProcessIdentity,
) -> Result<ExitStatus, String> {
    signal_process_group(identity, "-TERM")
}

pub(crate) fn kill_verified_process_group(
    identity: &ProcessIdentity,
) -> Result<ExitStatus, String> {
    signal_process_group(identity, "-KILL")
}

pub(crate) fn terminate_verified_process_group(
    identity: &ProcessIdentity,
    grace: Duration,
) -> Result<TerminationAcknowledgement, String> {
    if !process_matches_identity(identity)? {
        return Err("refusing to terminate a replaced process identity".to_string());
    }
    let status = signal_verified_process_group(identity)?;
    if !status.success() {
        return Err(format!("owned process-group TERM failed with {status}"));
    }
    if wait_for_process_group_exit(identity.pgid, grace)? {
        return Ok(termination_acknowledgement(identity, false));
    }
    let status = kill_verified_process_group(identity)?;
    if !status.success() {
        return Err(format!("owned process-group KILL failed with {status}"));
    }
    if !wait_for_process_group_exit(identity.pgid, Duration::from_secs(5))? {
        return Err("owned process group remained after KILL".to_string());
    }
    Ok(termination_acknowledgement(identity, true))
}

fn termination_acknowledgement(
    identity: &ProcessIdentity,
    kill_sent: bool,
) -> TerminationAcknowledgement {
    TerminationAcknowledgement {
        acknowledged: true,
        app_run_id: String::new(),
        generation: identity.generation,
        termination_observed: true,
        reaped: true,
        kill_sent,
    }
}

fn wait_for_process_group_exit(pgid: u32, timeout: Duration) -> Result<bool, String> {
    let deadline = std::time::Instant::now() + timeout;
    while std::time::Instant::now() < deadline {
        if !process_group_exists(pgid)? {
            return Ok(true);
        }
        thread::sleep(PROCESS_POLL);
    }
    Ok(!process_group_exists(pgid)?)
}

fn process_group_exists(pgid: u32) -> Result<bool, String> {
    let status = Command::new("/bin/kill")
        .args(["-0", "--", &format!("-{pgid}")])
        .stderr(std::process::Stdio::null())
        .status()
        .map_err(|error| format!("failed to inspect owned process group: {error}"))?;
    Ok(status.success())
}

fn signal_process_group(identity: &ProcessIdentity, signal: &str) -> Result<ExitStatus, String> {
    if identity.pgid == 0 || identity.pgid != identity.pid {
        return Err("refusing to signal an unowned process group".to_string());
    }
    Command::new("/bin/kill")
        .args([signal, "--", &format!("-{}", identity.pgid)])
        .status()
        .map_err(|error| format!("failed to signal owned process group: {error}"))
}

struct ObservedProcess {
    process_start_time: String,
    pgid: u32,
    executable_digest: String,
}

fn inspect_process(pid: u32) -> Result<Option<ObservedProcess>, String> {
    let start = ps_field(pid, "lstart")?;
    let pgid = ps_field(pid, "pgid")?;
    let executable = ps_field(pid, "comm")?;
    let (Some(process_start_time), Some(pgid), Some(executable)) = (start, pgid, executable) else {
        return Ok(None);
    };
    let process_start_time = normalize_process_start_time(&process_start_time)?;
    let pgid = pgid
        .trim()
        .parse::<u32>()
        .map_err(|error| format!("invalid process group for child {pid}: {error}"))?;
    let executable = canonical_executable(executable.trim())?;
    Ok(Some(ObservedProcess {
        process_start_time,
        pgid,
        executable_digest: executable_digest(&executable)?,
    }))
}

#[cfg(target_os = "macos")]
fn normalize_process_start_time(value: &str) -> Result<String, String> {
    let output = Command::new("/bin/date")
        .args(["-j", "-f", "%a %b %e %T %Y", value.trim(), "+%s"])
        .output()
        .map_err(|error| format!("failed to normalize process start time: {error}"))?;
    if !output.status.success() {
        return Err("failed to normalize process start time".to_string());
    }
    let normalized = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if normalized.is_empty() {
        Err("normalized process start time was empty".to_string())
    } else {
        Ok(normalized)
    }
}

#[cfg(not(target_os = "macos"))]
fn normalize_process_start_time(value: &str) -> Result<String, String> {
    Ok(value.trim().to_string())
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
