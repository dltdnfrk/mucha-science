use std::{
    fs,
    path::{Path, PathBuf},
    sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    },
    thread,
    time::{Duration, Instant},
};

use tauri::{test::MockRuntime, App, Listener, Manager};

use super::python_bridge::{
    cancel_pipeline_core, start_pipeline_core, PythonBridge, StartPipelineRequest,
};

const FIXTURE_SCRIPT: &str = r#"from __future__ import annotations
import datetime
import hashlib
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

script = pathlib.Path(__file__)
pid = os.getpid()
started = subprocess.check_output(["/bin/ps", "-o", "lstart=", "-p", str(pid)], text=True).strip()
if sys.platform == "darwin":
    started = subprocess.check_output(
        ["/bin/date", "-j", "-f", "%a %b %e %T %Y", started, "+%s"], text=True
    ).strip()
digest = hashlib.sha256(pathlib.Path(sys.executable).read_bytes()).hexdigest()
handshake = {
    "pid": pid,
    "process_start_time": started,
    "pgid": os.getpgid(0),
    "launch_nonce": os.environ["MUCHANIPO_EXECUTION_NONCE"],
    "generation": int(os.environ["MUCHANIPO_EXECUTION_GENERATION"]),
    "owner_boot_id": os.environ["MUCHANIPO_OWNER_BOOT_ID"],
    "executable_digest": digest,
}
path = pathlib.Path(os.environ["MUCHANIPO_EXECUTION_HANDSHAKE_PATH"])
temporary = path.with_suffix(".tmp")
temporary.write_text(json.dumps(handshake), encoding="utf-8")
temporary.replace(path)
child = subprocess.Popen(
    ["/bin/sh", "-c", "trap '' TERM; while :; do /bin/sleep 1; done"]
)
script.with_suffix(".ready").write_text(
    json.dumps({"leader": pid, "descendant": child.pid, "pgid": os.getpgid(0)}),
    encoding="utf-8",
)
generation = handshake["generation"]
for event_generation in (generation - 1, generation, generation):
    print(json.dumps({"event": "terminal_run_done", "generation": event_generation}), flush=True)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child.wait()
"#;

fn product_app() -> App<MockRuntime> {
    tauri::test::mock_builder()
        .manage(PythonBridge::default())
        .build(tauri::test::mock_context(tauri::test::noop_assets()))
        .expect("mock product app should build")
}

fn fixture_script(root: &Path) -> PathBuf {
    let script = root.join("owned_pipeline.py");
    fs::write(&script, FIXTURE_SCRIPT).expect("fixture pipeline should be written");
    script
}

fn request(root: &Path, script: &Path, app_run_id: &str) -> StartPipelineRequest {
    StartPipelineRequest {
        topic: "public product path".to_string(),
        pipeline: Some("stub".to_string()),
        depth: Some("shallow".to_string()),
        app_run_id: Some(app_run_id.to_string()),
        envs: None,
        owner_root: root.join("execution-owner"),
        fixture_script: Some(script.to_path_buf()),
    }
}

fn generation(receipt: &serde_json::Value) -> u64 {
    receipt["generation"]
        .as_u64()
        .expect("receipt generation should be numeric")
}

fn process_group(receipt: &serde_json::Value) -> u64 {
    receipt["identity"]["pgid"]
        .as_u64()
        .expect("running receipt should include a PGID")
}

fn wait_for_ready(script: &Path) {
    let deadline = Instant::now() + Duration::from_secs(5);
    while Instant::now() < deadline {
        if script.with_extension("ready").exists() {
            return;
        }
        thread::sleep(Duration::from_millis(20));
    }
    panic!("fixture leader and descendant did not become ready");
}

fn group_member_count(pgid: u64) -> usize {
    let output = std::process::Command::new("/bin/ps")
        .args(["-axo", "pgid="])
        .output()
        .expect("process table should be readable");
    String::from_utf8_lossy(&output.stdout)
        .lines()
        .filter(|line| line.trim().parse::<u64>().ok() == Some(pgid))
        .count()
}

fn restart_until_running(
    root: &Path,
    script: &Path,
    app_run_id: &str,
) -> (App<MockRuntime>, serde_json::Value) {
    let deadline = Instant::now() + Duration::from_secs(6);
    loop {
        let app = product_app();
        let receipt = start_pipeline_core(
            request(root, script, app_run_id),
            app.handle().clone(),
            app.state::<PythonBridge>().inner(),
        )
        .expect("restarted command core should recover");
        if receipt["phase"] == "running" {
            return (app, receipt);
        }
        if Instant::now() >= deadline {
            panic!("restarted command core did not reach running");
        }
        drop(app);
        thread::sleep(Duration::from_millis(50));
    }
}

