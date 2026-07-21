use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

pub const SCIENTIFIC_PROTOCOL: &str = "muchanipo";
pub const SCIENTIFIC_PROTOCOL_VERSION: &str = "ai-scientist.v1";

const ENVELOPE_FIELDS: [&str; 14] = [
    "protocol",
    "protocol_version",
    "kind",
    "name",
    "message_id",
    "cycle_id",
    "correlation_id",
    "causation_id",
    "sequence",
    "revision",
    "idempotency_key",
    "timestamp",
    "payload",
    "extensions",
];
const V1_ACTIONS: [&str; 20] = [
    "protocol.hello",
    "cycle.start",
    "cycle.replay",
    "cycle.resume",
    "cycle.continue",
    "responsibility.question_selection.disposition",
    "responsibility.safety_ethics_review.disposition",
    "responsibility.execution_accountability.disposition",
    "responsibility.exception_interpretation.disposition",
    "responsibility.novelty_value_judgment.disposition",
    "responsibility.final_accountability.disposition",
    "responsibility.disposition.supersede",
    "proposal.reject",
    "result.submit",
    "validation.adjudicate",
    "export.create",
    "export.get",
    "report.render",
    "cycle.abort",
    "cycle.ack",
];
const MAX_SAFE_COUNTER: u64 = 9_007_199_254_740_991;

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

/// A validated v1 protocol envelope. The raw JSON remains the client projection,
/// so validated server event names and payload fields are not reinterpreted.
#[derive(Debug, Clone)]
pub struct ScientificEnvelope {
    raw: Value,
}

impl ScientificEnvelope {
    pub fn from_value(raw: Value) -> Result<Self, String> {
        let object = raw
            .as_object()
            .ok_or_else(|| "scientific envelope must be a JSON object".to_string())?;

        validate_envelope(object)?;
        Ok(Self { raw })
    }

    pub fn from_server_value(raw: Value) -> Result<Self, String> {
        let envelope = Self::from_value(raw)?;
        if !matches!(
            envelope.raw.get("kind").and_then(Value::as_str),
            Some("response" | "event" | "error" | "snapshot" | "ack")
        ) {
            return Err("scientific server envelope kind is invalid".to_string());
        }
        Ok(envelope)
    }

    pub fn value(&self) -> &Value {
        &self.raw
    }

    pub fn is_welcome(&self) -> bool {
        self.raw.get("kind").and_then(Value::as_str) == Some("response")
            && self.raw.get("name").and_then(Value::as_str) == Some("protocol.welcome.response")
    }

    /// Returns the capability set from a validated welcome response. Callers
    /// must retain this set with the sidecar generation that produced it.
    pub fn welcome_capabilities(&self) -> Option<Vec<String>> {
        if !self.is_welcome() {
            return None;
        }

        self.raw["payload"]["capabilities"].as_array().map(|capabilities| {
            capabilities
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect()
        })
    }

    pub fn supports_v1(&self) -> bool {
        self.welcome_capabilities().is_some()
    }

    pub fn into_action_json_line(self, negotiated: bool) -> Result<String, String> {
        let object = self
            .raw
            .as_object()
            .ok_or_else(|| "scientific envelope must be a JSON object".to_string())?;
        if object.get("kind").and_then(Value::as_str) != Some("action") {
            return Err("scientific envelope kind must be action".to_string());
        }

        let name = object["name"]
            .as_str()
            .expect("validated scientific envelope name");
        if !V1_ACTIONS.contains(&name) {
            return Err(format!("unsupported scientific v1 action: {name}"));
        }

        if name == "protocol.hello" {
            let versions = object["payload"]
                .get("protocol_versions")
                .and_then(Value::as_array)
                .filter(|versions| {
                    !versions.is_empty() && versions.iter().all(|version| version.is_string())
                })
                .ok_or_else(|| {
                    "protocol.hello must declare supported protocol versions".to_string()
                })?;
            if !versions
                .iter()
                .any(|version| version.as_str() == Some(SCIENTIFIC_PROTOCOL_VERSION))
            {
                return Err(format!(
                    "protocol.hello must support {SCIENTIFIC_PROTOCOL_VERSION}"
                ));
            }
        } else if !negotiated {
            return Err("protocol.hello must be accepted before scientific actions".to_string());
        }

        serde_json::to_string(&self.raw)
            .map(|mut line| {
                line.push('\n');
                line
            })
            .map_err(|error| format!("failed to encode scientific envelope: {error}"))
    }
}

