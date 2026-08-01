"""Fail-closed, content-addressed staging for external-tool run artifacts."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
from typing import Sequence

from src.pipeline.scientific_contracts import ContractError, byte_digest, canonical_json, decode_json_object

from .contract import InvocationRecord, StagedRunArtifact


class StagingError(ValueError):
    """Staged invocation content is invalid, conflicting, or tampered."""


def _verify(final_dir: Path, manifest_bytes: bytes, output_digests: tuple[str, ...]) -> None:
    try:
        manifest_path = final_dir / "manifest.json"
        output_dir = final_dir / "outputs"
        if final_dir.is_symlink() or manifest_path.is_symlink() or output_dir.is_symlink():
            raise ValueError
        actual = manifest_path.read_bytes()
        decoded = decode_json_object(actual)
        if (actual != manifest_bytes or canonical_json(decoded) != actual
                or set(decoded) != {"schema_version", "invocation", "outputs"}
                or decoded["schema_version"] != "mucha-science.tool-run.v1"
                or tuple(item["sha256"] for item in decoded["outputs"]) != output_digests
                or any(set(item) != {"sha256"} for item in decoded["outputs"])):
            raise ValueError
        for digest in set(output_digests):
            path = output_dir / digest.removeprefix("sha256:")
            if path.is_symlink() or not path.is_file() or byte_digest(path.read_bytes()) != digest:
                raise ValueError
    except (OSError, KeyError, TypeError, ValueError, ContractError) as exc:
        raise StagingError("existing staged run is missing, conflicting, or tampered") from exc


def stage_run(staging_root: str | Path, record: InvocationRecord, outputs: Sequence[bytes]) -> StagedRunArtifact:
    """Atomically publish outputs and a canonical digest-only manifest."""
    if not isinstance(outputs, (list, tuple)) or any(not isinstance(item, bytes) for item in outputs):
        raise StagingError("outputs must be a sequence of bytes")
    root = Path(staging_root)
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise StagingError("staging root must be a real directory")
    output_digests = tuple(byte_digest(item) for item in outputs)
    manifest = {
        "schema_version": "mucha-science.tool-run.v1",
        "invocation": record.to_dict(),
        "outputs": [{"sha256": value} for value in output_digests],
    }
    manifest_bytes = canonical_json(manifest)
    artifact_id = byte_digest(manifest_bytes)
    final_dir = root / artifact_id.removeprefix("sha256:")
    if final_dir.exists():
        _verify(final_dir, manifest_bytes, output_digests)
    else:
        stage = Path(tempfile.mkdtemp(prefix=f".{final_dir.name}.", dir=root))
        try:
            output_dir = stage / "outputs"
            output_dir.mkdir()
            for raw, digest in zip(outputs, output_digests):
                destination = output_dir / digest.removeprefix("sha256:")
                if destination.exists():
                    if byte_digest(destination.read_bytes()) != digest:
                        raise StagingError("duplicate staged output digest conflicts")
                    continue
                with destination.open("xb") as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
            with (stage / "manifest.json").open("xb") as stream:
                stream.write(manifest_bytes)
                stream.flush()
                os.fsync(stream.fileno())
            directory_fd = os.open(stage, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            try:
                os.rename(stage, final_dir)
            except FileExistsError:
                shutil.rmtree(stage, ignore_errors=True)
                _verify(final_dir, manifest_bytes, output_digests)
            root_fd = os.open(root, os.O_RDONLY)
            try:
                os.fsync(root_fd)
            finally:
                os.close(root_fd)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            raise
    return StagedRunArtifact(artifact_id, artifact_id, output_digests, str(final_dir))
