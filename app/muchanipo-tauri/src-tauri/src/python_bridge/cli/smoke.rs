use std::time::Duration;

use super::{
    model::CliName,
    path::which_binary,
    process::{run_command_with_timeout, CapturedCommand},
};

#[derive(serde::Serialize)]
pub struct CliSmokeResult {
    pub name: String,
    pub ok: bool,
    pub output: Option<String>,
    pub error: Option<String>,
    pub timed_out: bool,
}

#[tauri::command]
pub async fn check_cli_smoke(name: String) -> Result<CliSmokeResult, String> {
    let cli = CliName::parse(&name)?;
    let name = cli.as_str().to_string();
    let Some(bin) = which_binary(cli.as_str()) else {
        return Ok(CliSmokeResult {
            name,
            ok: false,
            output: None,
            error: Some("binary not found".to_string()),
            timed_out: false,
        });
    };
    let spec = cli.smoke_spec();
    let output = run_command_with_timeout(
        &bin,
        spec.args,
        spec.input,
        Duration::from_secs(90),
    )
    .map_err(|error| error.to_string())?;
    Ok(smoke_result(name, output))
}

fn smoke_result(name: String, output: CapturedCommand) -> CliSmokeResult {
    let stdout = output.stdout.trim().to_string();
    let stderr = output.stderr.trim().to_string();
    let error = if output.timed_out {
        Some("smoke test timed out".to_string())
    } else if !output.success {
        Some(if stderr.is_empty() {
            format!("smoke test exited with {:?}", output.code)
        } else {
            stderr
        })
    } else {
        None
    };
    CliSmokeResult {
        name,
        ok: output.success && !output.timed_out,
        output: (!stdout.is_empty()).then(|| strip_kimi_resume_hint(&stdout)),
        error,
        timed_out: output.timed_out,
    }
}

fn strip_kimi_resume_hint(raw: &str) -> String {
    raw.lines()
        .filter(|line| !line.trim().starts_with("To resume this session:"))
        .collect::<Vec<_>>()
        .join("\n")
        .trim()
        .to_string()
}