#[cfg(unix)]
#[test]
fn start_command_core_recovers_all_crash_boundaries_without_duplicate_process_groups() {
    let _guard = super::EXECUTION_FAILPOINT_LOCK
        .lock()
        .expect("failpoint lock should be available");
    for failpoint in [
        "reserved_fsync",
        "spawn",
        "handshake",
        "running_fsync",
    ] {
        let root = super::temporary_directory(&format!("public-{failpoint}"));
        let script = fixture_script(&root);
        let app_run_id = format!("public-{failpoint}");
        let app = product_app();
        std::env::set_var("MUCHANIPO_PYTHON", "../../../.venv/bin/python");
        std::env::set_var("MUCHANIPO_EXECUTION_FAILPOINT", failpoint);
        let result = start_pipeline_core(
            request(&root, &script, &app_run_id),
            app.handle().clone(),
            app.state::<PythonBridge>().inner(),
        );
        std::env::remove_var("MUCHANIPO_EXECUTION_FAILPOINT");
        assert!(result.expect_err("injected crash should interrupt start").contains(failpoint));
        drop(app);

        let (restarted, running) = restart_until_running(&root, &script, &app_run_id);
        wait_for_ready(&script);
        let pgid = process_group(&running);
        assert!(group_member_count(pgid) >= 2);
        let replay = start_pipeline_core(
            request(&root, &script, &app_run_id),
            restarted.handle().clone(),
            restarted.state::<PythonBridge>().inner(),
        )
        .expect("idempotent replay should return the same generation");
        assert_eq!(generation(&running), generation(&replay));
        assert_eq!(group_member_count(pgid), 2);
        cancel_pipeline_core(
            app_run_id,
            generation(&running),
            restarted.handle().clone(),
            restarted.state::<PythonBridge>().inner(),
        )
        .expect("recovered process group should cancel and reap");
        assert_eq!(group_member_count(pgid), 0);
        fs::remove_dir_all(root).expect("fixture directory should be removed");
    }
    std::env::remove_var("MUCHANIPO_PYTHON");
}

#[cfg(unix)]
#[test]
fn cancel_command_core_is_idempotent_post_reap_and_rejects_stale_generation() {
    let _guard = super::EXECUTION_FAILPOINT_LOCK
        .lock()
        .expect("failpoint lock should be available");
    let root = super::temporary_directory("public-cancel");
    let script = fixture_script(&root);
    let app = product_app();
    let cancellation_events = Arc::new(AtomicUsize::new(0));
    let observed_events = cancellation_events.clone();
    app.listen("backend_event", move |event| {
        if event.payload().contains(r#""event":"execution_cancelled""#) {
            observed_events.fetch_add(1, Ordering::SeqCst);
        }
    });
    std::env::set_var("MUCHANIPO_PYTHON", "../../../.venv/bin/python");
    let running = start_pipeline_core(
        request(&root, &script, "public-cancel"),
        app.handle().clone(),
        app.state::<PythonBridge>().inner(),
    )
    .expect("product start core should launch the owned fixture");
    wait_for_ready(&script);
    let pgid = process_group(&running);
    assert!(group_member_count(pgid) >= 2);

    let first = cancel_pipeline_core(
        "public-cancel".to_string(),
        generation(&running),
        app.handle().clone(),
        app.state::<PythonBridge>().inner(),
    )
    .expect("first cancel should wait for reap");
    let second = cancel_pipeline_core(
        "public-cancel".to_string(),
        generation(&running),
        app.handle().clone(),
        app.state::<PythonBridge>().inner(),
    )
    .expect("duplicate cancel should replay acknowledgement");
    assert_eq!(first, second);
    assert_eq!(first["termination_observed"], true);
    assert_eq!(first["reaped"], true);
    assert_eq!(cancellation_events.load(Ordering::SeqCst), 1);
    assert_eq!(group_member_count(pgid), 0);
    assert!(cancel_pipeline_core(
        "public-cancel".to_string(),
        generation(&running) + 1,
        app.handle().clone(),
        app.state::<PythonBridge>().inner(),
    )
    .expect_err("stale generation must be rejected")
    .contains("not active"));
    std::env::remove_var("MUCHANIPO_PYTHON");
    fs::remove_dir_all(root).expect("fixture directory should be removed");
}
