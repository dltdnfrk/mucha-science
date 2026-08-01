#!/usr/bin/env python3
"""Deterministic local executable used by the reference mock scorer adapter."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json


def _decode(value: str) -> str:
    return base64.b64decode(value.encode("ascii"), validate=True).decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-b64", required=True)
    parser.add_argument("--target-b64", required=True)
    parser.add_argument("--seed", required=True, type=int)
    arguments = parser.parse_args()
    if not 0 <= arguments.seed <= 2**64 - 1:
        parser.error("seed must be uint64")

    candidate = _decode(arguments.candidate_b64)
    target = _decode(arguments.target_b64)
    candidate_hash = hashlib.sha256(candidate.encode("utf-8")).digest()
    target_hash = hashlib.sha256(target.encode("utf-8")).digest()
    matching_bits = 256 - sum((left ^ right).bit_count() for left, right in zip(candidate_hash, target_hash))
    seed_bytes = arguments.seed.to_bytes(8, "big")
    jitter = int.from_bytes(hashlib.sha256(candidate_hash + target_hash + seed_bytes).digest()[:8], "big") % 100_001
    score_ppm = (matching_bits * 900_000 // 256) + jitter
    output = {
        "abstention_disposition": "RANKED",
        "candidate_sha256": "sha256:" + candidate_hash.hex(),
        "constraint_disposition": "PASS",
        "score": f"{score_ppm / 1_000_000:.6f}",
        "score_ppm": score_ppm,
        "seed": arguments.seed,
        "target_sha256": "sha256:" + target_hash.hex(),
    }
    print(json.dumps(output, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
