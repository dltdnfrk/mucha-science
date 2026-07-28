use super::{
    execution_contract::{
        HandshakeIdentity, LaunchReceipt, ProcessIdentity, ReceiptPhase, RecoveryDecision,
    },
    execution_owner::ExecutionOwner,
};

const RESERVED_GRACE_MS: u64 = 5_000;

impl ExecutionOwner {
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
}
