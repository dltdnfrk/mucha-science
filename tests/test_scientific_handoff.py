from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.pipeline.scientific_contracts import Responsibility, byte_digest, canonical_json
from src.pipeline.scientific_cycle import GateUnsatisfied, ScientificCycleReducer
from src.pipeline.scientific_handoff import EXPORT_BOUNDARY, HandoffError, create_export_package




def record(record_id, content):
    return {"id": record_id, "content_hash": byte_digest(canonical_json(content)), "content": content}


def refresh_content_hash(item):
    item["content_hash"] = byte_digest(canonical_json(item["content"]))

HANDOFF_OWNER = {
    "actor_kind": "human",
    "display_name": "External experiment owner",
    "organization": None,
    "role": "owner",
    "assertion_source": "operator_entry",
    "verification_status": "operator_asserted_unverified",
    "authority_scope": {"kind": "none", "scope": None},
    "external_reference": None,
}


def state():
    landscape = record("landscape_1", {"artifact_type": "landscape"})
    hypothesis = record("hypothesis_1", {"artifact_type": "hypothesis"})
    proposal_content = {
        "artifact_type": "proposal", "claim_ids": ["claim_1"], "risks": ["risk"],
        "acceptance_criteria": ["criterion"],
        "handoff_boundary": {"kind": "export_only", "description": "external handoff"},
    }
    claim = record("claim_1", {"artifact_type": "claim", "statement": "claim"})
    proposal = record("proposal_1", proposal_content)
    local_x = record("stage_x_1", {"stage": "X", "status": "not_run", "execution_kind": "not_run"})
    safety_requirement = record("safety_requirement_1", {"responsibility": "safety_ethics_review"})
    execution_requirement = record("execution_requirement_1", {"responsibility": "execution_accountability"})
    question_requirement = record("question_requirement_1", {"responsibility": "question_selection"})
    exception_requirement = record("exception_requirement_1", {"responsibility": "exception_interpretation"})
    novelty_requirement = record("novelty_requirement_1", {"responsibility": "novelty_value_judgment"})
    final_requirement = record("final_requirement_1", {"responsibility": "final_accountability"})
    safety_disposition = record("safety_disposition_1", {"responsibility": "safety_ethics_review", "requirement_id": safety_requirement["id"], "status": "satisfied", "actor": {"display_name": "Ledger safety reviewer"}, "details": {"export_only_boundary_confirmed": True}})
    execution_disposition = record("execution_disposition_1", {"responsibility": "execution_accountability", "requirement_id": execution_requirement["id"], "status": "satisfied", "actor": {"display_name": "Ledger handoff owner"}, "details": {"handoff_owner": HANDOFF_OWNER, "execution_boundary": {"kind": "export_only", "description": "external execution only"}}})
    question_disposition = record("question_disposition_1", {"responsibility": "question_selection", "requirement_id": question_requirement["id"], "status": "satisfied", "actor": {"display_name": "Question reviewer"}, "details": {"selected_normalized_question": "Question?", "rejected_alternatives": []}})
    exception_disposition = record("exception_disposition_1", {"responsibility": "exception_interpretation", "requirement_id": exception_requirement["id"], "status": "satisfied", "actor": {"display_name": "Exception reviewer"}, "details": {}})
    novelty_disposition = record("novelty_disposition_1", {"responsibility": "novelty_value_judgment", "requirement_id": novelty_requirement["id"], "status": "satisfied", "actor": {"display_name": "Novelty reviewer"}, "details": {}})
    final_disposition = record("final_disposition_1", {"responsibility": "final_accountability", "requirement_id": final_requirement["id"], "status": "satisfied", "actor": {"display_name": "Final reviewer"}, "details": {}})
    requirements = {
        "safety_ethics_review": safety_requirement["id"],
        "execution_accountability": execution_requirement["id"],
        "question_selection": question_requirement["id"],
        "exception_interpretation": exception_requirement["id"],
        "novelty_value_judgment": novelty_requirement["id"],
        "final_accountability": final_requirement["id"],
    }
    dispositions = {
        safety_requirement["id"]: safety_disposition["id"],
        execution_requirement["id"]: execution_disposition["id"],
        question_requirement["id"]: question_disposition["id"],
        exception_requirement["id"]: exception_disposition["id"],
        novelty_requirement["id"]: novelty_disposition["id"],
        final_requirement["id"]: final_disposition["id"],
    }
    return {
        "cycle_id": "cycle_1", "question": "Question?",
        "records": {item["id"]: item for item in (
            landscape, hypothesis, claim, proposal, local_x,
            safety_requirement, execution_requirement, question_requirement, exception_requirement,
            novelty_requirement, final_requirement, safety_disposition, execution_disposition,
            question_disposition, exception_disposition, novelty_disposition, final_disposition,
        )},
        "current": {"landscape": landscape["id"], "hypothesis": hypothesis["id"], "proposal": proposal["id"], "local_x": {proposal["id"]: local_x["id"]}},
        "requirements": requirements, "dispositions": dispositions,
    }


