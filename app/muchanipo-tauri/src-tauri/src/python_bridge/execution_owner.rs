use std::{
    fs,
    path::{Path, PathBuf},
};

use super::{
    execution_contract::{
        CancellationDecision, EventAdmission, HandshakeIdentity, LaunchDecision, LaunchReceipt,
        LaunchRequest, ProcessIdentity, ReceiptPhase, RecoveryDecision, TerminalKind,
    },
    execution_store::{read_json, write_json_fsync},
};

const RESERVED_GRACE_MS: u64 = 5_000;

pub(crate) struct ExecutionOwner {
    root: PathBuf,
    generation: u64,
    current: Option<LaunchReceipt>,
    cancel_requested: bool,
    terminal_event_claimed: bool,
}

impl ExecutionOwner {
    pub(crate) fn open(root: PathBuf) -> Result<Self, String> {
        fs::create_dir_all(&root).map_err(|error| {
            format!(
                "failed to create execution owner directory {}: {error}",
                root.display()
            )
        })?;
        let generation_path = root.join("generation.json");
        let generation = if generation_path.exists() {
            read_json::<u64>(&generation_path)?
        } else {
            0
        };
        Ok(Self {
            root,
            generation,
            current: None,
            cancel_requested: false,
            terminal_event_claimed: false,
        })
    }

    pub(crate) fn reserve_launch(
        &mut self,
        request: LaunchRequest,
    ) -> Result<LaunchDecision, String> {
        let receipt_path = self.receipt_path(&request.app_run_id);
        if receipt_path.exists() {
            let mut receipt: LaunchReceipt = read_json(&receipt_path)?;
            receipt.receipt_path = receipt_path;
            self.generation = self.generation.max(receipt.generation);
            self.current = Some(receipt.clone());
            self.cancel_requested = receipt.phase == ReceiptPhase::CancelRequested;
            return Ok(LaunchDecision::Replay(receipt));
        }
        if self
            .current
            .as_ref()
            .is_some_and(|receipt| receipt.phase != ReceiptPhase::Terminal)
        {
            return Err("another execution generation is still active".to_string());
        }

        self.generation = self
            .generation
            .checked_add(1)
            .ok_or_else(|| "execution generation exhausted".to_string())?;
        let receipt = LaunchReceipt {
            app_run_id: request.app_run_id,
            generation: self.generation,
            launch_nonce: format!(
                "{}-{}-{}",
                std::process::id(),
                request.now_unix_ms,
                self.generation
            ),
            owner_boot_id: request.owner_boot_id,
            executable_path: request.executable_path,
            executable_digest: request.executable_digest,
            reserved_at_unix_ms: request.now_unix_ms,
            phase: ReceiptPhase::Reserved,
            identity: None,
            terminal_kind: None,
            termination_observed: false,
            reaped: false,
            receipt_path,
        };
        self.persist(&receipt)?;
        write_json_fsync(&self.root.join("generation.json"), &self.generation)?;
        self.current = Some(receipt.clone());
        self.cancel_requested = false;
        self.terminal_event_claimed = false;
        Ok(LaunchDecision::Spawn(receipt))
    }

    pub(crate) fn record_handshake(
        &mut self,
        receipt: &LaunchReceipt,
        handshake: &HandshakeIdentity,
        observed: &ProcessIdentity,
    ) -> Result<LaunchReceipt, String> {
        if !receipt.matches_static_identity(observed)
            || !handshake.matches_process(observed)
            || receipt.app_run_id
                != self
                    .current
                    .as_ref()
                    .map(|current| current.app_run_id.as_str())
                    .unwrap_or_default()
        {
            return Err("child handshake identity does not match reserved execution".to_string());
        }
        let mut running = receipt.clone();
        running.phase = ReceiptPhase::Running;
        running.identity = Some(observed.clone());
        self.persist(&running)?;
        self.current = Some(running.clone());
        Ok(running)
    }

