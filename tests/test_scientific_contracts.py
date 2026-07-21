import unittest

from src.pipeline import (
    ActorAssertion, ActorKind, AssertionSource, AuthorityKind, AuthorityScope,
    ContractError, Stage, StageBoundary, StageRecord, byte_digest, canonical_json,
    command_digest, content_record, deterministic_id, event_frame_hash,
    normalize_question,
)
from src.pipeline.scientific_contracts import (
    VerificationStatus, actor_assertion_from_mapping, external_reference_from_mapping,
    performer_from_mapping, stage_boundary_from_mapping, validate_adjudication_payload,
    validate_continue_payload, validate_disposition_payload, validate_export_payload,
    validate_protocol_action, validate_result_submit_payload, validate_supersede_payload,
)

ACTOR = {
    "actor_kind": "human",
    "display_name": "Operator",
    "organization": None,
    "role": "operator",
    "assertion_source": "operator_entry",
    "verification_status": "operator_asserted_unverified",
    "authority_scope": {"kind": "none", "scope": None},
    "external_reference": None,
}
PERFORMER = {
    "kind": "human",
    "name": "Operator",
    "version": None,
    "external_reference": None,
}
EXTERNAL_REFERENCE = {
    "reference_type": "lab_log",
    "issuer": "External Lab",
    "title": "Completed run",
    "uri_or_identifier": "lab-log-1",
    "content_hash": "sha256:" + "b" * 64,
    "assertion_source": "external_reference",
    "verification_status": "external_reference_unverified",
    "authority_scope": {"kind": "externally_asserted", "scope": "laboratory"},
}


def execution_accountability_payload():
    return {
        "expected_revision": 0,
        "requirement_id": "responsibility_requirement_00000000000000000000000000000000",
        "scope_hash": "sha256:" + "0" * 64,
        "actor": ACTOR,
        "asserted_at": "2026-07-19T00:00:00.000000Z",
        "status": "satisfied",
        "rationale": "external execution is outside this system",
        "details": {
            "proposal_id": "proposal_00000000000000000000000000000000",
            "proposal_hash": "sha256:" + "1" * 64,
            "handoff_owner": ACTOR,
            "execution_boundary": {"kind": "export_only", "description": "external handoff only"},
        },
    }


def adjudication_payload():
    return {
        "expected_revision": 0,
        "mode": "create",
        "assessment": {
            "claim_ids": ["claim_00000000000000000000000000000000"],
            "result_ids": ["result_00000000000000000000000000000000"],
            "analysis_stage_id": "stage_00000000000000000000000000000000",
            "analysis_artifact_ids": ["artifact_00000000000000000000000000000000"],
            "model_confidence": None,
            "evidence_quality": "unknown",
            "validation_level": "V1",
            "result_outcome": "inconclusive",
            "assessment_state": "pending",
            "applicability": "applicable",
            "covered_scope": "reported result",
            "method": "human assessment",
            "checks": ["reviewed record"],
            "assessor": ACTOR,
            "qualifications": [{"kind": "subject_matter", "asserted_unverified": True}],
            "validation_policy_id": "muchanipo.validation.general",
            "validation_policy_version": "1.0.0",
            "validation_policy_reference": None,
            "rationale": "asserted assessment",
        },
    }
def assessment_transition_payload():
    return {
        "expected_revision": 0,
        "mode": "transition",
        "assessment_id": "assessment_00000000000000000000000000000000",
        "from_state": "pending",
        "to_state": "accepted",
        "claim_ids": ["claim_00000000000000000000000000000000"],
        "result_ids": ["result_00000000000000000000000000000000"],
        "analysis_stage_id": "stage_00000000000000000000000000000000",
        "analysis_artifact_ids": ["artifact_00000000000000000000000000000000"],
        "actor": ACTOR,
        "qualification_evidence": [{
            "qualification": {"kind": "subject_matter", "asserted_unverified": True},
            "actor": ACTOR,
        }],
        "validation_policy_id": "muchanipo.validation.general",
        "validation_policy_version": "1.0.0",
        "validation_policy_reference": None,
        "rationale": "asserted assessment transition",
    }


