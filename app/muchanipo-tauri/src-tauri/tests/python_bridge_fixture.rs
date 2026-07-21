#[path = "../src/scientific_events.rs"]
mod scientific_events;
#[path = "../src/scientific_bridge.rs"]
mod scientific_bridge;

use scientific_bridge::{
    accept_welcome_for_test, action_is_authorized_for_test, bounded_line_for_test,
    establish_muchanipo_home, parse_backend_line_for_test, resolve_packaged_sidecar_path,
    scientific_sidecar_name, shutdown_bridge_for_exit, BridgePhase, ScientificBridge,
};
use std::{fs, path::PathBuf, time::{SystemTime, UNIX_EPOCH}};

fn temporary_directory(name: &str) -> PathBuf {
    let nonce = SystemTime::now().duration_since(UNIX_EPOCH).expect("system clock should be after Unix epoch").as_nanos();
    let directory = std::env::temp_dir().join(format!("muchanipo-python-bridge-{name}-{}-{nonce}", std::process::id()));
    fs::create_dir_all(&directory).expect("temporary fixture directory should be created");
    directory
}

#[test]
fn packaged_resolver_selects_the_generic_external_bin_in_the_packaged_layout() {
    let resource_dir = temporary_directory("bundled-resource");
    let executable_dir = temporary_directory("bundled-macos");
    fs::write(resource_dir.join("caller-selected.pyz"), b"untrusted").expect("arbitrary fixture should be written");
    let sidecar_name = scientific_sidecar_name();
    let bundled_sidecar = executable_dir.join("muchanipo-service");
    fs::write(&bundled_sidecar, b"bundled").expect("bundled fixture should be written");
    let manifest_dir = resource_dir.join("binaries");
    fs::create_dir(&manifest_dir).expect("manifest directory should be created");
    fs::write(
        manifest_dir.join(format!("{sidecar_name}.manifest.json")),
        format!(
            r#"{{"artifact":"{sidecar_name}","target":"{}","artifact_sha256":"4c4164b5039c360603643de4507bf8a558e50513b01281aa5ecbe5c22be298c9"}}"#,
            sidecar_name.trim_start_matches("muchanipo-service-"),
        ),
    ).expect("sidecar manifest should be written");
    assert_eq!(resolve_packaged_sidecar_path(&resource_dir, &executable_dir).expect("bundled sidecar should resolve"), bundled_sidecar.canonicalize().unwrap());
    fs::remove_dir_all(resource_dir).expect("temporary fixture directory should be removed");
    fs::remove_dir_all(executable_dir).expect("temporary fixture directory should be removed");
}

#[test]
fn packaged_resolver_fails_closed_when_the_bundle_is_missing() {
    let resource_dir = temporary_directory("missing-bundle");
    let executable_dir = temporary_directory("missing-external-bin");
    assert!(resolve_packaged_sidecar_path(&resource_dir, &executable_dir).expect_err("missing sidecar must not fall back").contains("bundled scientific sidecar is missing"));
    fs::remove_dir_all(resource_dir).expect("temporary fixture directory should be removed");
    fs::remove_dir_all(executable_dir).expect("temporary fixture directory should be removed");
}
#[test]
fn packaged_resolver_rejects_a_manifest_hash_mismatch() {
    let resource_dir = temporary_directory("hash-mismatch-resource");
    let executable_dir = temporary_directory("hash-mismatch-external-bin");
    let sidecar_name = scientific_sidecar_name();
    fs::write(executable_dir.join("muchanipo-service"), b"tampered").expect("sidecar fixture should be written");
    let manifest_dir = resource_dir.join("binaries");
    fs::create_dir(&manifest_dir).expect("manifest directory should be created");
    fs::write(
        manifest_dir.join(format!("{sidecar_name}.manifest.json")),
        format!(
            r#"{{"artifact":"{sidecar_name}","target":"{}","artifact_sha256":"4c4164b5039c360603643de4507bf8a558e50513b01281aa5ecbe5c22be298c9"}}"#,
            sidecar_name.trim_start_matches("muchanipo-service-"),
        ),
    ).expect("manifest fixture should be written");
    assert!(resolve_packaged_sidecar_path(&resource_dir, &executable_dir)
        .expect_err("hash mismatch must fail closed")
        .contains("SHA-256 does not match"));
    fs::remove_dir_all(resource_dir).expect("temporary fixture directory should be removed");
    fs::remove_dir_all(executable_dir).expect("temporary fixture directory should be removed");
}