fn validate_envelope(object: &Map<String, Value>) -> Result<(), String> {
    if object.len() != ENVELOPE_FIELDS.len()
        || ENVELOPE_FIELDS.iter().any(|field| !object.contains_key(*field))
        || object.keys().any(|field| !ENVELOPE_FIELDS.contains(&field.as_str()))
    {
        return Err("scientific envelope must contain exactly the common v1 fields".to_string());
    }

    if object.get("protocol").and_then(Value::as_str) != Some(SCIENTIFIC_PROTOCOL) {
        return Err("unsupported scientific protocol".to_string());
    }
    if object.get("protocol_version").and_then(Value::as_str)
        != Some(SCIENTIFIC_PROTOCOL_VERSION)
    {
        return Err(format!(
            "unsupported scientific protocol version; expected {SCIENTIFIC_PROTOCOL_VERSION}"
        ));
    }
    if !matches!(
        object.get("kind").and_then(Value::as_str),
        Some("action" | "event" | "response" | "error" | "snapshot" | "ack")
    ) {
        return Err("scientific envelope kind is invalid".to_string());
    }
    required_identifier(object, "name")?;
    required_identifier(object, "message_id")?;
    nullable_identifier(object, "cycle_id")?;
    nullable_identifier(object, "correlation_id")?;
    nullable_identifier(object, "causation_id")?;
    nullable_identifier(object, "idempotency_key")?;
    safe_counter(object, "sequence")?;
    safe_counter(object, "revision")?;

    let timestamp = object["timestamp"]
        .as_str()
        .ok_or_else(|| "scientific envelope timestamp must be a string".to_string())?;
    if !is_utc_microsecond_timestamp(timestamp) {
        return Err("scientific envelope timestamp must be a UTC RFC3339 microsecond timestamp".to_string());
    }
    if !object.get("payload").is_some_and(Value::is_object) {
        return Err("scientific envelope payload must be a plain object".to_string());
    }
    if !object.get("extensions").is_some_and(Value::is_object) {
        return Err("scientific envelope extensions must be a plain object".to_string());
    }

    if object.get("kind").and_then(Value::as_str) == Some("response")
        && object.get("name").and_then(Value::as_str) == Some("protocol.welcome.response")
    {
        validate_welcome(object)?;
    }

    Ok(())
}

fn required_identifier(object: &Map<String, Value>, field: &str) -> Result<(), String> {
    if object
        .get(field)
        .and_then(Value::as_str)
        .is_some_and(|value| !value.trim().is_empty())
    {
        Ok(())
    } else {
        Err(format!("scientific envelope {field} must be a nonempty string"))
    }
}

fn nullable_identifier(object: &Map<String, Value>, field: &str) -> Result<(), String> {
    match object.get(field) {
        Some(Value::Null) => Ok(()),
        Some(Value::String(value)) if !value.trim().is_empty() => Ok(()),
        _ => Err(format!(
            "scientific envelope {field} must be null or a nonempty string"
        )),
    }
}

fn safe_counter(object: &Map<String, Value>, field: &str) -> Result<(), String> {
    match object.get(field).and_then(Value::as_u64) {
        Some(value) if value <= MAX_SAFE_COUNTER => Ok(()),
        _ => Err(format!(
            "scientific envelope {field} must be a nonnegative safe integer"
        )),
    }
}

fn validate_welcome(object: &Map<String, Value>) -> Result<(), String> {
    let payload = object["payload"]
        .as_object()
        .expect("validated scientific envelope payload");
    if payload.get("protocol_version").and_then(Value::as_str)
        != Some(SCIENTIFIC_PROTOCOL_VERSION)
        || payload.get("physical_execution").and_then(Value::as_str) != Some("unavailable")
    {
        return Err("scientific welcome does not support this client".to_string());
    }

    let capabilities = payload
        .get("capabilities")
        .and_then(Value::as_array)
        .filter(|capabilities| {
            !capabilities.is_empty()
                && capabilities.iter().all(|capability| {
                    capability
                        .as_str()
                        .is_some_and(|name| !name.trim().is_empty())
                })
        })
        .ok_or_else(|| {
            "scientific welcome capabilities must be a nonempty array of strings".to_string()
        })?;

    if capabilities.len() != capabilities.iter().collect::<std::collections::HashSet<_>>().len() {
        return Err("scientific welcome capabilities must not contain duplicates".to_string());
    }
    Ok(())
}

fn is_utc_microsecond_timestamp(timestamp: &str) -> bool {
    let bytes = timestamp.as_bytes();
    if bytes.len() != 27
        || bytes[4] != b'-'
        || bytes[7] != b'-'
        || bytes[10] != b'T'
        || bytes[13] != b':'
        || bytes[16] != b':'
        || bytes[19] != b'.'
        || bytes[26] != b'Z'
        || bytes
            .iter()
            .enumerate()
            .any(|(index, byte)| !matches!(index, 4 | 7 | 10 | 13 | 16 | 19 | 26) && !byte.is_ascii_digit())
    {
        return false;
    }

    let year = number(&bytes[0..4]);
    let month = number(&bytes[5..7]);
    let day = number(&bytes[8..10]);
    let hour = number(&bytes[11..13]);
    let minute = number(&bytes[14..16]);
    let second = number(&bytes[17..19]);
    year > 0
        && (1..=12).contains(&month)
        && day > 0
        && day <= days_in_month(year, month)
        && hour < 24
        && minute < 60
        && second < 60
}

fn number(bytes: &[u8]) -> u32 {
    bytes.iter().fold(0, |value, byte| value * 10 + u32::from(byte - b'0'))
}

fn days_in_month(year: u32, month: u32) -> u32 {
    match month {
        4 | 6 | 9 | 11 => 30,
        2 if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29,
        2 => 28,
        _ => 31,
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
        let contains_envelope_field = ENVELOPE_FIELDS.iter().any(|field| object.contains_key(*field));

        match mode {
            BackendMode::Legacy => {
                if contains_envelope_field {
                    return Err("legacy sidecar emitted a scientific or mixed-protocol frame".to_string());
                }
                if !object
                    .get("event")
                    .and_then(Value::as_str)
                    .is_some_and(|event| !event.trim().is_empty())
                {
                    return Err("legacy backend event must contain a nonempty event discriminator".to_string());
                }
                serde_json::from_value(value)
                    .map(Self::Legacy)
                    .map_err(|error| format!("invalid legacy backend event: {error}"))
            }
            BackendMode::ScientificV1 => {
                if !contains_envelope_field {
                    return Err("scientific sidecar emitted a legacy or mixed-protocol frame".to_string());
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
