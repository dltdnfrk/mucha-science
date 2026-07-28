use std::path::PathBuf;

#[derive(Debug, Clone, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum ReceiptPhase {
    Reserved,
    Running,
    CancelRequested,
    Terminal,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum TerminalKind {
    Completed,
    Failed,
    Canceled,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
pub(crate) struct ProcessIdentity {
    pub(crate) pid: u32,
    pub(crate) process_start_time: String,
    pub(crate) pgid: u32,
    pub(crate) launch_nonce: String,
    pub(crate) generation: u64,
    pub(crate) owner_boot_id: String,
    pub(crate) executable_digest: String,
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
pub(crate) struct HandshakeIdentity {
    pub(crate) pid: u32,
    pub(crate) process_start_time: String,
    pub(crate) pgid: u32,
    pub(crate) launch_nonce: String,
    pub(crate) generation: u64,
    pub(crate) owner_boot_id: String,
    pub(crate) executable_digest: String,
}

impl HandshakeIdentity {
    pub(crate) fn from_process(identity: ProcessIdentity) -> Self {
        Self {
            pid: identity.pid,
            process_start_time: identity.process_start_time,
            pgid: identity.pgid,
            launch_nonce: identity.launch_nonce,
            generation: identity.generation,
            owner_boot_id: identity.owner_boot_id,
            executable_digest: identity.executable_digest,
        }
    }

    pub(crate) fn matches_process(&self, identity: &ProcessIdentity) -> bool {
        self.pid == identity.pid
            && self.process_start_time == identity.process_start_time
            && self.pgid == identity.pgid
            && self.launch_nonce == identity.launch_nonce
            && self.generation == identity.generation
            && self.owner_boot_id == identity.owner_boot_id
            && self.executable_digest == identity.executable_digest
    }
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Deserialize, serde::Serialize)]
pub(crate) struct LaunchReceipt {
    pub(crate) app_run_id: String,
    pub(crate) generation: u64,
    pub(crate) launch_nonce: String,
    pub(crate) owner_boot_id: String,
    pub(crate) executable_path: String,
    pub(crate) executable_digest: String,
    pub(crate) reserved_at_unix_ms: u64,
    pub(crate) phase: ReceiptPhase,
    pub(crate) identity: Option<ProcessIdentity>,
    pub(crate) terminal_kind: Option<TerminalKind>,
    pub(crate) termination_observed: bool,
    pub(crate) reaped: bool,
    #[serde(skip)]
    pub(crate) receipt_path: PathBuf,
}

impl LaunchReceipt {
    pub(crate) fn matches_static_identity(&self, identity: &ProcessIdentity) -> bool {
        self.generation == identity.generation
            && self.launch_nonce == identity.launch_nonce
            && self.owner_boot_id == identity.owner_boot_id
            && self.executable_digest == identity.executable_digest
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct LaunchRequest {
    pub(crate) app_run_id: String,
    pub(crate) owner_boot_id: String,
    pub(crate) executable_path: String,
    pub(crate) executable_digest: String,
    pub(crate) now_unix_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum LaunchDecision {
    Spawn(LaunchReceipt),
    Replay(LaunchReceipt),
}

impl LaunchDecision {
    pub(crate) const fn receipt(&self) -> &LaunchReceipt {
        match self {
            Self::Spawn(receipt) | Self::Replay(receipt) => receipt,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum RecoveryDecision {
    ReservedGrace,
    ResumeReserved,
    WaitForHandshake,
    Adopt,
    RejectIdentity,
    TerminalizeLost,
    ReplayTerminal,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) enum CancellationDecision {
    SignalOwnedProcess(ProcessIdentity),
    AwaitTermination,
    AlreadyTerminal(LaunchReceipt),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum EventAdmission {
    Admitted,
    AdmittedTerminal,
    QuarantinedLateGeneration,
    QuarantinedDuplicateTerminal,
}
