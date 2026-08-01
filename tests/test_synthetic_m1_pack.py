from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.packs_loader import load_pack
from src.pipeline.scientific_contracts import canonical_json


PACK_DIR = Path(__file__).resolve().parents[1] / "packs" / "synthetic-m1"


def test_synthetic_m1_pack_loads_with_stable_identity_and_no_fixed_purpose() -> None:
    manifest = json.loads((PACK_DIR / "pack.json").read_text(encoding="utf-8"))

    first = load_pack(PACK_DIR)
    second = load_pack(PACK_DIR)

    expected_digest = "sha256:" + hashlib.sha256(canonical_json(manifest)).hexdigest()
    assert first == second
    assert (first.name, first.version, first.manifest_sha256) == (
        "synthetic-m1",
        "0.1.0",
        expected_digest,
    )
    assert {"functional_purpose", "fixed_objective"}.isdisjoint(manifest)