def cycle_start_action():
    return {
        "protocol": "muchanipo",
        "protocol_version": "ai-scientist.v1",
        "kind": "action",
        "name": "cycle.start",
        "message_id": "message_00000000000000000000000000000000",
        "cycle_id": None,
        "correlation_id": "message_00000000000000000000000000000000",
        "causation_id": None,
        "sequence": 0,
        "revision": 0,
        "idempotency_key": "start-1",
        "timestamp": "2026-07-19T00:00:00.000000Z",
        "payload": {
            "creation_idempotency_key": "start-1",
            "expected_revision": 0,
            "raw_question": "Does this work?",
            "contract_version": "ai-scientist.v1",
            "boundary": {"kind": "cognitive_only", "description": "local work"},
            "creator": ACTOR,
        },
        "extensions": {},
    }
def read_action(name: str, payload: dict) -> dict:
    action = cycle_start_action()
    action.update({"name": name, "cycle_id": None, "idempotency_key": None, "payload": payload})
    return action






class ScientificContractsTests(unittest.TestCase):
    def test_canonical_json_is_stable_and_rejects_unsafe_numbers(self):
        self.assertEqual(canonical_json({"z": "é", "a": 1}), b'{"a":1,"z":"\xc3\xa9"}')
        with self.assertRaises(ContractError):
            canonical_json({"number": 1.5})
        with self.assertRaises(ContractError):
            canonical_json({"number": 9_007_199_254_740_992})
        with self.assertRaises(ContractError):
            canonical_json({1: "integer key", "1": "string key"})

    def test_root_action_coordinates_and_idempotency_bindings_are_exact(self):
        action = cycle_start_action()
        validate_protocol_action(action)
        invalid_actions = []
        for field, value in (
            ("correlation_id", None),
            ("causation_id", action["message_id"]),
            ("sequence", 1),
            ("revision", 1),
            ("idempotency_key", None),
        ):
            invalid_actions.append({**action, field: value})
        invalid_actions.append({
            **action,
            "payload": {**action["payload"], "creation_idempotency_key": "different-key"},
        })
        for invalid in invalid_actions:
            with self.subTest(invalid=invalid), self.assertRaises(ContractError):
                validate_protocol_action(invalid)

    def test_mapping_parsers_reject_lossy_scalars_and_accept_exact_values(self):
        self.assertEqual(actor_assertion_from_mapping(ACTOR), ACTOR)
        self.assertEqual(external_reference_from_mapping(EXTERNAL_REFERENCE), EXTERNAL_REFERENCE)
        self.assertEqual(stage_boundary_from_mapping({"kind": "export_only", "description": "handoff"})["kind"],
                         "export_only")
        self.assertEqual(performer_from_mapping(PERFORMER), PERFORMER)

        invalid_actor_values = (
            {**ACTOR, "display_name": 7},
            {**ACTOR, "organization": ""},
            {**ACTOR, "role": 7},
            {**ACTOR, "assertion_source": 7},
            {**ACTOR, "authority_scope": {"kind": "none", "scope": "not null"}},
        )
        for invalid in invalid_actor_values:
            with self.assertRaises(ContractError):
                actor_assertion_from_mapping(invalid)
        for field in ("reference_type", "issuer", "title", "uri_or_identifier", "content_hash",
                      "assertion_source", "verification_status"):
            with self.subTest(field=field), self.assertRaises(ContractError):
                external_reference_from_mapping({**EXTERNAL_REFERENCE, field: 7})
        with self.assertRaises(ContractError):
            external_reference_from_mapping({
                **EXTERNAL_REFERENCE,
                "authority_scope": {"kind": "externally_asserted", "scope": 7},
            })
        for invalid in (
            {"kind": 7, "description": "handoff"},
            {"kind": "export_only", "description": 7},
            {**PERFORMER, "kind": 7},
            {**PERFORMER, "name": 7},
            {**PERFORMER, "version": 7},
        ):
            with self.assertRaises(ContractError):
                if set(invalid) == {"kind", "description"}:
                    stage_boundary_from_mapping(invalid)
                else:
                    performer_from_mapping(invalid)

    def test_execution_accountability_requires_valid_owner_and_export_only_boundary(self):
        payload = execution_accountability_payload()
        validate_disposition_payload("execution_accountability", payload)
        with self.assertRaises(ContractError):
            validate_disposition_payload("execution_accountability", {
                **payload,
                "details": {**payload["details"], "handoff_owner": {**ACTOR, "display_name": 7}},
            })
        with self.assertRaises(ContractError):
            validate_disposition_payload("execution_accountability", {
                **payload,
                "details": {
                    **payload["details"],
                    "execution_boundary": {"kind": "cognitive_only", "description": "local work"},
                },
            })

    def test_qualifications_must_be_explicitly_asserted_unverified(self):
        payload = adjudication_payload()
        validate_adjudication_payload(payload)
        with self.assertRaises(ContractError):
            validate_adjudication_payload({
                **payload,
                "assessment": {
                    **payload["assessment"],
                    "qualifications": [{"kind": "subject_matter", "asserted_unverified": False}],
                },
            })
    def test_strict_read_payloads_are_closed_and_typed(self):
        client_id = "client_00000000000000000000000000000000"
        export_payload = {
            "client_instance_id": client_id,
            "request_ordinal": 1,
            "export_id": "handoff_00000000000000000000000000000000",
            "include_archive_bytes": False,
        }
        report_payload = {
            "client_instance_id": client_id,
            "request_ordinal": 2,
            "cycle_id": "cycle_00000000000000000000000000000000",
            "at_revision": 3,
            "format": "canonical_json",
            "include_status_overlay": True,
        }
        validate_protocol_action(read_action("export.get", export_payload))
        validate_protocol_action(read_action("report.render", report_payload))
        for payload in (
            {**export_payload, "extra": True},
            {**export_payload, "include_archive_bytes": 1},
            {**report_payload, "format": "text"},
            {**report_payload, "at_revision": True},
            {**report_payload, "include_status_overlay": None},
        ):
            with self.assertRaises(ContractError):
                validate_protocol_action(read_action(
                    "export.get" if "export_id" in payload else "report.render", payload,
                ))
        with self.assertRaises(ContractError):
            invalid = read_action("report.render", report_payload)
            invalid["idempotency_key"] = "read-key"
            validate_protocol_action(invalid)
    def test_cycle_start_requires_exact_zero_revision_and_frozen_contract_version(self):
        action = cycle_start_action()
        validate_protocol_action(action)
        for expected_revision in (True, 1):
            with self.subTest(expected_revision=expected_revision), self.assertRaises(ContractError):
                validate_protocol_action({
                    **action,
                    "payload": {**action["payload"], "expected_revision": expected_revision},
                })
        for contract_version in ("", "ai-scientist.v2", True):
            with self.subTest(contract_version=contract_version), self.assertRaises(ContractError):
                validate_protocol_action({
                    **action,
                    "payload": {**action["payload"], "contract_version": contract_version},
                })

    def test_assessment_transition_requires_closed_asserted_unverified_evidence(self):
        payload = assessment_transition_payload()
        validate_adjudication_payload(payload)
        invalid_evidence = (
            ["unstructured"],
            [{"qualification": {"kind": "subject_matter", "asserted_unverified": True}}],
            [{"qualification": {"kind": "subject_matter", "asserted_unverified": False}, "actor": ACTOR}],
            [{
                "qualification": {"kind": "subject_matter", "asserted_unverified": True},
                "actor": {**ACTOR, "verification_status": "verified"},
            }],
            [{
                "qualification": {"kind": "subject_matter", "asserted_unverified": True},
                "actor": ACTOR,
                "extra": "rejected",
            }],
        )
        for evidence in invalid_evidence:
            with self.subTest(evidence=evidence), self.assertRaises(ContractError):
                validate_adjudication_payload({**payload, "qualification_evidence": evidence})

    def test_question_normalization_known_vector(self):
        self.assertEqual(normalize_question("\u00a0A\r\nCafe\u0301\u2003"), "A Café")

    def test_question_normalization_uses_pinned_unicode_authority(self):
        import unicodedata2

        from src.pipeline.scientific_contracts import NORMALIZATION_UNICODE_VERSION

        self.assertEqual(NORMALIZATION_UNICODE_VERSION, "15.1.0")
        self.assertEqual(unicodedata2.unidata_version, NORMALIZATION_UNICODE_VERSION)

    def test_identity_and_content_preimage_exclude_own_identifiers(self):
        seed = {"cycle_id": "cycle_0123456789abcdef0123456789abcdef", "producer_id": "model", "logical_ordinal": 1, "parent_ids": []}
        one = deterministic_id("artifact", seed)
        two = deterministic_id("artifact", seed)
        self.assertEqual(one, two)
        record = content_record("artifact", {"title": "frozen"}, seed)
        self.assertEqual(record["content_hash"], byte_digest(canonical_json({"title": "frozen"})))
        with self.assertRaises(ContractError):
            content_record("artifact", {"id": one}, seed)

    def test_command_digest_includes_idempotency_key(self):
        payload = {"expected_revision": 0}
        self.assertNotEqual(command_digest("cycle.start", None, "first", payload), command_digest("cycle.start", None, "second", payload))

    def test_frame_hash_omits_only_frame_hash(self):
        frame = {"event": {"sequence": 1}, "marker": "committed", "frame_hash": "sha256:" + "0" * 64}
        expected = event_frame_hash(frame)
        self.assertEqual(expected, event_frame_hash({**frame, "frame_hash": expected}))
        self.assertNotEqual(expected, event_frame_hash({**frame, "marker": "other", "frame_hash": expected}))

    def test_actor_assurance_and_local_execution_boundary(self):
        actor = ActorAssertion(ActorKind.HUMAN, "Operator", None, None, AssertionSource.OPERATOR_ENTRY,
                               VerificationStatus.OPERATOR_ASSERTED_UNVERIFIED, AuthorityScope(AuthorityKind.NONE, None), None)
        self.assertEqual(actor.verification_status, "operator_asserted_unverified")
        local = StageRecord("cycle_0123456789abcdef0123456789abcdef", Stage.X, 1, "muchanipo", "not_run", "not_run", None, (), "not_run", StageBoundary("export_only", "external handoff only"), None, None, (), "proposal_0123456789abcdef0123456789abcdef", "sha256:" + "a" * 64, (), None, None)
        self.assertEqual(local.status, "not_run")
        with self.assertRaises(ContractError):
            StageRecord(local.cycle_id, Stage.X, 2, "muchanipo", "not_run", "not_run", actor, (), "not_run", local.boundary, None, None, (), local.proposal_id, local.proposal_hash, (), None, None)

    def test_disposition_wire_shape_requires_scope_hash_and_exact_branch_details(self):
        payload = {
            "expected_revision": 0,
            "requirement_id": "responsibility_requirement_00000000000000000000000000000000",
            "scope_hash": "sha256:" + "0" * 64,
            "actor": ACTOR,
            "asserted_at": "2026-07-19T00:00:00.000000Z",
            "status": "satisfied",
            "rationale": "asserted",
            "details": {
                "report_body_id": "report_body_00000000000000000000000000000000",
                "report_body_hash": "sha256:" + "1" * 64,
                "reviewed_exact_bytes": True,
                "limitations_acknowledged": True,
            },
        }
        validate_disposition_payload("final_accountability", payload)
        for invalid in (
            {key: value for key, value in payload.items() if key != "scope_hash"},
            {**payload, "report_body_hash": payload["details"]["report_body_hash"]},
            {**payload, "details": {key: value for key, value in payload["details"].items() if key != "reviewed_exact_bytes"}},
            {**payload, "details": {**payload["details"], "extra": True}},
        ):
            with self.assertRaises(ContractError):
                validate_disposition_payload("final_accountability", invalid)
    def test_supersede_wire_requires_exact_payload_and_validates_all_replacement_roles(self):
        requirement_id = "responsibility_requirement_00000000000000000000000000000000"
        disposition_id = "responsibility_disposition_00000000000000000000000000000000"
        common = {
            "expected_revision": 0, "requirement_id": requirement_id,
            "scope_hash": "sha256:" + "0" * 64, "actor": ACTOR,
            "asserted_at": "2026-07-19T00:00:00.000000Z",
            "status": "satisfied", "rationale": "replacement assertion",
        }
        details = {
            "question_selection": {
                "selected_normalized_question": "Question?", "rejected_alternatives": [],
            },
            "safety_ethics_review": {
                "proposal_id": "proposal_00000000000000000000000000000000",
                "proposal_hash": "sha256:" + "1" * 64, "risk_findings": [],
                "export_only_boundary_confirmed": True,
            },
            "execution_accountability": execution_accountability_payload()["details"],
            "exception_interpretation": {
                "result_ids": [], "result_hashes": [], "deviations": [],
                "no_exception_assertion": True,
            },
            "novelty_value_judgment": {
                "claim_ids": [], "judgment": "novel", "limitations": [],
            },
            "final_accountability": {
                "report_body_id": "report_body_00000000000000000000000000000000",
                "report_body_hash": "sha256:" + "1" * 64,
                "reviewed_exact_bytes": True, "limitations_acknowledged": True,
            },
        }
        for responsibility, branch_details in details.items():
            replacement = {**common, "details": branch_details}
            payload = {
                "expected_revision": 0, "responsibility": responsibility,
                "requirement_id": requirement_id,
                "superseded_disposition_id": disposition_id,
                "rationale": "replace stale sign-off",
                "replacement_disposition": replacement,
            }
            with self.subTest(responsibility=responsibility):
                validate_supersede_payload(payload)
        null_payload = {
            "expected_revision": 0, "responsibility": "question_selection",
            "requirement_id": requirement_id,
            "superseded_disposition_id": disposition_id,
            "rationale": "request a new decision",
            "replacement_disposition": None,
        }
        validate_supersede_payload(null_payload)
        for invalid in (
            {key: value for key, value in null_payload.items() if key != "rationale"},
            {**null_payload, "rationale": ""},
            {**null_payload, "responsibility": "not_a_role"},
            {**null_payload, "replacement_disposition": {**common, "details": {}}},
            {key: value for key, value in null_payload.items()
             if key not in {"rationale", "replacement_disposition"}},
        ):
            with self.assertRaises(ContractError):
                validate_supersede_payload(invalid)

    def test_write_wire_shape_excludes_caller_projection_inputs(self):
        stage_input = {
            "kind": "write.final",
            "accountable_party": ACTOR,
            "performers": [PERFORMER],
            "execution_kind": "cognitive",
            "automation_mode": "manual",
            "boundary": {"kind": "cognitive_only", "description": "local"},
            "started_at": "2026-07-19T00:00:00.000000Z",
            "completed_at": "2026-07-19T00:00:01.000000Z",
            "source_revision": 0,
            "source_artifact_ids": [],
            "claim_ids": [],
            "result_ids": [],
            "analysis_artifact_ids": [],
            "limitations": ["asserted limitation"],
        }
        validate_continue_payload({"expected_revision": 0, "operation": "write.final", "stage_input": stage_input})
        with self.assertRaises(ContractError):
            validate_continue_payload({
                "expected_revision": 0,
                "operation": "write.final",
                "stage_input": {**stage_input, "projection": {"policy_output": {"fabricated": True}}},
            })

    def test_result_submit_wire_names_only_verified_staged_content(self):
        payload = {
            "expected_revision": 0,
            "proposal_id": "proposal_0123456789abcdef0123456789abcdef",
            "proposal_hash": "sha256:" + "c" * 64,
            "supersedes_result_id": None,
            "execution_kind": "physical",
            "accountable_party": ACTOR,
            "performers": [{
                "kind": "organization",
                "name": "External Lab",
                "version": None,
                "external_reference": EXTERNAL_REFERENCE,
            }],
            "started_at": "2026-07-19T00:00:00.000000Z",
            "completed_at": "2026-07-19T01:00:00.000000Z",
            "external_references": [EXTERNAL_REFERENCE],
            "staged_blob_ids": ["external_blob_0123456789abcdef0123456789abcdef"],
            "result_manifest": {"summary": "completed externally"},
            "deviations": [],
        }
        validate_result_submit_payload(payload)
        for forbidden in (
            {"controlled_import": payload},
            {**payload, "staged_files": ["/tmp/result.bin"]},
            {**payload, "staged_batch_id": "external_artifacts_0123456789abcdef0123456789abcdef"},
            {key: value for key, value in payload.items() if key != "started_at"},
        ):
            with self.assertRaises(ContractError):
                validate_result_submit_payload(forbidden)
    def test_export_create_payload_is_exact_and_has_no_report_gate(self):
        payload = {
            "expected_revision": 3,
            "format": "scientific-export.v1",
            "artifact_ids": ["artifact_00000000000000000000000000000000"],
            "report_body_id": None,
            "redaction_profile_id": None,
            "external_reference_ids": [],
        }
        validate_export_payload(payload)
        for invalid in (
            {**payload, "report_body_hash": "sha256:" + "a" * 64},
            {key: value for key, value in payload.items() if key != "redaction_profile_id"},
            {**payload, "format": "markdown"},
        ):
            with self.assertRaises(ContractError):
                validate_export_payload(invalid)
if __name__ == "__main__":
    unittest.main()