#[cfg(unix)]
#[test]
fn packaged_resolver_rejects_a_symlink_even_when_it_points_inside_resources() {
    use std::os::unix::fs::symlink;
    let resource_dir = temporary_directory("symlink-bundle");
    let executable_dir = temporary_directory("symlink-external-bin");
    let target = executable_dir.join("real-sidecar");
    fs::write(&target, b"bundled").expect("target fixture should be written");
    symlink(&target, executable_dir.join("muchanipo-service")).expect("symlink fixture should be created");
    assert!(resolve_packaged_sidecar_path(&resource_dir, &executable_dir).expect_err("symlink must be rejected").contains("symbolic link"));
    fs::remove_dir_all(resource_dir).expect("temporary fixture directory should be removed");
    fs::remove_dir_all(executable_dir).expect("temporary fixture directory should be removed");
}

#[test]
fn muchanipo_home_is_canonical_direct_app_data_descendant() {
    let app_data = temporary_directory("app-data");
    let home = establish_muchanipo_home(app_data.clone()).expect("home should be created");
    assert_eq!(home, app_data.canonicalize().unwrap().join("muchanipo"));
    assert!(!fs::symlink_metadata(&home).unwrap().file_type().is_symlink());
    fs::remove_dir_all(app_data).expect("temporary fixture directory should be removed");
}

#[cfg(unix)]
#[test]
fn muchanipo_home_rejects_a_symlink() {
    use std::os::unix::fs::symlink;

    let app_data = temporary_directory("symlink-home");
    let target = temporary_directory("symlink-home-target");
    symlink(&target, app_data.join("muchanipo")).expect("symlink fixture should be created");
    assert!(establish_muchanipo_home(app_data.clone())
        .expect_err("symlink home must fail closed")
        .contains("symbolic link"));
    fs::remove_dir_all(app_data).expect("temporary fixture directory should be removed");
    fs::remove_dir_all(target).expect("temporary fixture directory should be removed");
}

#[test]
fn start_reservation_rejects_duplicates_and_resets_for_a_new_generation() {
    let bridge = ScientificBridge::default();
    let first = bridge.reserve_start_for_test().expect("first start reserves the bridge");
    assert_eq!(bridge.lifecycle_for_test().unwrap(), (BridgePhase::Starting, first));
    assert!(bridge.reserve_start_for_test().expect_err("concurrent start must fail").contains("already starting"));
    bridge.reset_start_for_test(first).expect("failed start resets its generation");
    let second = bridge.reserve_start_for_test().expect("restart reserves a new generation");
    assert!(second > first);
    assert_eq!(bridge.lifecycle_for_test().unwrap(), (BridgePhase::Starting, second));
}
#[test]
fn quarantined_generation_rejects_writes_and_new_starts_after_fatal_or_monitor_failure() {
    let bridge = ScientificBridge::default();
    let generation = bridge.reserve_start_for_test().expect("start should reserve a generation");

    bridge
        .quarantine_for_test(generation)
        .expect("fatal protocol or monitor failure must quarantine the generation");

    assert_eq!(bridge.lifecycle_for_test().unwrap(), (BridgePhase::Quarantined, generation));
    assert!(!bridge.accepts_writes_for_test().unwrap(), "quarantine must never authorize writes");
    assert!(bridge
        .reserve_start_for_test()
        .expect_err("new start must not supersede quarantined ownership")
        .contains("cleanup must complete"));
}

