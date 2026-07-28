use std::process::Command;

use super::{model::CliName, path::which_binary};
use crate::python_bridge::{cli::path::merged_cli_path, workspace::workspace_root};

#[derive(serde::Serialize)]
pub struct CliAuthLaunch {
    pub name: String,
    pub command: String,
    pub login_command: String,
}

#[tauri::command]
pub async fn open_cli_auth(name: String) -> Result<CliAuthLaunch, String> {
    let cli = CliName::parse(&name)?;
    let name = cli.as_str().to_string();
    if which_binary(cli.as_str()).is_none() {
        return Err(format!("{name} CLI is not installed or not on PATH"));
    }

    let login_command = cli.login_command();
    let command = terminal_login_script(&name, login_command);
    let osa = format!(
        "tell application \"Terminal\"\nactivate\ndo script \"{}\"\nend tell",
        escape_applescript_string(&command)
    );
    let output = Command::new("/usr/bin/osascript")
        .arg("-e")
        .arg(osa)
        .output()
        .map_err(|error| {
            cli_auth_fallback_error(&format!("failed to open Terminal: {error}"), login_command)
        })?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let detail = if stderr.is_empty() {
            format!("osascript exited with {:?}", output.status.code())
        } else {
            stderr
        };
        return Err(cli_auth_fallback_error(&detail, login_command));
    }

    Ok(CliAuthLaunch {
        name,
        command,
        login_command: login_command.to_string(),
    })
}

fn terminal_login_script(name: &str, login_command: &str) -> String {
    format!(
        "cd {}; export PATH={}; clear; echo {}; echo {}; {}; echo; echo {}",
        shell_quote(&workspace_root().to_string_lossy()),
        shell_quote(&merged_cli_path()),
        shell_quote(&format!("Muchanipo: connecting {name} CLI")),
        shell_quote("Complete the login flow in this Terminal window."),
        login_command,
        shell_quote("When finished, return to Muchanipo and click 다시 확인 or 실호출 테스트.")
    )
}

fn cli_auth_fallback_error(detail: &str, login_command: &str) -> String {
    format!(
        "{}. Manual fallback: open Terminal, run `cd {}`, then run `{}`.",
        detail,
        shell_quote(&workspace_root().to_string_lossy()),
        login_command
    )
}

fn shell_quote(raw: &str) -> String {
    format!("'{}'", raw.replace('\'', "'\\''"))
}

fn escape_applescript_string(raw: &str) -> String {
    raw.replace('\\', "\\\\").replace('"', "\\\"")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shell_quote_handles_single_quotes() {
        assert_eq!(shell_quote("a'b"), "'a'\\''b'");
    }

    #[test]
    fn applescript_escape_handles_quotes_and_backslashes() {
        assert_eq!(
            escape_applescript_string("say \"hi\" \\ done"),
            "say \\\"hi\\\" \\\\ done"
        );
    }

    #[test]
    fn auth_error_includes_manual_terminal_fallback() {
        let message = cli_auth_fallback_error("Terminal automation blocked", "codex login");
        for expected in [
            "Terminal automation blocked",
            "Manual fallback: open Terminal",
            "codex login",
            "cd ",
        ] {
            assert!(message.contains(expected));
        }
    }
}
