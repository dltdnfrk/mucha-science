use tauri::State;

use super::{
    backend_events::backend_line_matches_app_run_id,
    state::{lock_error, PythonBridge},
};

#[tauri::command]
pub async fn get_buffered_events(
    app_run_id: Option<String>,
    bridge: State<'_, PythonBridge>,
) -> Result<Vec<String>, String> {
    let buffer = bridge.event_buffer.lock().map_err(lock_error)?;
    let Some(app_run_id) = app_run_id
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
    else {
        return Ok(buffer.clone());
    };
    Ok(buffer
        .iter()
        .filter(|line| backend_line_matches_app_run_id(line, &app_run_id))
        .cloned()
        .collect())
}

pub(super) fn should_buffer_backend_line(line: &str) -> bool {
    !line.contains("\"event\":\"council_persona_token\"")
        && !line.contains("\"event\": \"council_persona_token\"")
        && !line.contains("\"event\":\"pipeline_heartbeat\"")
        && !line.contains("\"event\": \"pipeline_heartbeat\"")
}

#[cfg(test)]
mod tests {
    use super::should_buffer_backend_line;

    #[test]
    fn replay_buffer_skips_live_only_events() {
        assert!(!should_buffer_backend_line(
            r#"{"event":"council_persona_token","delta":"x"}"#
        ));
        assert!(!should_buffer_backend_line(
            r#"{"event":"pipeline_heartbeat","stage":"research"}"#
        ));
        assert!(should_buffer_backend_line(
            r#"{"event":"final_report","markdown":"done"}"#
        ));
    }
}
