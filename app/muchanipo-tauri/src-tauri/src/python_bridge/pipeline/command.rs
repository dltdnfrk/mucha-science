use std::{
    collections::HashMap,
    path::Path,
    process::{Command, Stdio},
};

use super::super::{
    cli::{merged_cli_path, which_binary},
    pipeline_config::{pipeline_command_args, PipelineMode, ResearchDepth},
    renderer_env::sanitize_renderer_envs,
    state::{
        cancel_path, configure_process_group, finalizer_path, handshake_path, LaunchReceipt,
    },
    workspace::workspace_root,
};

pub(super) fn pipeline_command(
    python_bin: &Path,
    topic: &str,
    pipeline_mode: PipelineMode,
    research_depth: ResearchDepth,
    app_run_id: &str,
    receipt: &LaunchReceipt,
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
        .env(
            "MUCHANIPO_EXECUTION_GENERATION",
            receipt.generation.to_string(),
        )
        .env("MUCHANIPO_EXECUTION_NONCE", &receipt.launch_nonce)
        .env("MUCHANIPO_OWNER_BOOT_ID", &receipt.owner_boot_id)
        .env("MUCHANIPO_EXECUTABLE_DIGEST", &receipt.executable_digest)
        .env(
            "MUCHANIPO_EXECUTION_HANDSHAKE_PATH",
            handshake_path(receipt),
        )
        .env("MUCHANIPO_EXECUTION_CANCEL_PATH", cancel_path(receipt))
        .env(
            "MUCHANIPO_EXECUTION_FINALIZER_PATH",
            finalizer_path(receipt),
        );
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
