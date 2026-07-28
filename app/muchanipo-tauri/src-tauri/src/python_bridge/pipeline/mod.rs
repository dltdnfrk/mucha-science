mod io;
mod lifecycle;

use std::{
    collections::HashMap,
    process::{Command, Stdio},
};

use tauri::{AppHandle, Manager, State};

use super::{
    backend_events::normalize_app_run_id,
    cli::{merged_cli_path, which_binary},
    pipeline_config::{pipeline_command_args, PipelineMode, ResearchDepth},
    python_runtime::resolve_python_bin,
    renderer_env::sanitize_renderer_envs,
    state::{
        await_verified_handshake, cancel_path, canonical_executable, configure_process_group,
        executable_digest, finalizer_path, now_unix_ms, observe_process, owner_boot_id,
        signal_verified_process_group, write_cancel_token, CancellationDecision, ExecutionOwner,
        LaunchDecision, LaunchRequest, PythonBridge,
    },
    workspace::workspace_root,
};
use io::{spawn_output_readers, OutputReaders};
use lifecycle::{
    clear_telemetry_for_start, install_child, spawn_child_waiter, SpawnedChild, WaitContext,
};

#[tauri::command]
pub async fn start_pipeline(
    topic: String,
    pipeline: Option<String>,
    depth: Option<String>,
    app_run_id: Option<String>,
    envs: Option<HashMap<String, String>>,
    app: AppHandle,
    bridge: State<'_, PythonBridge>,
) -> Result<serde_json::Value, String> {
    let topic = topic.trim().to_string();
    if topic.is_empty() {
        return Err("topic is required".to_string());
    }
    let pipeline_mode = PipelineMode::from_option(pipeline.as_deref());
    let research_depth = ResearchDepth::parse(depth.as_deref())?;
    let app_run_id = normalize_app_run_id(app_run_id.as_deref());
    let python_bin = canonical_executable(&resolve_python_bin()?)?;
    let digest = executable_digest(&python_bin)?;
    let boot_id = owner_boot_id()?;
    let owner_root = app
        .path()
        .app_data_dir()
        .map_err(|error| format!("failed to resolve app data directory: {error}"))?
        .join("execution-owner");

    let mut execution = bridge.execution.lock().map_err(super::state::lock_error)?;
    if execution.owner.is_none() {
        execution.owner = Some(ExecutionOwner::open(owner_root)?);
    }
    let decision = execution
        .owner
        .as_mut()
        .expect("execution owner initialized")
        .reserve_launch(LaunchRequest {
            app_run_id: app_run_id.clone(),
            owner_boot_id: boot_id,
            executable_path: python_bin.display().to_string(),
            executable_digest: digest,
            now_unix_ms: now_unix_ms(),
        })?;
    if let LaunchDecision::Replay(receipt) = decision {
        return serde_json::to_value(receipt)
            .map_err(|error| format!("failed to encode launch receipt: {error}"));
    }
    let receipt = decision.receipt().clone();
    clear_telemetry_for_start(&bridge);

    let mut command = pipeline_command(
        &python_bin,
        &topic,
        pipeline_mode,
        research_depth,
        &app_run_id,
        &receipt,
        envs,
    )?;
    let mut child = command
        .spawn()
        .map_err(|error| format!("failed to start python pipeline: {error}"))?;
    let pid = child.id();
    let stdout = child.stdout.take().ok_or("failed to open python stdout")?;
    let stderr = child.stderr.take().ok_or("failed to open python stderr")?;
    let stdin = child.stdin.take().ok_or("failed to open python stdin")?;
    let (handshake, observed) = await_verified_handshake(&receipt, pid)?;
    let running = execution
        .owner
        .as_mut()
        .expect("execution owner initialized")
        .record_handshake(&receipt, &handshake, &observed)?;
    install_child(
        &mut execution,
        SpawnedChild {
            child,
            stdin,
            receipt: running.clone(),
        },
    );
    let child_handle = execution
        .runtime
        .as_ref()
        .expect("runtime installed")
        .child
        .clone();
    drop(execution);

    let generation = running.generation;
    let owned_bridge = bridge.inner().clone();
    spawn_output_readers(OutputReaders {
        app: app.clone(),
        bridge: owned_bridge.clone(),
        stdout,
        stderr,
        app_run_id: app_run_id.clone(),
        generation,
    });
    spawn_child_waiter(WaitContext {
        app,
        bridge: owned_bridge,
        app_run_id,
        generation,
        child: child_handle,
    });
    serde_json::to_value(running)
        .map_err(|error| format!("failed to encode launch receipt: {error}"))
}

