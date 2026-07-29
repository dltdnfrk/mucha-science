use std::{
    fs::{self, File, OpenOptions},
    io::{BufWriter, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

use serde::{de::DeserializeOwned, Serialize};

pub(crate) fn read_json<T: DeserializeOwned>(path: &Path) -> Result<T, String> {
    let bytes = fs::read(path).map_err(|error| {
        format!(
            "failed to read execution receipt {}: {error}",
            path.display()
        )
    })?;
    serde_json::from_slice(&bytes)
        .map_err(|error| format!("invalid execution receipt {}: {error}", path.display()))
}

pub(crate) fn write_json_fsync<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| format!("execution receipt has no parent: {}", path.display()))?;
    fs::create_dir_all(parent).map_err(|error| {
        format!(
            "failed to create execution receipt directory {}: {error}",
            parent.display()
        )
    })?;
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|error| format!("system clock is before Unix epoch: {error}"))?
        .as_nanos();
    let temporary = temporary_path(path, nonce);
    let file = OpenOptions::new()
        .create_new(true)
        .write(true)
        .open(&temporary)
        .map_err(|error| {
            format!(
                "failed to create temporary execution receipt {}: {error}",
                temporary.display()
            )
        })?;
    let mut writer = BufWriter::new(file);
    serde_json::to_writer(&mut writer, value)
        .map_err(|error| format!("failed to encode execution receipt: {error}"))?;
    writer
        .write_all(b"\n")
        .and_then(|()| writer.flush())
        .map_err(|error| format!("failed to write execution receipt: {error}"))?;
    writer
        .get_ref()
        .sync_all()
        .map_err(|error| format!("failed to fsync execution receipt: {error}"))?;
    fs::rename(&temporary, path).map_err(|error| {
        format!(
            "failed to atomically install execution receipt {}: {error}",
            path.display()
        )
    })?;
    File::open(parent)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| {
            format!(
                "failed to fsync execution receipt directory {}: {error}",
                parent.display()
            )
        })
}

fn temporary_path(path: &Path, nonce: u128) -> PathBuf {
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("receipt");
    path.with_file_name(format!(".{file_name}.{}.{}.tmp", std::process::id(), nonce))
}