    pub(crate) fn recover(
        &self,
        receipt: &LaunchReceipt,
        handshake: Option<&HandshakeIdentity>,
        observed: Option<&ProcessIdentity>,
        now_unix_ms: u64,
    ) -> Result<RecoveryDecision, String> {
        let effective = self.current.as_ref().filter(|current| {
            current.app_run_id == receipt.app_run_id && current.generation == receipt.generation
        });
        if effective.is_some_and(|current| current.phase == ReceiptPhase::Terminal) {
            return Ok(RecoveryDecision::ReplayTerminal);
        }
        match (handshake, observed) {
            (Some(child), Some(process))
                if receipt.matches_static_identity(process) && child.matches_process(process) =>
            {
                Ok(RecoveryDecision::Adopt)
            }
            (Some(_), Some(_)) | (None, Some(_)) => {
                if handshake.is_none()
                    && observed.is_some_and(|process| receipt.matches_static_identity(process))
                {
                    Ok(RecoveryDecision::WaitForHandshake)
                } else {
                    Ok(RecoveryDecision::RejectIdentity)
                }
            }
            (Some(_), None) => Ok(RecoveryDecision::TerminalizeLost),
            (None, None)
                if effective.is_some_and(|current| current.phase == ReceiptPhase::Running) =>
            {
                Ok(RecoveryDecision::TerminalizeLost)
            }
            (None, None)
                if now_unix_ms.saturating_sub(receipt.reserved_at_unix_ms)
                    < RESERVED_GRACE_MS =>
            {
                Ok(RecoveryDecision::ReservedGrace)
            }
            (None, None) => Ok(RecoveryDecision::ResumeReserved),
        }
    }

    pub(crate) fn request_cancel(
        &mut self,
        app_run_id: &str,
        generation: u64,
        observed: Option<&ProcessIdentity>,
    ) -> Result<CancellationDecision, String> {
        let current = self.current_mut(app_run_id, generation)?;
        if current.phase == ReceiptPhase::Terminal {
            return Ok(CancellationDecision::AlreadyTerminal(current.clone()));
        }
        if self.cancel_requested || current.phase == ReceiptPhase::CancelRequested {
            return Ok(CancellationDecision::AwaitTermination);
        }
        let expected = current
            .identity
            .as_ref()
            .ok_or_else(|| "active execution has no verified process identity".to_string())?;
        let observed = observed
            .filter(|identity| *identity == expected)
            .ok_or_else(|| "refusing to cancel an unverified process identity".to_string())?
            .clone();
        current.phase = ReceiptPhase::CancelRequested;
        let receipt = current.clone();
        self.persist(&receipt)?;
        self.cancel_requested = true;
        Ok(CancellationDecision::SignalOwnedProcess(observed))
    }

    pub(crate) fn admit_event(
        &mut self,
        app_run_id: &str,
        generation: u64,
        terminal: bool,
    ) -> EventAdmission {
        let Some(current) = self.current.as_ref() else {
            return EventAdmission::QuarantinedLateGeneration;
        };
        if current.app_run_id != app_run_id
            || current.generation != generation
            || current.phase == ReceiptPhase::Terminal
        {
            return EventAdmission::QuarantinedLateGeneration;
        }
        if !terminal {
            return EventAdmission::Admitted;
        }
        if self.terminal_event_claimed {
            return EventAdmission::QuarantinedDuplicateTerminal;
        }
        self.terminal_event_claimed = true;
        EventAdmission::AdmittedTerminal
    }

    pub(crate) fn observe_termination(
        &mut self,
        app_run_id: &str,
        generation: u64,
        reaped: bool,
    ) -> Result<LaunchReceipt, String> {
        self.terminalize(
            app_run_id,
            generation,
            TerminalKind::Canceled,
            true,
            reaped,
        )
    }

    pub(crate) fn terminalize(
        &mut self,
        app_run_id: &str,
        generation: u64,
        kind: TerminalKind,
        termination_observed: bool,
        reaped: bool,
    ) -> Result<LaunchReceipt, String> {
        let current = self.current_mut(app_run_id, generation)?;
        if current.phase == ReceiptPhase::Terminal {
            return Ok(current.clone());
        }
        current.phase = ReceiptPhase::Terminal;
        current.terminal_kind = Some(kind);
        current.termination_observed = termination_observed;
        current.reaped = reaped;
        let receipt = current.clone();
        self.persist(&receipt)?;
        Ok(receipt)
    }

    fn current_mut(
        &mut self,
        app_run_id: &str,
        generation: u64,
    ) -> Result<&mut LaunchReceipt, String> {
        self.current
            .as_mut()
            .filter(|receipt| {
                receipt.app_run_id == app_run_id && receipt.generation == generation
            })
            .ok_or_else(|| "execution generation is not active".to_string())
    }

    fn persist(&self, receipt: &LaunchReceipt) -> Result<(), String> {
        write_json_fsync(&receipt.receipt_path, receipt)
    }

    fn receipt_path(&self, app_run_id: &str) -> PathBuf {
        self.root
            .join(format!("{}.json", safe_file_component(app_run_id)))
    }
}

fn safe_file_component(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '-' | '_') {
                character
            } else {
                '-'
            }
        })
        .collect()
}