#[tauri::command]
pub async fn cancel_pipeline(
    app_run_id: String,
    generation: u64,
    bridge: State<'_, PythonBridge>,
) -> Result<serde_json::Value, String> {
    let mut execution = bridge.execution.lock().map_err(super::state::lock_error)?;
    let runtime = execution
        .runtime
        .as_ref()
        .filter(|runtime| {
            runtime.receipt.app_run_id == app_run_id
                && runtime.receipt.generation == generation
        })
        .ok_or_else(|| "execution generation is not active".to_string())?;
    let receipt = runtime.receipt.clone();
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
    match decision {
        CancellationDecision::SignalOwnedProcess(identity) => {
            write_cancel_token(&cancel_path(&receipt), &receipt)?;
            let status = signal_verified_process_group(&identity)?;
            if !status.success() {
                return Err(format!("owned process-group signal failed with {status}"));
            }
            Ok(serde_json::json!({"acknowledged": true, "termination_observed": false}))
        }
        CancellationDecision::AwaitTermination => {
            Ok(serde_json::json!({"acknowledged": true, "termination_observed": false}))
        }
        CancellationDecision::AlreadyTerminal(receipt) => serde_json::to_value(receipt)
            .map_err(|error| format!("failed to encode terminal receipt: {error}")),
    }
}

fn pipeline_command(
    python_bin: &std::path::Path,
    topic: &str,
    pipeline_mode: PipelineMode,
    research_depth: ResearchDepth,
    app_run_id: &str,
    receipt: &super::state::LaunchReceipt,
    envs: Option<HashMap<String, String>>,
) -> Result<Command, String> {
    let mut command = Command::new(python_bin);
    command
        .args(pipeline_command_args(topic, pipeline_mode, research_depth))
        .current_dir(workspace_root())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("PATH", merged_cli_path())
        .env("MUCHANIPO_APP_RUN_ID", app_run_id)
        .env("MUCHANIPO_EXECUTION_GENERATION", receipt.generation.to_string())
        .env("MUCHANIPO_EXECUTION_NONCE", &receipt.launch_nonce)
        .env("MUCHANIPO_OWNER_BOOT_ID", &receipt.owner_boot_id)
        .env("MUCHANIPO_EXECUTABLE_DIGEST", &receipt.executable_digest)
        .env("MUCHANIPO_EXECUTION_HANDSHAKE_PATH", super::state::await_path_for_receipt(receipt));
    command
        .env("MUCHANIPO_EXECUTION_CANCEL_PATH", cancel_path(receipt))
        .env("MUCHANIPO_EXECUTION_FINALIZER_PATH", finalizer_path(receipt));
    configure_process_group(&mut command);
    for (cli_name, env_var) in [
        ("claude", "CLAUDE_BIN"),
        ("codex", "CODEX_BIN"),
        ("gemini", "GEMINI_BIN"),
        ("kimi", "KIMI_BIN"),
        ("opencode", "OPENCODE_BIN"),
    ] {
        if let Some(path) = which_binary(cli_name) {
            command.env(env_var, path);
        }
    }
    if let Some(envs) = envs {
        command.envs(sanitize_renderer_envs(envs)?);
    }
    Ok(command)
}
