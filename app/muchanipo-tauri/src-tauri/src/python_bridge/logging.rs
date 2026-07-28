use std::{
    fs::File,
    io::Write,
    path::{Path, PathBuf},
};

pub(super) fn open_run_log(path: &Path, app_run_id: &str) -> Option<File> {
    let mut log = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .ok()?;
    let _ = writeln!(
        log,
        "--- new run app_run_id={} @ {:?} ---",
        app_run_id,
        std::time::SystemTime::now()
    );
    Some(log)
}

pub(super) fn stdout_log_path_for_app_run_id(app_run_id: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "muchanipo-python-{}-stdout.jsonl",
        sanitize_app_run_id_for_filename(app_run_id)
    ))
}

pub(super) fn stderr_log_path_for_app_run_id(app_run_id: &str) -> PathBuf {
    std::env::temp_dir().join(format!(
        "muchanipo-python-{}-stderr.log",
        sanitize_app_run_id_for_filename(app_run_id)
    ))
}

fn sanitize_app_run_id_for_filename(app_run_id: &str) -> String {
    let sanitized = app_run_id
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '-' | '_') {
                character
            } else {
                '-'
            }
        })
        .collect::<String>();
    let sanitized = sanitized.trim_matches('-');
    if sanitized.is_empty() {
        "run".to_string()
    } else {
        sanitized.to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn app_run_scoped_log_paths_are_unique_and_sanitized() {
        let first = stderr_log_path_for_app_run_id("run-one");
        let second = stderr_log_path_for_app_run_id("../run two!!");
        let stdout = stdout_log_path_for_app_run_id("../run two!!");
        assert_ne!(first, second);
        assert_eq!(
            second.file_name().and_then(|value| value.to_str()),
            Some("muchanipo-python-run-two-stderr.log")
        );
        assert_eq!(
            stdout.file_name().and_then(|value| value.to_str()),
            Some("muchanipo-python-run-two-stdout.jsonl")
        );
    }
}
