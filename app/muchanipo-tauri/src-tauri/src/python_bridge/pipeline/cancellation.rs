use tauri::{AppHandle, State};

use crate::events::BackendEvent;

use super::super::{
    backend_events::{emit_backend_event, with_app_run_id},
    state::{
        cancel_path, observe_process, terminate_verified_process_group, write_cancel_token,
        CancellationDecision, LaunchReceipt, PythonBridge, TerminationAcknowledgement,
    },
};

#[tauri::command]
pub async fn cancel_pipeline(
    app_run_id: String,
    generation: u64,
    app: AppHandle,
    bridge: State<'_, PythonBridge>,
) -> Result<serde_json::Value, String> {
    let mut execution = bridge
        .execution
        .lock()
        .map_err(super::super::state::lock_error)?;
    let receipt = execution
        .runtime
        .as_ref()
        .map(|runtime| runtime.receipt.clone())
        .or_else(|| {
            execution
                .owner
                .as_ref()
                .and_then(|owner| owner.current_receipt().cloned())
        })
        .filter(|receipt| receipt.app_run_id == app_run_id && receipt.generation == generation)
        .ok_or_else(|| "execution generation is not active".to_string())?;
    let expected = receipt
        .identity
        .as_ref()
        .ok_or_else(|| "execution has no verified process identity".to_string())?;
    let observed = observe_process(expected.pid, &receipt)?;
    let decision = execution
        .owner
        .as_mut()
        .ok_or_else(|| "execution owner is unavailable".to_string())?
        .request_cancel(&app_run_id, generation, observed.as_ref())?;
    let acknowledgement = match decision {
        CancellationDecision::SignalOwnedProcess(identity) => {
            write_cancel_token(&cancel_path(&receipt), &receipt)?;
            drop(execution);
            let termination =
                terminate_verified_process_group(&identity, std::time::Duration::from_secs(2))?;
            let mut execution = bridge
                .execution
                .lock()
                .map_err(super::super::state::lock_error)?;
            let terminal = execution
                .owner
                .as_mut()
                .ok_or_else(|| "execution owner is unavailable".to_string())?
                .observe_termination(&app_run_id, generation, true)?;
            let mut acknowledgement =
                TerminationAcknowledgement::from_reaped_receipt(&terminal)?;
            acknowledgement.kill_sent = termination.kill_sent;
            Ok(acknowledgement)
        }
        CancellationDecision::AwaitTermination => {
            drop(execution);
            let terminal = await_terminal_receipt(bridge.inner(), &app_run_id, generation)?;
            TerminationAcknowledgement::from_reaped_receipt(&terminal)
        }
        CancellationDecision::AlreadyTerminal(receipt) => {
            TerminationAcknowledgement::from_reaped_receipt(&receipt)
        }
    }?;
    emit_cancellation_event(&app, &acknowledgement);
    serde_json::to_value(acknowledgement)
        .map_err(|error| format!("failed to encode cancellation acknowledgement: {error}"))
}

fn await_terminal_receipt(
    bridge: &PythonBridge,
    app_run_id: &str,
    generation: u64,
) -> Result<LaunchReceipt, String> {
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(8);
    while std::time::Instant::now() < deadline {
        let receipt = bridge
            .execution
            .lock()
            .map_err(super::super::state::lock_error)?
            .owner
            .as_ref()
            .and_then(|owner| owner.current_receipt().cloned());
        if let Some(receipt) = receipt.filter(|receipt| {
            receipt.app_run_id == app_run_id
                && receipt.generation == generation
                && receipt.termination_observed
                && receipt.reaped
        }) {
            return Ok(receipt);
        }
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
    Err("timed out waiting for verified execution reap".to_string())
}

fn emit_cancellation_event(app: &AppHandle, acknowledgement: &TerminationAcknowledgement) {
    let mut fields = serde_json::Map::new();
    fields.insert(
        "generation".to_string(),
        serde_json::Value::Number(acknowledgement.generation.into()),
    );
    fields.insert(
        "termination_observed".to_string(),
        serde_json::Value::Bool(acknowledgement.termination_observed),
    );
    fields.insert(
        "reaped".to_string(),
        serde_json::Value::Bool(acknowledgement.reaped),
    );
    emit_backend_event(
        app,
        with_app_run_id(
            BackendEvent {
                event: "execution_cancelled".to_string(),
                fields,
            },
            &acknowledgement.app_run_id,
        ),
    );
}
