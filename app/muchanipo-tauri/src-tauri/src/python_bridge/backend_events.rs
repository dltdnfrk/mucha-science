use serde_json::Value;
use tauri::{AppHandle, Emitter};

use crate::events::BackendEvent;

pub(super) fn emit_backend_line(
    app: &AppHandle,
    line: &str,
    app_run_id: &str,
) -> Option<String> {
    match BackendEvent::from_json_line(line) {
        Ok(event) => {
            let event = with_app_run_id(event, app_run_id);
            let tagged_line = serde_json::to_string(&event).ok();
            emit_backend_event(app, event);
            tagged_line
        }
        Err(error) => {
            emit_backend_event(
                app,
                with_app_run_id(
                    BackendEvent::warning(format!(
                        "invalid backend event JSON: {error}; line={line}"
                    )),
                    app_run_id,
                ),
            );
            None
        }
    }
}

pub(super) fn emit_backend_event(app: &AppHandle, event: BackendEvent) {
    if let Err(error) = app.emit("backend_event", event) {
        eprintln!("failed to emit backend_event: {error}");
    }
}

pub(super) fn with_app_run_id(
    mut event: BackendEvent,
    app_run_id: &str,
) -> BackendEvent {
    if !app_run_id.trim().is_empty() {
        event.fields.insert(
            "app_run_id".to_string(),
            Value::String(app_run_id.to_string()),
        );
    }
    event
}

pub(super) fn backend_line_matches_app_run_id(line: &str, app_run_id: &str) -> bool {
    BackendEvent::from_json_line(line)
        .ok()
        .and_then(|event| {
            event
                .fields
                .get("app_run_id")
                .and_then(|value| value.as_str())
                .map(str::to_string)
        })
        .as_deref()
        == Some(app_run_id)
}

pub(super) fn stderr_line_to_backend_event(line: &str) -> BackendEvent {
    if line.starts_with("muchanipo provider_call_start ") {
        let mut fields = serde_json::Map::new();
        fields.insert("message".to_string(), Value::String(line.to_string()));
        fields.insert(
            "source".to_string(),
            Value::String("python_stderr".to_string()),
        );
        return BackendEvent {
            event: "provider_activity".to_string(),
            fields,
        };
    }
    BackendEvent::warning(format!("python stderr: {line}"))
}

pub(super) fn normalize_app_run_id(value: Option<&str>) -> String {
    value
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(ToString::to_string)
        .unwrap_or_else(|| {
            let millis = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map(|duration| duration.as_millis())
                .unwrap_or_default();
            format!("run-tauri-{millis}")
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backend_warning_event_shape_is_non_fatal() {
        let event = BackendEvent::warning("heads up");
        assert_eq!(event.event, "warning");
        assert_eq!(
            event.fields.get("message").and_then(|value| value.as_str()),
            Some("heads up")
        );
    }

    #[test]
    fn app_run_id_is_injected_without_overwriting_backend_run_id() {
        let event = BackendEvent::from_json_line(
            r#"{"event":"run_started","run_id":"python-run","stage":"intake"}"#,
        )
        .expect("valid backend event");
        let event = with_app_run_id(event, "run-ui-123");
        assert_eq!(
            event.fields.get("run_id").and_then(|value| value.as_str()),
            Some("python-run")
        );
        assert_eq!(
            event
                .fields
                .get("app_run_id")
                .and_then(|value| value.as_str()),
            Some("run-ui-123")
        );
    }
}