#[test]
fn quarantined_owned_process_is_retained_until_stop_retries_cleanup() {
    let bridge = ScientificBridge::default();
    let generation = bridge.reserve_start_for_test().expect("start should reserve a generation");
    bridge
        .quarantine_owned_process_for_test(generation)
        .expect("failed superseded termination must retain its owned process");

    assert_eq!(bridge.lifecycle_for_test().unwrap(), (BridgePhase::Quarantined, generation));
    assert!(bridge.has_process_for_test().unwrap(), "quarantine retains cleanup ownership");
    assert!(bridge
        .write_is_rejected_for_test()
        .expect_err("quarantine must reject writes before touching retained stdin")
        .contains("not authorized"));
    assert!(bridge
        .reserve_start_for_test()
        .expect_err("retained ownership must block superseding starts")
        .contains("cleanup must complete"));

    shutdown_bridge_for_exit(&bridge).expect("later stop should retry cleanup");
    assert_eq!(bridge.lifecycle_for_test().unwrap(), (BridgePhase::Stopped, generation));
    assert!(!bridge.has_process_for_test().unwrap(), "successful retry releases ownership");
}

#[test]
fn action_authorization_uses_only_current_negotiated_capabilities() {
    assert!(action_is_authorized_for_test(false, false, &[], "protocol.hello"));
    assert!(!action_is_authorized_for_test(false, true, &[], "protocol.hello"));
    assert!(!action_is_authorized_for_test(true, false, &[], "protocol.hello"));
    assert!(!action_is_authorized_for_test(false, false, &["cycle.start"], "cycle.start"));
    assert!(action_is_authorized_for_test(true, false, &["cycle.start"], "cycle.start"));
    assert!(!action_is_authorized_for_test(true, false, &["cycle.start"], "export.create"));
}
#[test]
fn welcome_requires_the_single_pending_hello_correlation() {
    assert!(accept_welcome_for_test(false, Some("hello-1"), "hello-1").is_ok());
    assert!(accept_welcome_for_test(false, None, "hello-1")
        .expect_err("unprompted welcome must fail")
        .contains("pending protocol.hello"));
    assert!(accept_welcome_for_test(false, Some("hello-1"), "hello-2")
        .expect_err("wrong correlation must fail")
        .contains("pending protocol.hello"));
    assert!(accept_welcome_for_test(true, Some("hello-1"), "hello-1")
        .expect_err("replayed welcome must fail")
        .contains("replayed"));
}

#[test]
fn legacy_mode_accepts_legacy_actions_and_rejects_scientific_or_mixed_frames() {
    assert!(parse_backend_line_for_test(false, r#"{"event":"progress","step":1}"#).is_ok());
    assert!(parse_backend_line_for_test(false, r#"{"event":"progress","protocol":"muchanipo"}"#)
        .expect_err("mixed frame must fail closed")
        .contains("mixed-protocol"));
}

#[test]
fn scientific_mode_rejects_legacy_frames() {
    assert!(parse_backend_line_for_test(true, r#"{"event":"progress"}"#)
        .expect_err("legacy frame must not cross a scientific boundary")
        .contains("legacy or mixed-protocol"));
    assert!(parse_backend_line_for_test(true, r#"{"event":"progress","protocol":"muchanipo"}"#)
        .expect_err("ambiguous mixed frame must fail closed")
        .contains("exactly the common v1 fields"));
}

#[test]
fn oversized_jsonl_frames_are_rejected_before_unbounded_allocation() {
    assert!(bounded_line_for_test(&vec![b'x'; 32], 16)
        .expect_err("oversized unterminated frame must fail")
        .contains("16 byte limit"));
    assert_eq!(bounded_line_for_test(b"{\"event\":\"ok\"}\n", 64).unwrap(), Some("{\"event\":\"ok\"}".to_string()));
}

#[test]
fn tauri_csp_is_a_non_null_valid_json_string() {
    let config: serde_json::Value = serde_json::from_str(include_str!("../tauri.conf.json")).expect("Tauri config must parse");
    let csp = config["app"]["security"]["csp"].as_str().expect("CSP must be non-null");
    assert!(csp.contains("default-src 'self'"));
    assert!(csp.contains("ipc:"));
}
