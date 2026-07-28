use std::collections::HashSet;

use serde_json::{Map, Value};

use super::{ENVELOPE_FIELDS, SCIENTIFIC_PROTOCOL, SCIENTIFIC_PROTOCOL_VERSION};

const MAX_SAFE_COUNTER: u64 = 9_007_199_254_740_991;

pub(super) fn validate_envelope(object: &Map<String, Value>) -> Result<(), String> {
    if object.len() != ENVELOPE_FIELDS.len()
        || ENVELOPE_FIELDS
            .iter()
            .any(|field| !object.contains_key(*field))
        || object
            .keys()
            .any(|field| !ENVELOPE_FIELDS.contains(&field.as_str()))
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
        return Err(
            "scientific envelope timestamp must be a UTC RFC3339 microsecond timestamp".to_string(),
        );
    }
    if !object.get("payload").is_some_and(Value::is_object) {
        return Err("scientific envelope payload must be a plain object".to_string());
    }
    if !object.get("extensions").is_some_and(Value::is_object) {
        return Err("scientific envelope extensions must be a plain object".to_string());
    }
    if object.get("kind").and_then(Value::as_str) == Some("response")
        && object.get("name").and_then(Value::as_str)
            == Some("protocol.welcome.response")
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
        Err(format!(
            "scientific envelope {field} must be a nonempty string"
        ))
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
        .ok_or_else(|| "scientific envelope payload must be a plain object".to_string())?;
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
    if capabilities.len() != capabilities.iter().collect::<HashSet<_>>().len() {
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
        || bytes.iter().enumerate().any(|(index, byte)| {
            !matches!(index, 4 | 7 | 10 | 13 | 16 | 19 | 26) && !byte.is_ascii_digit()
        })
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
    bytes
        .iter()
        .fold(0, |value, byte| value * 10 + u32::from(byte - b'0'))
}

fn days_in_month(year: u32, month: u32) -> u32 {
    match month {
        4 | 6 | 9 | 11 => 30,
        2 if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29,
        2 => 28,
        _ => 31,
    }
}
