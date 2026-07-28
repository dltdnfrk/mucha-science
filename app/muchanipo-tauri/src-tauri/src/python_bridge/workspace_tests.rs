use std::path::PathBuf;

use super::{find_workspace_root_from, is_workspace_root, resolve_workspace_root};

fn test_root(label: &str) -> PathBuf {
    std::env::temp_dir().join(format!("{label}-{}", std::process::id()))
}

fn create_src_workspace(label: &str) -> PathBuf {
    let root = test_root(label);
    let package_dir = root.join("src").join("muchanipo");
    std::fs::create_dir_all(&package_dir).expect("create src package dir");
    std::fs::write(package_dir.join("__init__.py"), "").expect("write package marker");
    root
}

#[test]
fn workspace_root_detection_accepts_src_layout() {
    assert!(is_workspace_root(&create_src_workspace(
        "muchanipo-tauri-src-layout"
    )));
}

#[test]
fn workspace_root_fallback_walks_up_to_src_layout() {
    let root = create_src_workspace("muchanipo-tauri-walk-src-layout");
    let nested = root.join("app").join("muchanipo-tauri");
    std::fs::create_dir_all(&nested).expect("create nested app dir");

    assert_eq!(find_workspace_root_from(nested), Some(root));
}

#[test]
fn workspace_root_resolution_uses_packaged_exe_path_when_manifest_is_stale() {
    let root = create_src_workspace("muchanipo-tauri-exe-src-layout");
    let stale_manifest_root = test_root("muchanipo-tauri-stale-src-layout");
    let launch_dir = test_root("muchanipo-tauri-launch-dir");
    let exe_dir = root
        .join("target/release/bundle/macos/Muchanipo.app/Contents/MacOS");
    std::fs::create_dir_all(&stale_manifest_root).expect("create stale manifest root");
    std::fs::create_dir_all(&launch_dir).expect("create launch dir");
    std::fs::create_dir_all(&exe_dir).expect("create exe dir");

    assert_eq!(
        resolve_workspace_root(
            None,
            Some(stale_manifest_root),
            Some(launch_dir),
            Some(exe_dir)
        ),
        root
    );
}

#[test]
fn workspace_root_resolution_prefers_valid_configured_workspace() {
    let root = create_src_workspace("muchanipo-tauri-configured-src-layout");
    let stale_manifest_root = test_root("muchanipo-tauri-configured-stale-manifest");
    let launch_dir = test_root("muchanipo-tauri-configured-launch-dir");
    std::fs::create_dir_all(&stale_manifest_root).expect("create stale manifest root");
    std::fs::create_dir_all(&launch_dir).expect("create launch dir");

    assert_eq!(
        resolve_workspace_root(
            Some(root.clone()),
            Some(stale_manifest_root),
            Some(launch_dir),
            None
        ),
        root
    );
}

#[test]
fn workspace_root_resolution_ignores_invalid_configured_workspace() {
    let root = create_src_workspace("muchanipo-tauri-invalid-config-src-layout");
    let invalid_config = test_root("muchanipo-tauri-invalid-config");
    let exe_dir = root
        .join("target/release/bundle/macos/Muchanipo.app/Contents/MacOS");
    std::fs::create_dir_all(&invalid_config).expect("create invalid config dir");
    std::fs::create_dir_all(&exe_dir).expect("create exe dir");

    assert_eq!(
        resolve_workspace_root(Some(invalid_config), None, None, Some(exe_dir)),
        root
    );
}

#[test]
fn workspace_root_resolution_does_not_return_stale_manifest_candidate() {
    let stale_manifest_root = test_root("muchanipo-tauri-stale-manifest");
    let launch_dir = test_root("muchanipo-tauri-launch-fallback");
    std::fs::create_dir_all(&stale_manifest_root).expect("create stale manifest root");
    std::fs::create_dir_all(&launch_dir).expect("create launch dir");

    assert_eq!(
        resolve_workspace_root(
            None,
            Some(stale_manifest_root),
            Some(launch_dir.clone()),
            None
        ),
        launch_dir
    );
}
