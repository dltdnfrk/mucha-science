import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.pipeline.scientific_contracts import byte_digest, canonical_json
from src.pipeline.external_result_ingest import (
    ExternalResultIngestError,
    ImportQuota,
    ingest_external_result,
    resolve_staged_external_result,
    stage_external_result,
)


PROPOSAL_ID = "proposal_0123456789abcdef0123456789abcdef"
PROPOSAL = {"artifact_type": "proposal"}
PROPOSAL_HASH = byte_digest(canonical_json(PROPOSAL))


def ledger():
    return {"cycle_id": "cycle_0123456789abcdef0123456789abcdef", "current": {"proposal": PROPOSAL_ID}, "records": {PROPOSAL_ID: {"content_hash": PROPOSAL_HASH, "content": PROPOSAL}, "result_prior": {"record_type": "result", "content": {"proposal_id": PROPOSAL_ID}}}}


def accountability():
    scope = {"kind": "none", "scope": None}
    return (
        {"actor_kind": "human", "display_name": "External operator", "organization": None, "role": None, "assertion_source": "operator_entry", "verification_status": "operator_asserted_unverified", "authority_scope": scope, "external_reference": None},
        {"reference_type": "lab_log", "issuer": "External Lab", "title": "Completed run", "uri_or_identifier": "lab-log-1", "content_hash": "sha256:" + "b" * 64, "assertion_source": "external_reference", "verification_status": "external_reference_unverified", "authority_scope": scope},
    )


