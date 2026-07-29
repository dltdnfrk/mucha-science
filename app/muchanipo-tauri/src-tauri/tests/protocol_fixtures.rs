#[path = "../src/scientific_events.rs"]
mod events;

use events::{
    BackendMessage, BackendMode, ScientificEnvelope, SCIENTIFIC_PROTOCOL,
    SCIENTIFIC_PROTOCOL_VERSION,
};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{fs, path::PathBuf};

#[derive(Deserialize)]
struct FixtureManifest {
    unicode_version: String,
    files: Vec<FixtureEntry>,
}

#[derive(Deserialize)]
struct FixtureEntry {
    path: String,
    length: usize,
    sha256: String,
}

fn sha256(bytes: &[u8]) -> String {
    const K: [u32; 64] = [
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2,
    ];
    let bit_length = (bytes.len() as u64) * 8;
    let mut padded = bytes.to_vec();
    padded.push(0x80);
    while (padded.len() + 8) % 64 != 0 {
        padded.push(0);
    }
    padded.extend_from_slice(&bit_length.to_be_bytes());
    let mut hash = [
        0x6a09e667u32,
        0xbb67ae85,
        0x3c6ef372,
        0xa54ff53a,
        0x510e527f,
        0x9b05688c,
        0x1f83d9ab,
        0x5be0cd19,
    ];
    for block in padded.chunks_exact(64) {
        let mut words = [0u32; 64];
        for (index, chunk) in block.chunks_exact(4).enumerate() {
            words[index] = u32::from_be_bytes(chunk.try_into().unwrap());
        }
        for index in 16..64 {
            words[index] = words[index - 16]
                .wrapping_add(
                    words[index - 15].rotate_right(7)
                        ^ words[index - 15].rotate_right(18)
                        ^ (words[index - 15] >> 3),
                )
                .wrapping_add(words[index - 7])
                .wrapping_add(
                    words[index - 2].rotate_right(17)
                        ^ words[index - 2].rotate_right(19)
                        ^ (words[index - 2] >> 10),
                );
        }
        let mut state = hash;
        for index in 0..64 {
            let choose = (state[4] & state[5]) ^ (!state[4] & state[6]);
            let majority = (state[0] & state[1]) ^ (state[0] & state[2]) ^ (state[1] & state[2]);
            let temporary1 = state[7]
                .wrapping_add(
                    state[4].rotate_right(6)
                        ^ state[4].rotate_right(11)
                        ^ state[4].rotate_right(25),
                )
                .wrapping_add(choose)
                .wrapping_add(K[index])
                .wrapping_add(words[index]);
            let temporary2 =
                (state[0].rotate_right(2) ^ state[0].rotate_right(13) ^ state[0].rotate_right(22))
                    .wrapping_add(majority);
            state = [
                temporary1.wrapping_add(temporary2),
                state[0],
                state[1],
                state[2],
                state[3].wrapping_add(temporary1),
                state[4],
                state[5],
                state[6],
            ];
        }
        for index in 0..8 {
            hash[index] = hash[index].wrapping_add(state[index]);
        }
    }
    hash.iter().map(|word| format!("{word:08x}")).collect()
}

#[test]
fn generated_protocol_fixture_bytes_match_the_manifest() {
    let root =
        PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../config/protocol/ai-scientist.v1");
    let manifest: FixtureManifest =
        serde_json::from_slice(&fs::read(root.join("manifest.json")).unwrap()).unwrap();
    assert_eq!(manifest.unicode_version, "15.1.0");
    assert_eq!(manifest.files.len(), 5);
    for entry in manifest.files {
        let bytes = fs::read(root.join(&entry.path)).unwrap();
        assert_eq!(bytes.len(), entry.length, "{}", entry.path);
        assert_eq!(sha256(&bytes), entry.sha256, "{}", entry.path);
        assert_eq!(bytes.last(), Some(&b'\n'), "{}", entry.path);
        for record in bytes
            .split(|byte| *byte == b'\n')
            .filter(|record| !record.is_empty())
        {
            serde_json::from_slice::<Value>(record).unwrap();
        }
    }
}

fn envelope(kind: &str, name: &str, payload: Value) -> Value {
    json!({
        "protocol": SCIENTIFIC_PROTOCOL,
        "protocol_version": SCIENTIFIC_PROTOCOL_VERSION,
        "kind": kind,
        "name": name,
        "message_id": "message_0123456789abcdef0123456789abcdef",
        "cycle_id": null,
        "correlation_id": null,
        "causation_id": null,
        "sequence": 0,
        "revision": 0,
        "idempotency_key": null,
        "timestamp": "2026-07-19T00:00:00.000000Z",
        "payload": payload,
        "extensions": {"server_extension": {"preserved": true}}
    })
}

#[test]
fn unknown_scientific_events_are_preserved_as_json() {
    let fixture = envelope(
        "event",
        "future.server.event",
        json!({"nested": [1, {"unrecognized": "value"}]}),
    );

    let message =
        BackendMessage::from_json_line_for_mode(&fixture.to_string(), BackendMode::ScientificV1)
            .unwrap();
    let BackendMessage::Scientific(scientific) = message else {
        panic!("scientific envelope must not be translated to a legacy event");
    };

    assert_eq!(scientific.value(), &fixture);
}

