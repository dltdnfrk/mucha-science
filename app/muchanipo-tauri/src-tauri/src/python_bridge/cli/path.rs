use std::{path::PathBuf, process::Command};

pub(in crate::python_bridge) fn which_binary(name: &str) -> Option<String> {
    let mut candidates: Vec<String> = candidate_user_bin_dirs()
        .into_iter()
        .map(|dir| format!("{dir}/{name}"))
        .collect();
    candidates.extend([
        format!("/usr/local/bin/{name}"),
        format!("/opt/homebrew/bin/{name}"),
    ]);
    for candidate in &candidates {
        if std::path::Path::new(candidate).exists() {
            return Some(candidate.clone());
        }
    }

    let output = Command::new("/bin/sh")
        .arg("-c")
        .arg(format!("command -v {name}"))
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
    (!path.is_empty()).then_some(path)
}

fn candidate_user_bin_dirs() -> Vec<String> {
    let mut dirs = Vec::new();
    if let Ok(home) = std::env::var("HOME") {
        dirs.push(
            PathBuf::from(&home)
                .join(".npm-global/bin")
                .to_string_lossy()
                .to_string(),
        );
        dirs.push(
            PathBuf::from(&home)
                .join(".local/bin")
                .to_string_lossy()
                .to_string(),
        );
    }
    dirs
}

pub(in crate::python_bridge) fn merged_cli_path() -> String {
    let mut dirs = Vec::new();
    for dir in candidate_user_bin_dirs() {
        if std::path::Path::new(&dir).exists() {
            dirs.push(dir);
        }
    }
    for dir in [
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/opt/homebrew/sbin",
        "/usr/local/sbin",
    ] {
        if std::path::Path::new(dir).exists() && !dirs.iter().any(|item| item == dir) {
            dirs.push(dir.to_string());
        }
    }
    let current_path = std::env::var("PATH").unwrap_or_default();
    if current_path.is_empty() {
        dirs.join(":")
    } else {
        format!("{}:{current_path}", dirs.join(":"))
    }
}
