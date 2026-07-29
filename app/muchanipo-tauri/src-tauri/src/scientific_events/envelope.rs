use serde_json::Value;

use super::{validation::validate_envelope, SCIENTIFIC_PROTOCOL_VERSION, V1_ACTIONS};

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

    pub fn welcome_capabilities(&self) -> Option<Vec<String>> {
        if !self.is_welcome() {
            return None;
        }
        self.raw["payload"]["capabilities"]
            .as_array()
            .map(|capabilities| {
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
            .ok_or_else(|| "scientific envelope name must be a nonempty string".to_string())?;
        if !V1_ACTIONS.contains(&name) {
            return Err(format!("unsupported scientific v1 action: {name}"));
        }

        if name == "protocol.hello" {
            let versions = object["payload"]
                .get("protocol_versions")
                .and_then(Value::as_array)
                .filter(|versions| !versions.is_empty() && versions.iter().all(Value::is_string))
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
