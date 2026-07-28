use std::process::{Command, Stdio};

use super::{cli::path::merged_cli_path, workspace::workspace_root};

pub(super) fn resolve_python_bin() -> Result<String, String> {
    let candidates = python_bin_candidates();
    select_python_bin(
        &candidates,
        python_candidate_exists,
        python_imports_pipeline_deps,
    )
    .ok_or_else(|| {
        format!(
            "no Python interpreter with Muchanipo dependencies found; tried {}. \
Install project deps into one of those interpreters or set MUCHANIPO_PYTHON.",
            candidates.join(", ")
        )
    })
}

fn python_bin_candidates() -> Vec<String> {
    let mut candidates = Vec::new();
    if let Ok(override_bin) = std::env::var("MUCHANIPO_PYTHON") {
        push_unique_candidate(&mut candidates, override_bin.trim());
    }
    for candidate in [
        "python",
        "/usr/local/bin/python3",
        "/opt/homebrew/bin/python3",
        "/usr/bin/python3",
        "python3",
    ] {
        push_unique_candidate(&mut candidates, candidate);
    }
    candidates
}

fn push_unique_candidate(candidates: &mut Vec<String>, candidate: &str) {
    if !candidate.is_empty() && !candidates.iter().any(|existing| existing == candidate) {
        candidates.push(candidate.to_string());
    }
}

fn select_python_bin<F, G>(
    candidates: &[String],
    mut is_available: F,
    mut supports_pipeline: G,
) -> Option<String>
where
    F: FnMut(&str) -> bool,
    G: FnMut(&str) -> bool,
{
    candidates
        .iter()
        .filter(|candidate| is_available(candidate))
        .find(|candidate| supports_pipeline(candidate))
        .cloned()
}

fn python_candidate_exists(bin: &str) -> bool {
    matches!(bin, "python" | "python3") || std::path::Path::new(bin).exists()
}

fn python_imports_pipeline_deps(bin: &str) -> bool {
    Command::new(bin)
        .args(["-c", "import httpx"])
        .current_dir(workspace_root())
        .env("PATH", merged_cli_path())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .is_ok_and(|status| status.success())
}

#[cfg(test)]
mod tests {
    use super::select_python_bin;

    #[test]
    fn skips_available_but_unsupported_interpreter() {
        let candidates = vec![
            "/opt/homebrew/bin/python3".to_string(),
            "/usr/local/bin/python3".to_string(),
            "python3".to_string(),
        ];
        let selected = select_python_bin(
            &candidates,
            |_| true,
            |candidate| candidate == "/usr/local/bin/python3",
        );
        assert_eq!(selected, Some("/usr/local/bin/python3".to_string()));
    }

    #[test]
    fn returns_none_when_no_candidate_supports_pipeline() {
        let candidates = vec![
            "/opt/homebrew/bin/python3".to_string(),
            "/usr/local/bin/python3".to_string(),
        ];
        assert_eq!(select_python_bin(&candidates, |_| true, |_| false), None);
    }
}
