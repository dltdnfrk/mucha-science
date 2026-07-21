#!/usr/bin/env python3
"""Build the native, self-contained Muchanipo scientific sidecar."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TAURI_ROOT = ROOT / "app" / "muchanipo-tauri"
BINARIES = TAURI_ROOT / "src-tauri" / "binaries"
SOURCE_DATE_EPOCH = "1704067200"
SUPPORTED_TARGETS = {
    "aarch64-apple-darwin": ("Darwin", "arm64"),
    "x86_64-apple-darwin": ("Darwin", "x86_64"),
    "x86_64-unknown-linux-gnu": ("Linux", "x86_64"),
    "x86_64-pc-windows-msvc": ("Windows", "AMD64"),
}
PINNED_PYINSTALLER_VERSION = "6.11.1"
PINNED_UNICODE_VERSION = "15.1.0"
RUNTIME_MODULES = (
    "muchanipo",
    "muchanipo.__main__",
    "src",
    "src.muchanipo",
    "src.muchanipo.events",
    "src.muchanipo.server",
    "src.pipeline",
    "src.pipeline.cycle_repository",
    "src.pipeline.external_result_ingest",
    "src.pipeline.scientific_contracts",
    "src.pipeline.scientific_cycle",
    "src.pipeline.scientific_handoff",
    "src.runtime",
    "src.runtime.paths",
    "src.hitl",
    "src.hitl.signoff_core",
    "src.report",
    "src.report.scientific_projector",
    "src.council",
    "src.council.scientific_hypotheses",
    "src.evidence",
    "src.evidence.scientific_validation",
)


def module_source(module: str) -> Path:
    base = ROOT / module.replace(".", "/")
    source = base / "__init__.py" if base.is_dir() else base.with_suffix(".py")
    if source.is_symlink():
        raise ValueError(f"sidecar source must not be a symlink: {source}")
    if not source.is_file():
        raise ValueError(f"sidecar runtime module is missing: {module}")
    return source


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def host_target() -> str:
    system, machine = platform.system(), platform.machine()
    for target, host in SUPPORTED_TARGETS.items():
        if host == (system, machine):
            return target
    raise ValueError(f"unsupported native sidecar host: {system}/{machine}")


def source_manifest() -> list[dict[str, str]]:
    files = [ROOT / "pyproject.toml", *(module_source(module) for module in RUNTIME_MODULES)]
    if any(path.is_symlink() for path in files):
        raise ValueError("sidecar sources must not be symlinks")
    return [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256(path)}
        for path in sorted(files)
    ]


def command_output(command: list[str]) -> str:
    return subprocess.run(command, check=True, capture_output=True, text=True).stdout.strip()


def build(python: Path, target: str, output_dir: Path, signing_identity: str) -> tuple[Path, Path]:
    python = python.absolute()
    if not python.is_file():
        raise ValueError("sidecar toolchain interpreter must be an existing file")
    if target != host_target():
        raise ValueError(f"sidecars must be built natively: requested {target}, host is {host_target()}")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"sidecar output directory must be clean: {output_dir}")
    if command_output([str(python), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"]) != "3.11":
        raise ValueError("sidecar toolchain interpreter must be Python 3.11")
    pyinstaller_version = command_output([str(python), "-m", "PyInstaller", "--version"])
    if pyinstaller_version != PINNED_PYINSTALLER_VERSION:
        raise ValueError(f"sidecar toolchain must use PyInstaller {PINNED_PYINSTALLER_VERSION}")
    unicodedata2_version = command_output([str(python), "-c", "import unicodedata2; print(unicodedata2.unidata_version)"])
    if unicodedata2_version != PINNED_UNICODE_VERSION:
        raise ValueError(f"sidecar toolchain must use unicodedata2 pinned to Unicode {PINNED_UNICODE_VERSION}")
    output_dir.mkdir(parents=True, exist_ok=False)
    artifact_name = f"muchanipo-service-{target}" + (".exe" if target.endswith("windows-msvc") else "")
    temporary_root = Path(tempfile.gettempdir()) / f"muchanipo-sidecar-build-{target}"
    if temporary_root.exists():
        shutil.rmtree(temporary_root)
    temporary_root.mkdir()
    try:
        entrypoint = temporary_root / "entrypoint.py"
        entrypoint.write_text("from muchanipo.__main__ import main\nraise SystemExit(main())\n", encoding="utf-8")
        environment = os.environ | {"PYTHONHASHSEED": "0", "SOURCE_DATE_EPOCH": SOURCE_DATE_EPOCH}
        subprocess.run(
            [
                str(python), "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
                "--name", artifact_name, "--paths", str(ROOT),
                *(argument for module in RUNTIME_MODULES for argument in ("--hidden-import", module)),
                "--distpath", str(temporary_root / "dist"),
                "--workpath", str(temporary_root / "work"), "--specpath", str(temporary_root / "spec"),
                str(entrypoint),
            ],
            check=True,
            cwd=ROOT,
            env=environment,
        )
        artifact = output_dir / artifact_name
        shutil.copyfile(temporary_root / "dist" / artifact_name, artifact)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    artifact.chmod(0o755)
    if target.endswith("apple-darwin"):
        subprocess.run(["codesign", "--force", "--sign", signing_identity, "--timestamp=none", str(artifact)], check=True)
        subprocess.run(["codesign", "--verify", "--strict", str(artifact)], check=True)
    digest = sha256(artifact)
    manifest = {
        "artifact": artifact_name,
        "artifact_sha256": digest,
        "byte_length": artifact.stat().st_size,
        "format": "muchanipo.scientific-sidecar.v1",
        "macos_signing_identity": signing_identity if target.endswith("apple-darwin") else None,
        "pyinstaller_version": pyinstaller_version,
        "unicodedata2_unidata_version": unicodedata2_version,
        "python_executable_sha256": sha256(python),
        "python_version": command_output([str(python), "--version"]),
        "source_date_epoch": SOURCE_DATE_EPOCH,
        "sources": source_manifest(),
        "target": target,
    }
    manifest_path = output_dir / f"{artifact_name}.manifest.json"
    manifest_path.write_bytes(json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode() + b"\n")
    (output_dir / f"{artifact_name}.sha256").write_text(f"{digest}  {artifact_name}\n", encoding="ascii")
    return artifact, manifest_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True, type=Path, help="absolute path to the pinned Python 3.11 build interpreter")
    parser.add_argument("--target", default=host_target(), choices=sorted(SUPPORTED_TARGETS))
    parser.add_argument("--output-dir", type=Path, default=BINARIES)
    parser.add_argument("--signing-identity", default="-", help="macOS codesign identity; '-' creates an ad-hoc signature")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove the build-owned output directory before building instead of failing on leftovers",
    )
    args = parser.parse_args()
    if args.clean and args.output_dir.exists():
        shutil.rmtree(args.output_dir)
    artifact, manifest = build(args.python, args.target, args.output_dir, args.signing_identity)
    print(artifact)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