class ScientificHandoffTests(unittest.TestCase):
    def test_deterministic_export_is_export_only_and_read_only(self):
        ledger = state()
        before_export = deepcopy(ledger)
        with tempfile.TemporaryDirectory() as directory:
            first = create_export_package(ledger, directory)
            self.assertEqual(ledger, before_export)
            second = create_export_package(ledger, directory)
            self.assertEqual(ledger, before_export)
            self.assertEqual(first["package_id"], second["package_id"])
            manifest = first["manifest"]
            self.assertEqual(manifest["boundary"]["kind"], "export_only")
            self.assertEqual(manifest["boundary"]["statement"], EXPORT_BOUNDARY)
            self.assertEqual(manifest["lineage"]["local_x"]["status"], "not_run")
            self.assertEqual(manifest["ledger_gates"]["safety_ethics_review"]["disposition_id"], "safety_disposition_1")
            self.assertEqual(manifest["ledger_gates"]["execution_accountability"]["disposition_id"], "execution_disposition_1")
            self.assertIn("does not authorize, schedule, command, or execute", EXPORT_BOUNDARY)
    def test_archive_is_deterministic_and_orphan_staging_is_not_discoverable(self):
        ledger = state()
        with tempfile.TemporaryDirectory() as directory:
            orphan = Path(directory) / ".tmp-export-orphan"
            orphan.mkdir()
            (orphan / "partial").write_bytes(b"partial")
            first = create_export_package(ledger, directory)
            archive = (Path(first["path"]) / "archive.zip").read_bytes()
            second = create_export_package(ledger, directory)
            self.assertEqual(archive, (Path(second["path"]) / "archive.zip").read_bytes())
            self.assertEqual(first["archive_hash"], byte_digest(archive))
            self.assertEqual(first["byte_length"], len(archive))
            self.assertTrue(first["archive_blob_id"].startswith("blob_"))
            self.assertEqual(
                first["manifest"]["files"],
                sorted(first["manifest"]["files"], key=lambda entry: entry["relative_path"]),
            )
            self.assertFalse((Path(directory) / ".tmp-export-orphan" / "manifest.json").exists())
    def test_failed_publish_leaves_no_visible_export_and_retry_reuses_bytes(self):
        ledger = state()
        with tempfile.TemporaryDirectory() as directory:
            with patch(
                "src.pipeline.scientific_handoff._write_fsynced",
                side_effect=OSError("simulated crash before publish"),
            ):
                with self.assertRaisesRegex(OSError, "simulated crash before publish"):
                    create_export_package(ledger, directory)
            self.assertEqual(
                [entry for entry in Path(directory).iterdir() if not entry.name.startswith(".")],
                [],
            )
            package = create_export_package(ledger, directory)
            retry = create_export_package(ledger, directory)
            self.assertEqual(package["package_id"], retry["package_id"])
            self.assertEqual(package["archive_hash"], retry["archive_hash"])

    def test_archive_tampering_is_rejected_as_existing_package_corruption(self):
        ledger = state()
        with tempfile.TemporaryDirectory() as directory:
            package = create_export_package(ledger, directory)
            archive = Path(package["path"]) / "archive.zip"
            archive.write_bytes(b"not a zip archive")
            with self.assertRaisesRegex(HandoffError, "^existing export package conflicts with deterministic inputs$"):
                create_export_package(ledger, directory)

    def test_export_rejects_current_local_x_that_has_run(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = state()
            local_x = invalid["records"]["stage_x_1"]
            local_x["content"]["status"] = "completed"
            local_x["content"]["execution_kind"] = "completed"
            refresh_content_hash(local_x)
            with self.assertRaisesRegex(HandoffError, "^current proposal requires local X=not_run$"):
                create_export_package(invalid, directory)

    def test_export_requires_current_satisfied_safety_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = state()
            disposition = invalid["records"]["safety_disposition_1"]
            disposition["content"]["status"] = "declined"
            refresh_content_hash(disposition)
            with self.assertRaisesRegex(
                HandoffError,
                "^current safety_ethics_review disposition is not satisfied$",
            ):
                create_export_package(invalid, directory)

    def test_export_requires_current_satisfied_execution_accountability_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = state()
            disposition = invalid["records"]["execution_disposition_1"]
            disposition["content"]["status"] = "declined"
            refresh_content_hash(disposition)
            with self.assertRaisesRegex(
                HandoffError,
                "^current execution_accountability disposition is not satisfied$",
            ):
                create_export_package(invalid, directory)
    def test_export_rejects_satisfied_gates_without_export_only_semantics(self):
        with tempfile.TemporaryDirectory() as directory:
            invalid = state()
            invalid["records"]["safety_disposition_1"]["content"]["details"]["export_only_boundary_confirmed"] = False
            refresh_content_hash(invalid["records"]["safety_disposition_1"])
            with self.assertRaisesRegex(HandoffError, "does not confirm export_only boundary"):
                create_export_package(invalid, directory)

            invalid = state()
            invalid["records"]["execution_disposition_1"]["content"]["details"]["execution_boundary"]["kind"] = "computational_only"
            refresh_content_hash(invalid["records"]["execution_disposition_1"])
            with self.assertRaisesRegex(HandoffError, "is not export_only"):
                create_export_package(invalid, directory)


    def test_completion_rejects_satisfied_disposition_without_required_confirmations(self):
        report_hash = "sha256:" + "a" * 64
        state = {
            "current": {"final_report": "stage_1"},
            "records": {
                "stage_1": {"id": "stage_1", "content": {"report_body_id": "body_1"}},
                "body_1": {"id": "body_1", "content": {"body_hash": report_hash}},
                "disposition_1": {
                    "id": "disposition_1",
                    "content": {
                        "status": "satisfied",
                        "details": {
                            "report_body_hash": report_hash,
                            "reviewed_exact_bytes": False,
                            "limitations_acknowledged": True,
                        },
                    },
                },
            },
            "requirements": {Responsibility.FINAL_ACCOUNTABILITY.value: "requirement_1"},
            "dispositions": {"requirement_1": "disposition_1"},
        }
        state["question"] = "Question"
        for responsibility in Responsibility:
            requirement_id = (
                "requirement_1"
                if responsibility is Responsibility.FINAL_ACCOUNTABILITY
                else f"requirement_{responsibility.value}"
            )
            disposition_id = (
                "disposition_1"
                if responsibility is Responsibility.FINAL_ACCOUNTABILITY
                else f"disposition_{responsibility.value}"
            )
            scope_hash = "sha256:" + "b" * 64
            state["requirements"][responsibility.value] = requirement_id
            state["dispositions"][requirement_id] = disposition_id
            state["records"][requirement_id] = {
                "id": requirement_id,
                "content": {"scope_hash": scope_hash},
            }
            if responsibility is not Responsibility.FINAL_ACCOUNTABILITY:
                state["records"][disposition_id] = {
                    "id": disposition_id,
                    "content": {
                        "requirement_id": requirement_id,
                        "responsibility": responsibility.value,
                        "scope_hash": scope_hash,
                        "actor": {"actor_kind": "human"},
                        "status": "satisfied",
                        "details": {
                            "selected_normalized_question": "Question"
                        } if responsibility is Responsibility.QUESTION_SELECTION else {},
                    },
                }
        state["records"]["disposition_1"]["content"].update({
            "requirement_id": "requirement_1",
            "responsibility": Responsibility.FINAL_ACCOUNTABILITY.value,
            "scope_hash": state["records"]["requirement_1"]["content"]["scope_hash"],
            "actor": {"actor_kind": "human"},
        })
        data = {
            "report_stage_id": "stage_1",
            "report_body_id": "body_1",
            "report_body_hash": report_hash,
            "final_accountability_requirement_id": "requirement_1",
            "final_accountability_disposition_id": "disposition_1",
        }
        with self.assertRaisesRegex(GateUnsatisfied, "^final accountability is not current$"):
            ScientificCycleReducer()._complete(deepcopy(state), data)

        state["records"]["disposition_1"]["content"]["details"]["reviewed_exact_bytes"] = True
        state["records"]["disposition_1"]["content"]["details"]["limitations_acknowledged"] = False
        with self.assertRaisesRegex(GateUnsatisfied, "^final accountability is not current$"):
            ScientificCycleReducer()._complete(deepcopy(state), data)
    def test_assessment_transition_replaces_current_projection_and_keeps_history(self):
        assessment_id = "assessment_00000000000000000000000000000000"
        common = {
            "claim_ids": ["claim_00000000000000000000000000000000"],
            "result_ids": ["result_00000000000000000000000000000000"],
            "analysis_stage_id": "stage_00000000000000000000000000000000",
            "analysis_artifact_ids": ["artifact_00000000000000000000000000000000"],
            "validation_policy_id": "muchanipo.validation.general",
            "validation_policy_version": "1.0.0",
            "validation_policy_reference": None,
            "model_confidence": 1,
            "evidence_quality": "low",
            "validation_level": "V1",
            "result_outcome": "supports",
            "applicability": "applicable",
            "assessor": HANDOFF_OWNER,
            "qualifications": [{"kind": "subject_matter", "asserted_unverified": True}],
            "methods_and_statistics": False,
            "independent": False,
        }
        original = {"id": assessment_id, "content": common | {"assessment_state": "pending"}}
        state = {
            "cycle_id": "cycle_00000000000000000000000000000000",
            "records": {
                assessment_id: original,
                common["analysis_stage_id"]: {"content": {"artifact_ids": common["analysis_artifact_ids"]}},
            },
            "assessments": {assessment_id: original},
            "current": {
                "claims": common["claim_ids"],
                "results": common["result_ids"],
                "analysis": common["analysis_stage_id"],
            },
        }
        payload = common | {
            "mode": "transition",
            "assessment_id": assessment_id,
            "from_state": "pending",
            "to_state": "accepted",
            "actor": HANDOFF_OWNER,
            "qualification_evidence": [],
            "rationale": "review complete",
        }
        with patch("src.pipeline.scientific_cycle.validate_adjudication_payload"):
            reduction = ScientificCycleReducer()._adjudicate(state, payload)
        current = reduction.state["assessments"][assessment_id]
        self.assertEqual(current["content"]["assessment_state"], "accepted")
        self.assertNotEqual(current["id"], assessment_id)
        self.assertEqual(reduction.state["records"][assessment_id]["content"]["assessment_state"], "pending")
        self.assertEqual(reduction.state["records"][reduction.event_payload["transition_id"]]["content"]["to_state"], "accepted")
    def test_rejects_stale_package_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            exported = create_export_package(state(), directory)
            manifest = dict(exported["manifest"])
            manifest["lineage"]["claims"][0]["content"]["statement"] = "substituted"
            manifest_path = Path(exported["path"]) / "manifest.json"
            manifest_path.write_bytes(canonical_json(manifest))
            with self.assertRaisesRegex(HandoffError, "^existing export package conflicts with deterministic inputs$"):
                create_export_package(state(), directory)
if __name__ == "__main__":
    unittest.main()
