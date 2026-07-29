use std::{
    fs,
    path::{Path, PathBuf},
};

use serde_json::Value;
use tauri::{AppHandle, Manager};

use super::sha256::sha256_file;

pub(crate) const SCIENTIFIC_SIDECAR_BASE: &str = "muchanipo-service";

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
const SCIENTIFIC_TARGET: &str = "aarch64-apple-darwin";
#[cfg(all(target_os = "macos", target_arch = "x86_64"))]
const SCIENTIFIC_TARGET: &str = "x86_64-apple-darwin";
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
const SCIENTIFIC_TARGET: &str = "x86_64-unknown-linux-gnu";
#[cfg(all(target_os = "windows", target_arch = "x86_64"))]
const SCIENTIFIC_TARGET: &str = "x86_64-pc-windows-msvc";
#[cfg(not(any(
    all(target_os = "macos", target_arch = "aarch64"),
    all(target_os = "macos", target_arch = "x86_64"),
    all(target_os = "linux", target_arch = "x86_64"),
    all(target_os = "windows", target_arch = "x86_64"),
)))]
compile_error!("Muchanipo scientific sidecar has no native artifact for this target");

pub(crate) fn scientific_sidecar_name() -> String {
    let suffix = if cfg!(windows) { ".exe" } else { "" };
    format!("{SCIENTIFIC_SIDECAR_BASE}-{SCIENTIFIC_TARGET}{suffix}")
}

pub(crate) fn establish_muchanipo_home(app_data_dir: PathBuf) -> Result<PathBuf, String> {
    fs::create_dir_all(&app_data_dir)
        .map_err(|error| format!("failed to create app-local data directory: {error}"))?;
    let app_data_root = app_data_dir
        .canonicalize()
        .map_err(|error| format!("failed to canonicalize app-local data directory: {error}"))?;
    if !app_data_root.is_dir() {
        return Err("app-local data directory is not a directory".to_string());
    }

    let muchanipo_home = app_data_root.join("muchanipo");
    match fs::symlink_metadata(&muchanipo_home) {
        Ok(metadata) if metadata.file_type().is_symlink() => {
            return Err("app-local MUCHANIPO_HOME must not be a symbolic link".to_string());
        }
        Ok(metadata) if !metadata.is_dir() => {
            return Err("app-local MUCHANIPO_HOME is not a directory".to_string());
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
            fs::create_dir(&muchanipo_home)
                .map_err(|error| format!("failed to create app-local MUCHANIPO_HOME: {error}"))?;
        }
        Err(error) => {
            return Err(format!(
                "failed to inspect app-local MUCHANIPO_HOME: {error}"
            ));
        }
    }
    let canonical_home = muchanipo_home
        .canonicalize()
        .map_err(|error| format!("failed to canonicalize app-local MUCHANIPO_HOME: {error}"))?;
    if canonical_home.parent() != Some(app_data_root.as_path()) {
        return Err(
            "app-local MUCHANIPO_HOME must be a direct canonical descendant of app data"
                .to_string(),
        );
    }
    Ok(canonical_home)
}

pub(super) fn resolve_sidecar_path(app: &AppHandle) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| format!("failed to resolve bundled scientific sidecar: {error}"))?;
    let executable = std::env::current_exe()
        .map_err(|error| format!("failed to resolve bundled scientific sidecar: {error}"))?;
    let executable_dir = executable.parent().ok_or_else(|| {
        "bundled scientific sidecar executable has no parent directory".to_string()
    })?;
    resolve_packaged_sidecar_path(&resource_dir, executable_dir)
}

pub(crate) fn resolve_packaged_sidecar_path(
    resource_dir: &Path,
    executable_dir: &Path,
) -> Result<PathBuf, String> {
    let resource_root = resource_dir
        .canonicalize()
        .map_err(|error| format!("failed to canonicalize bundled resource root: {error}"))?;
    if !resource_root.is_dir() {
        return Err("bundled resource root is not a directory".to_string());
    }
    let sidecar = executable_dir.join(format!(
        "{SCIENTIFIC_SIDECAR_BASE}{}",
        if cfg!(windows) { ".exe" } else { "" }
    ));
    let metadata = fs::symlink_metadata(&sidecar).map_err(|_| {
        format!(
            "bundled scientific sidecar is missing: {}",
            sidecar.display()
        )
    })?;
    if metadata.file_type().is_symlink() {
        return Err("bundled scientific sidecar must not be a symbolic link".to_string());
    }
    if !metadata.is_file() {
        return Err(format!(
            "bundled scientific sidecar is missing: {}",
            sidecar.display()
        ));
    }
    let canonical_sidecar = sidecar
        .canonicalize()
        .map_err(|error| format!("failed to canonicalize bundled scientific sidecar: {error}"))?;
    verify_sidecar_manifest(
        &resource_root,
        &canonical_sidecar,
        &scientific_sidecar_name(),
    )?;
    Ok(canonical_sidecar)
}

fn verify_sidecar_manifest(resource_root: &Path, sidecar: &Path, name: &str) -> Result<(), String> {
    let manifest_path = resource_root
        .join("binaries")
        .join(format!("{name}.manifest.json"));
    let metadata = fs::symlink_metadata(&manifest_path)
        .map_err(|_| "bundled scientific sidecar manifest is missing".to_string())?;
    if metadata.file_type().is_symlink() || !metadata.is_file() {
        return Err("bundled scientific sidecar manifest must be a regular file".to_string());
    }
    let bytes = fs::read(&manifest_path)
        .map_err(|error| format!("failed to read bundled scientific sidecar manifest: {error}"))?;
    let manifest: Value = serde_json::from_slice(&bytes)
        .map_err(|error| format!("bundled scientific sidecar manifest is invalid JSON: {error}"))?;
    let expected_name = manifest
        .get("artifact")
        .and_then(Value::as_str)
        .ok_or_else(|| "bundled scientific sidecar manifest omits artifact".to_string())?;
    let expected_target = manifest
        .get("target")
        .and_then(Value::as_str)
        .ok_or_else(|| "bundled scientific sidecar manifest omits target".to_string())?;
    let expected_hash = manifest
        .get("artifact_sha256")
        .and_then(Value::as_str)
        .ok_or_else(|| "bundled scientific sidecar manifest omits artifact SHA-256".to_string())?;
    if expected_name != name || expected_target != SCIENTIFIC_TARGET || !is_sha256(expected_hash) {
        return Err(
            "bundled scientific sidecar manifest does not identify this native artifact"
                .to_string(),
        );
    }
    if sha256_file(sidecar)? != expected_hash {
        return Err("bundled scientific sidecar SHA-256 does not match its manifest".to_string());
    }
    Ok(())
}

fn is_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
}