class ExternalResultIngestTests(unittest.TestCase):
    def _ingest(self, staged, approved, artifacts, **overrides):
        actor, reference = accountability()
        arguments = {"state": ledger(), "staged_files": [staged], "approved_roots": [approved], "artifact_root": artifacts,
                     "proposal_id": PROPOSAL_ID, "proposal_hash": PROPOSAL_HASH, "execution_kind": "physical",
                     "accountable_party": actor, "accountability_reference": reference, "outcome": "supports",
                     "limitations": ["single run"], "metadata": {"instrument": "external"}}
        arguments.update(overrides)
        return ingest_external_result(**arguments)

    def test_import_keeps_outcome_independent_of_validation_level_and_correction_lineage(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            output = Path(directory) / "artifacts"
            staged = root / "result.bin"; staged.write_bytes(b"external bytes")
            for outcome in ("supports", "refutes", "inconclusive"):
                result = self._ingest(staged, root, output, outcome=outcome, supersedes_result_id="result_prior")
                content = result["result"]["content"]
                self.assertEqual(result["result"]["record_type"], "result")
                self.assertEqual(content["outcome"], outcome)
                self.assertEqual(content["supersedes_result_id"], "result_prior")
                self.assertNotIn("validation_level", content)
    def test_metadata_is_materialized_before_result_record_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            staged = root / "result.bin"; staged.write_bytes(b"external bytes")
            output = Path(directory) / "artifacts"
            for metadata in ({}, {"nested": {"measurements": [1, {"unit": "ms"}]}}):
                with self.subTest(metadata=metadata):
                    result = self._ingest(staged, root, output, metadata=metadata)
                    stored = result["result"]["content"]["metadata"]
                    self.assertIsInstance(stored, dict)
                    self.assertNotIsInstance(stored, type(result))
                    if stored:
                        self.assertIsInstance(stored["nested"], dict)
                        self.assertIsInstance(stored["nested"]["measurements"], list)

    def test_rejects_traversal_symlinks_and_changed_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            output = Path(directory) / "artifacts"
            outside = Path(directory) / "outside.bin"; outside.write_bytes(b"x")
            with self.assertRaisesRegex(ExternalResultIngestError, "^staged artifact is outside approved roots or contains symbolic links$"):
                self._ingest(outside, root, output)
            linked = root / "link.bin"; linked.symlink_to(outside)
            with self.assertRaisesRegex(ExternalResultIngestError, "^staged artifact is outside approved roots or contains symbolic links$"):
                self._ingest(linked, root, output)
            staged = root / "large.bin"; staged.write_bytes(b"1234")
            original_lseek = os.lseek

            def mutate_after_hash(descriptor, offset, origin):
                staged.write_bytes(b"5678")
                return original_lseek(descriptor, offset, origin)

            with patch("src.pipeline.external_result_ingest.os.lseek", side_effect=mutate_after_hash):
                with self.assertRaisesRegex(ExternalResultIngestError, "^staged artifact changed during copy$"):
                    self._ingest(staged, root, output, quota=ImportQuota(max_files=1, max_file_bytes=4, max_total_bytes=4))

    def test_rejects_fifo_under_approved_root_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            fifo = root / "result.fifo"
            os.mkfifo(fifo)
            original_open = os.open

            def open_nonblocking(path, flags, mode=0o777, *, dir_fd=None):
                return original_open(path, flags | os.O_NONBLOCK, mode, dir_fd=dir_fd)

            with patch("src.pipeline.external_result_ingest.os.open", side_effect=open_nonblocking), patch(
                "src.pipeline.external_result_ingest.os.read",
                side_effect=AssertionError("FIFO must be rejected before reading"),
            ):
                with self.assertRaisesRegex(
                    ExternalResultIngestError,
                    "^staged artifact must be a regular file$",
                ):
                    self._ingest(fifo, root, Path(directory) / "artifacts")

    def test_rejects_directory_under_approved_root_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            staged_directory = root / "result-directory"; staged_directory.mkdir()
            with patch(
                "src.pipeline.external_result_ingest.os.read",
                side_effect=AssertionError("directory must be rejected before reading"),
            ):
                with self.assertRaisesRegex(
                    ExternalResultIngestError,
                    "^staged artifact must be a regular file$",
                ):
                    self._ingest(staged_directory, root, Path(directory) / "artifacts")

    def test_requires_complete_accountability_and_nonempty_limitations(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            staged = root / "result.bin"; staged.write_bytes(b"external bytes")
            output = Path(directory) / "artifacts"
            actor, _ = accountability()
            incomplete_actor = dict(actor); incomplete_actor.pop("authority_scope")
            with self.assertRaisesRegex(ExternalResultIngestError, "^accountability assertions must use canonical actor and external-reference contracts$"):
                self._ingest(staged, root, output, accountable_party=incomplete_actor)
            with self.assertRaisesRegex(ExternalResultIngestError, "^outcome and nonempty limitations are required$"):
                self._ingest(staged, root, output, limitations=[])

    def test_retries_verified_batch_and_rejects_conflicting_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            staged = root / "result.bin"; staged.write_bytes(b"external bytes")
            output = Path(directory) / "artifacts"
            first = self._ingest(staged, root, output)
            second = self._ingest(staged, root, output)
            self.assertEqual(first["artifact_batch"]["manifest_hash"], second["artifact_batch"]["manifest_hash"])
            batch = Path(first["artifact_batch"]["path"])
            (batch / "0000.bin").write_bytes(b"tampered")
            with self.assertRaisesRegex(ExternalResultIngestError, "^existing artifact batch conflicts with deterministic import$"):
                self._ingest(staged, root, output)
    def test_rejects_non_string_and_colliding_metadata_keys_before_artifact_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            staged = root / "result.bin"; staged.write_bytes(b"external bytes")
            output = Path(directory) / "artifacts"
            for metadata in ({1: "numeric key"}, {1: "numeric key", "1": "string key"}):
                with self.assertRaisesRegex(ExternalResultIngestError, "metadata"):
                    self._ingest(staged, root, output, metadata=metadata)
            self.assertFalse(output.exists())


    def test_rejects_intermediate_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            outside = Path(directory) / "outside"; outside.mkdir()
            staged = outside / "result.bin"; staged.write_bytes(b"external bytes")
            (root / "nested").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ExternalResultIngestError, "^staged artifact is outside approved roots or contains symbolic links$"):
                self._ingest(root / "nested" / "result.bin", root, Path(directory) / "artifacts")
    def test_rejects_artifact_count_over_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            output = Path(directory) / "artifacts"
            first = root / "first.bin"; first.write_bytes(b"a")
            second = root / "second.bin"; second.write_bytes(b"b")
            with self.assertRaisesRegex(ExternalResultIngestError, "^artifact count exceeds quota$"):
                self._ingest(
                    first,
                    root,
                    output,
                    staged_files=[first, second],
                    quota=ImportQuota(max_files=1, max_file_bytes=2, max_total_bytes=2),
                )

    def test_rejects_per_file_bytes_over_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            output = Path(directory) / "artifacts"
            staged = root / "large.bin"; staged.write_bytes(b"123")
            with self.assertRaisesRegex(ExternalResultIngestError, "^artifact bytes exceed quota$"):
                self._ingest(
                    staged,
                    root,
                    output,
                    quota=ImportQuota(max_files=1, max_file_bytes=2, max_total_bytes=3),
                )

    def test_rejects_aggregate_artifact_bytes_over_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            output = Path(directory) / "artifacts"
            first = root / "first.bin"; first.write_bytes(b"ab")
            second = root / "second.bin"; second.write_bytes(b"cd")
            with self.assertRaisesRegex(ExternalResultIngestError, "^artifact bytes exceed quota$"):
                self._ingest(
                    first,
                    root,
                    output,
                    staged_files=[first, second],
                    quota=ImportQuota(max_files=2, max_file_bytes=2, max_total_bytes=3),
                )


    def test_rejects_lexical_parent_segment_before_descriptor_traversal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            staged = root / "result.bin"; staged.write_bytes(b"external bytes")
            traversal = root / "nested" / ".." / "result.bin"
            with self.assertRaisesRegex(ExternalResultIngestError, "^staged artifact contains lexical parent traversal$"):
                self._ingest(traversal, root, Path(directory) / "artifacts")

    def test_batch_identity_uses_opened_content_not_source_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            output = Path(directory) / "artifacts"
            first_path = root / "first.bin"; first_path.write_bytes(b"same bytes")
            second_path = root / "second.bin"; second_path.write_bytes(b"same bytes")
            first = self._ingest(first_path, root, output)
            same_content = self._ingest(second_path, root, output)
            self.assertEqual(first["artifact_batch"]["id"], same_content["artifact_batch"]["id"])
            first_path.write_bytes(b"changed!!!")
            changed_content = self._ingest(first_path, root, output)
            self.assertNotEqual(first["artifact_batch"]["id"], changed_content["artifact_batch"]["id"])

    def test_closes_opened_source_on_pre_copy_hash_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            staged = root / "result.bin"; staged.write_bytes(b"external bytes")
            opened: list[int] = []
            closed: list[int] = []
            approved_source = ingest_external_result.__globals__["_approved_source"]
            original_close = os.close

            def capture_source(*args):
                source_fd, size = approved_source(*args)
                opened.append(source_fd)
                return source_fd, size

            def capture_close(descriptor):
                closed.append(descriptor)
                return original_close(descriptor)

            with patch("src.pipeline.external_result_ingest._approved_source", side_effect=capture_source):
                with patch("src.pipeline.external_result_ingest.os.lseek", side_effect=OSError("injected")):
                    with patch("src.pipeline.external_result_ingest.os.close", side_effect=capture_close):
                        with self.assertRaisesRegex(OSError, "^injected$"):
                            self._ingest(staged, root, Path(directory) / "artifacts")
            self.assertEqual(len(opened), 1)
            self.assertIn(opened[0], closed)

    def test_rejects_stale_same_path_before_existing_batch_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            staged = root / "result.bin"; staged.write_bytes(b"external bytes")
            output = Path(directory) / "artifacts"
            first = self._ingest(staged, root, output)
            batch = Path(first["artifact_batch"]["path"])
            original_exists = Path.exists

            def mutate_when_batch_is_checked(path):
                if path == batch:
                    staged.write_bytes(b"changed bytes!")
                return original_exists(path)

            with patch("src.pipeline.external_result_ingest.Path.exists", autospec=True, side_effect=mutate_when_batch_is_checked):
                with self.assertRaisesRegex(ExternalResultIngestError, "^existing artifact batch conflicts with deterministic import$"):
                    self._ingest(staged, root, output)
    def test_rejects_existing_batch_with_manifest_for_other_staged_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            staged = root / "result.bin"; staged.write_bytes(b"external bytes")
            output = Path(directory) / "artifacts"
            first = self._ingest(staged, root, output)
            batch = Path(first["artifact_batch"]["path"])
            manifest = (batch / "manifest.json").read_bytes()
            (batch / "manifest.json").write_bytes(manifest.replace(b"0000.bin", b"9999.bin"))
            with self.assertRaisesRegex(ExternalResultIngestError, "^existing artifact batch conflicts with deterministic import$"):
                self._ingest(staged, root, output)
    def test_rejects_existing_batch_with_extra_manifest_field(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "approved"; root.mkdir()
            output = Path(directory) / "artifacts"
            staged = root / "result.bin"; staged.write_bytes(b"external bytes")
            first = self._ingest(staged, root, output)
            batch = Path(first["artifact_batch"]["path"])
            manifest = json.loads((batch / "manifest.json").read_bytes())
            manifest["unexpected"] = True
            (batch / "manifest.json").write_bytes(canonical_json(manifest))

            with self.assertRaisesRegex(
                ExternalResultIngestError,
                "^existing artifact batch conflicts with deterministic import$",
            ):
                self._ingest(staged, root, output)
    def test_local_staging_is_confined_immutable_and_retries_exactly(self):
        with tempfile.TemporaryDirectory() as directory:
            approved = Path(directory) / "approved"; approved.mkdir()
            store = Path(directory) / "staging"
            source = approved / "result.bin"; source.write_bytes(b"external bytes")
            first = stage_external_result(
                staged_files=[source],
                approved_roots=[approved],
                staging_root=store,
            )
            second = stage_external_result(
                staged_files=[source],
                approved_roots=[approved],
                staging_root=store,
            )
            self.assertEqual(first, second)
            resolved = resolve_staged_external_result(staging_root=store, **first)
            self.assertEqual([path.read_bytes() for path in resolved], [b"external bytes"])
            with self.assertRaisesRegex(ExternalResultIngestError, "unknown or tampered"):
                resolve_staged_external_result(
                    staging_root=store,
                    staged_batch_id=first["staged_batch_id"],
                    staged_manifest_hash="sha256:" + "0" * 64,
                    staged_blob_ids=first["staged_blob_ids"],
                    staged_artifact_digests=first["staged_artifact_digests"],
                )
            with self.assertRaisesRegex(ExternalResultIngestError, "unknown or tampered"):
                resolve_staged_external_result(
                    staging_root=store,
                    staged_batch_id=first["staged_batch_id"],
                    staged_manifest_hash=first["staged_manifest_hash"],
                    staged_blob_ids=("external_blob_00000000000000000000000000000000",),
                    staged_artifact_digests=first["staged_artifact_digests"],
                )
            (resolved[0]).write_bytes(b"tampered")
            with self.assertRaisesRegex(ExternalResultIngestError, "unknown or tampered"):
                resolve_staged_external_result(staging_root=store, **first)

    def test_local_staging_rejects_traversal_symlink_and_quota(self):
        with tempfile.TemporaryDirectory() as directory:
            approved = Path(directory) / "approved"; approved.mkdir()
            outside = Path(directory) / "outside.bin"; outside.write_bytes(b"x")
            linked = approved / "linked.bin"; linked.symlink_to(outside)
            with self.assertRaisesRegex(ExternalResultIngestError, "symbolic links"):
                stage_external_result(
                    staged_files=[linked],
                    approved_roots=[approved],
                    staging_root=Path(directory) / "staging",
                )
            with self.assertRaisesRegex(ExternalResultIngestError, "parent traversal"):
                stage_external_result(
                    staged_files=[approved / "nested" / ".." / "linked.bin"],
                    approved_roots=[approved],
                    staging_root=Path(directory) / "staging",
                )
            large = approved / "large.bin"; large.write_bytes(b"123")
            with self.assertRaisesRegex(ExternalResultIngestError, "artifact bytes exceed quota"):
                stage_external_result(
                    staged_files=[large],
                    approved_roots=[approved],
                    staging_root=Path(directory) / "staging",
                    quota=ImportQuota(max_files=1, max_file_bytes=2, max_total_bytes=2),
                )
if __name__ == "__main__":
    unittest.main()
