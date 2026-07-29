use std::path::{Path, PathBuf};

pub(super) fn workspace_root() -> PathBuf {
    let configured_candidate = std::env::var_os("MUCHANIPO_WORKSPACE_ROOT")
        .or_else(|| std::env::var_os("MUCHANIPO_WORKSPACE"))
        .map(PathBuf::from);
    let manifest = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let manifest_candidate = manifest
        .parent()
        .and_then(|path| path.parent())
        .and_then(|path| path.parent())
        .map(PathBuf::from);
    let cwd = std::env::current_dir().ok();
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|path| path.parent().map(PathBuf::from));

    resolve_workspace_root(configured_candidate, manifest_candidate, cwd, exe_dir)
}

fn resolve_workspace_root(
    configured_candidate: Option<PathBuf>,
    manifest_candidate: Option<PathBuf>,
    cwd: Option<PathBuf>,
    exe_dir: Option<PathBuf>,
) -> PathBuf {
    for root in [configured_candidate.as_ref(), manifest_candidate.as_ref()]
        .into_iter()
        .flatten()
    {
        if is_workspace_root(root) {
            return root.to_path_buf();
        }
    }

    for start in [cwd.as_ref(), exe_dir.as_ref()].into_iter().flatten() {
        if let Some(root) = find_workspace_root_from(start.clone()) {
            return root;
        }
    }

    cwd.or(exe_dir)
        .or(manifest_candidate)
        .or(configured_candidate)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn find_workspace_root_from(mut path: PathBuf) -> Option<PathBuf> {
    loop {
        if is_workspace_root(&path) {
            return Some(path);
        }
        if !path.pop() {
            return None;
        }
    }
}

fn is_workspace_root(path: &Path) -> bool {
    path.join("muchanipo").join("__init__.py").exists()
        || path
            .join("src")
            .join("muchanipo")
            .join("__init__.py")
            .exists()
}

#[cfg(test)]
#[path = "workspace_tests.rs"]
mod tests;