#[test]
fn scientific_action_roundtrips_without_payload_reinterpretation() {
    let fixture = envelope(
        "action",
        "cycle.start",
        json!({"subject": "unknown fields remain server-owned", "future": {"n": 1}}),
    );

    let line = ScientificEnvelope::from_value(fixture.clone())
        .unwrap()
        .into_action_json_line(true)
        .unwrap();

    assert_eq!(serde_json::from_str::<Value>(line.trim()).unwrap(), fixture);
}

#[test]
fn incompatible_protocol_version_fails_closed() {
    let mut fixture = envelope("event", "cycle.started", json!({}));
    fixture["protocol_version"] = json!("ai-scientist.v2");

    assert!(ScientificEnvelope::from_value(fixture).is_err());
}

#[test]
fn only_exact_v1_action_names_are_accepted() {
    for name in ["instrument.run", "cycle_start", "cycle.start.physical"] {
        let fixture = envelope("action", name, json!({"target": "x"}));
        let error = ScientificEnvelope::from_value(fixture)
            .unwrap()
            .into_action_json_line(true)
            .unwrap_err();
        assert!(error.contains("unsupported scientific v1 action"));
    }
}

#[test]
fn common_envelope_fields_must_be_complete_exact_and_well_typed() {
    let mut omitted = envelope("event", "future.server.event", json!({}));
    omitted.as_object_mut().unwrap().remove("timestamp");
    assert!(ScientificEnvelope::from_value(omitted).is_err());

    let mut extra = envelope("event", "future.server.event", json!({}));
    extra["untrusted_top_level"] = json!(true);
    assert!(ScientificEnvelope::from_value(extra).is_err());

    let mut wrong_counter = envelope("event", "future.server.event", json!({}));
    wrong_counter["sequence"] = json!(9_007_199_254_740_992_u64);
    assert!(ScientificEnvelope::from_value(wrong_counter).is_err());

    let mut wrong_identifier = envelope("event", "future.server.event", json!({}));
    wrong_identifier["cycle_id"] = json!("");
    assert!(ScientificEnvelope::from_value(wrong_identifier).is_err());

    let mut wrong_timestamp = envelope("event", "future.server.event", json!({}));
    wrong_timestamp["timestamp"] = json!("2026-02-30T00:00:00.000000Z");
    assert!(ScientificEnvelope::from_value(wrong_timestamp).is_err());

    let mut wrong_payload = envelope("event", "future.server.event", json!({}));
    wrong_payload["payload"] = json!([]);
    assert!(ScientificEnvelope::from_value(wrong_payload).is_err());
}

#[test]
fn explicit_protocol_modes_reject_partial_and_mixed_frames() {
    assert!(BackendMessage::from_json_line_for_mode(
        r#"{"protocol":"muchanipo","event":"started"}"#,
        BackendMode::ScientificV1,
    )
    .is_err());
    assert!(BackendMessage::from_json_line_for_mode(
        r#"{"event":"started","sequence":0}"#,
        BackendMode::Legacy,
    )
    .is_err());

    let mut mixed = envelope("event", "future.server.event", json!({}));
    mixed["event"] = json!("legacy.started");
    assert!(
        BackendMessage::from_json_line_for_mode(&mixed.to_string(), BackendMode::ScientificV1)
            .is_err()
    );

    let legacy = BackendMessage::from_json_line_for_mode(
        r#"{"event":"legacy.started","message":"ok"}"#,
        BackendMode::Legacy,
    );
    assert!(matches!(legacy, Ok(BackendMessage::Legacy(_))));
}

#[test]
fn welcome_requires_nonempty_string_capabilities_and_exposes_them() {
    let payload = json!({
        "protocol_version": SCIENTIFIC_PROTOCOL_VERSION,
        "physical_execution": "unavailable",
        "capabilities": ["cycle.start", "cycle.replay"]
    });
    let welcome =
        ScientificEnvelope::from_value(envelope("response", "protocol.welcome.response", payload))
            .unwrap();
    assert!(welcome.supports_v1());
    assert_eq!(
        welcome.welcome_capabilities(),
        Some(vec!["cycle.start".to_string(), "cycle.replay".to_string()])
    );

    for capabilities in [json!([]), json!(["cycle.start", 1]), json!([""])] {
        let payload = json!({
            "protocol_version": SCIENTIFIC_PROTOCOL_VERSION,
            "physical_execution": "unavailable",
            "capabilities": capabilities
        });
        assert!(ScientificEnvelope::from_value(envelope(
            "response",
            "protocol.welcome.response",
            payload,
        ))
        .is_err());
    }
}
#[test]
fn scientific_server_frames_reject_client_actions_and_accept_terminal_kinds() {
    let action = envelope(
        "action",
        "cycle.start",
        json!({"subject": "must not return from server"}),
    );
    assert!(BackendMessage::from_json_line_for_mode(
        &action.to_string(),
        BackendMode::ScientificV1
    )
    .expect_err("server action must fail closed")
    .contains("server envelope kind"));

    for kind in ["snapshot", "ack"] {
        let message = BackendMessage::from_json_line_for_mode(
            &envelope(kind, "cycle.terminal", json!({})).to_string(),
            BackendMode::ScientificV1,
        );
        assert!(matches!(message, Ok(BackendMessage::Scientific(_))));
    }
}
