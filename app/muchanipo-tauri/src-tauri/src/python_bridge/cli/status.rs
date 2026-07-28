use std::time::Duration;

use super::{
    model::{CliName, ALL_CLIS},
    path::which_binary,
    process::run_command_with_timeout,
};

#[derive(serde::Serialize)]
pub struct CliStatus {
    pub name: String,
    pub installed: bool,
    pub path: Option<String>,
    pub version: Option<String>,
    pub error: Option<String>,
    pub version_timed_out: bool,
    pub pipeline_supported: bool,
    pub smoke_supported: bool,
    pub diagnosis: Option<String>,
}

#[tauri::command]
pub async fn check_cli_status() -> Result<Vec<CliStatus>, String> {
    let mut statuses = Vec::with_capacity(ALL_CLIS.len());
    for cli in ALL_CLIS {
        statuses.push(check_status(cli));
    }
    Ok(statuses)
}

fn check_status(cli: CliName) -> CliStatus {
    let path = which_binary(cli.as_str());
    let mut status = CliStatus {
        name: cli.as_str().to_string(),
        installed: path.is_some(),
        path: path.clone(),
        version: None,
        error: None,
        version_timed_out: false,
        pipeline_supported: true,
        smoke_supported: true,
        diagnosis: Some(cli.diagnosis().to_string()),
    };
    let Some(bin) = path else {
        return status;
    };

    match run_command_with_timeout(&bin, &["--version"], None, Duration::from_secs(8)) {
        Ok(output) if output.timed_out => {
            status.version_timed_out = true;
            status.error = Some("version check timed out".to_string());
        }
        Ok(output) if output.success => {
            let stdout = output.stdout.trim();
            let stderr = output.stderr.trim();
            status.version = Some(if stdout.is_empty() {
                stderr.to_string()
            } else {
                stdout.to_string()
            });
        }
        Ok(output) => {
            let stderr = output.stderr.trim();
            status.error = Some(if stderr.is_empty() {
                format!("version check exited with {:?}", output.code)
            } else {
                stderr.to_string()
            });
        }
        Err(error) => status.error = Some(error.to_string()),
    }
    status
}
