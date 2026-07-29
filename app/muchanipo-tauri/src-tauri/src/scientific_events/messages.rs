use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

use super::{ScientificEnvelope, ENVELOPE_FIELDS};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackendEvent {
    pub event: String,
    #[serde(flatten)]
    pub fields: Map<String, Value>,
}

impl BackendEvent {
    pub fn error(message: impl Into<String>) -> Self {
        let mut fields = Map::new();
        fields.insert("message".to_string(), Value::String(message.into()));
        Self {
            event: "error".to_string(),
            fields,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BackendMode {
    Legacy,
    ScientificV1,
}

#[derive(Debug, Clone)]
pub enum BackendMessage {
    Legacy(BackendEvent),
    Scientific(ScientificEnvelope),
}

impl BackendMessage {
    pub fn from_json_line_for_mode(line: &str, mode: BackendMode) -> Result<Self, String> {
        let value: Value =
            serde_json::from_str(line).map_err(|error| format!("invalid backend JSON: {error}"))?;
        let object = value
            .as_object()
            .ok_or_else(|| "backend message must be a JSON object".to_string())?;
        let contains_envelope_field = ENVELOPE_FIELDS
            .iter()
            .any(|field| object.contains_key(*field));

        match mode {
            BackendMode::Legacy => {
                if contains_envelope_field {
                    return Err(
                        "legacy sidecar emitted a scientific or mixed-protocol frame".to_string(),
                    );
                }
                if !object
                    .get("event")
                    .and_then(Value::as_str)
                    .is_some_and(|event| !event.trim().is_empty())
                {
                    return Err(
                        "legacy backend event must contain a nonempty event discriminator"
                            .to_string(),
                    );
                }
                serde_json::from_value(value)
                    .map(Self::Legacy)
                    .map_err(|error| format!("invalid legacy backend event: {error}"))
            }
            BackendMode::ScientificV1 => {
                if !contains_envelope_field {
                    return Err(
                        "scientific sidecar emitted a legacy or mixed-protocol frame".to_string(),
                    );
                }
                ScientificEnvelope::from_server_value(value).map(Self::Scientific)
            }
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackendAction {
    #[serde(flatten)]
    pub fields: Map<String, Value>,
}

impl BackendAction {
    pub fn into_json_line(mut self) -> Result<String, serde_json::Error> {
        if !self.fields.contains_key("action") {
            if let Some(kind) = self.fields.remove("type") {
                self.fields
                    .insert("action".to_string(), normalize_action(kind));
            }
        }
        serde_json::to_string(&self.fields).map(|mut line| {
            line.push('\n');
            line
        })
    }
}

fn normalize_action(kind: Value) -> Value {
    match kind.as_str() {
        Some("cancel") => Value::String("abort".to_string()),
        Some(other) => Value::String(other.to_string()),
        None => kind,
    }
}
