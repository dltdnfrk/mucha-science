use std::{
    collections::BTreeSet,
    process::{Child, ChildStdin},
    sync::{Arc, Mutex},
};

use super::BackendMode;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum BridgePhase {
    Stopped,
    Starting,
    Running,
    Stopping,
    Quarantined,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum ProcessMode {
    Legacy,
    ScientificV1,
}

impl ProcessMode {
    pub(super) const fn backend_mode(self) -> BackendMode {
        match self {
            Self::Legacy => BackendMode::Legacy,
            Self::ScientificV1 => BackendMode::ScientificV1,
        }
    }
}

pub(super) struct RunningProcess {
    pub(super) child: Child,
    pub(super) stdin: ChildStdin,
    pub(super) mode: ProcessMode,
    pub(super) negotiated: bool,
    pub(super) pending_hello: Option<String>,
    pub(super) capabilities: BTreeSet<String>,
}

pub(super) struct BridgeState {
    pub(super) generation: u64,
    pub(super) phase: BridgePhase,
    pub(super) stdout_eof: bool,
    pub(super) process: Option<RunningProcess>,
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
    pub(super) fn reserve_start(&mut self) -> Result<u64, String> {
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
            BridgePhase::Quarantined => Err(
                "python sidecar cleanup must complete before starting another sidecar".to_string(),
            ),
        }
    }

    pub(super) fn reset_start(&mut self, generation: u64) {
        if self.generation == generation
            && matches!(self.phase, BridgePhase::Starting | BridgePhase::Stopping)
            && self.process.is_none()
        {
            self.phase = BridgePhase::Stopped;
            self.stdout_eof = false;
        }
    }

    pub(super) fn quarantine(&mut self, generation: u64) -> bool {
        if self.phase == BridgePhase::Running && self.generation == generation {
            self.phase = BridgePhase::Quarantined;
            true
        } else {
            false
        }
    }

    pub(super) fn accepts_writes(&self) -> bool {
        self.phase == BridgePhase::Running
    }

    pub(super) fn mark_stdout_eof(&mut self, generation: u64) -> Result<(), String> {
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
            Err(error) => Err(format!(
                "failed to inspect python sidecar after stdout closed: {error}"
            )),
        }
    }
}

#[derive(Clone, Default)]
pub struct ScientificBridge {
    pub(super) state: Arc<Mutex<BridgeState>>,
}

pub(super) fn lock_error<T>(error: std::sync::PoisonError<T>) -> String {
    format!("python bridge state lock poisoned: {error}")
}

#[cfg(test)]
impl ScientificBridge {
    pub(crate) fn reserve_start_for_test(&self) -> Result<u64, String> {
        self.state.lock().map_err(lock_error)?.reserve_start()
    }

    pub(crate) fn reset_start_for_test(&self, generation: u64) -> Result<(), String> {
        self.state
            .lock()
            .map_err(lock_error)?
            .reset_start(generation);
        Ok(())
    }

    pub(crate) fn lifecycle_for_test(&self) -> Result<(BridgePhase, u64), String> {
        let state = self.state.lock().map_err(lock_error)?;
        Ok((state.phase, state.generation))
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
        use std::process::{Command, Stdio};

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
        super::io::write_legacy_line(self, "{\"event\":\"test\"}\n")
    }
}
