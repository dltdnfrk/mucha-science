from dataclasses import asdict
import unittest

from src.hitl.signoff_core import SignoffCore, SignoffError
from src.pipeline.scientific_contracts import (
    ActorAssertion, ActorKind, AssertionSource, AuthorityKind, AuthorityScope,
    Responsibility, VerificationStatus, byte_digest, canonical_json,
)
from src.report.scientific_projector import (
    ReportProjectionError, ScientificReportProjector, compose_scientific_report_body,
)

from src.pipeline.scientific_cycle import initial_state

CYCLE = "cycle_0123456789abcdef0123456789abcdef"
REPORT = "report_00000000000000000000000000000000"


def operator(name="Operator"):
    return ActorAssertion(ActorKind.HUMAN, name, None, "reviewer",
                          AssertionSource.OPERATOR_ENTRY,
                          VerificationStatus.OPERATOR_ASSERTED_UNVERIFIED,
                          AuthorityScope(AuthorityKind.NONE, None), None)


class ReportAttestationTests(unittest.TestCase):
    def test_all_six_requirements_are_current_and_supersession_preserves_history(self):
        core = SignoffCore(CYCLE)
        self.assertEqual({item.responsibility for item in core.requirements}, set(Responsibility))
        for responsibility in Responsibility:
            if responsibility is Responsibility.FINAL_ACCOUNTABILITY:
                continue
            requirement = core.current_requirement(responsibility)
            details = {}
            if responsibility is Responsibility.EXECUTION_ACCOUNTABILITY:
                details = {
                    "handoff_owner": operator("Handoff owner"),
                    "execution_boundary": {"kind": "cognitive_only", "description": "No physical execution."},
                }
            core.record_disposition(requirement_id=requirement.requirement_id,
                                    responsibility=responsibility, actor=operator(),
                                    asserted_at="2026-07-19T00:00:00.000000Z",
                                    status="satisfied", rationale="asserted review", details=details)
        old = core.current_requirement(Responsibility.QUESTION_SELECTION)
        old_disposition = core.current_disposition(Responsibility.QUESTION_SELECTION)
        replacement = core.supersede(
            Responsibility.QUESTION_SELECTION,
            "claim_set",
            ("claim_11111111111111111111111111111111",),
        )
        self.assertNotEqual(old.requirement_id, replacement.requirement_id)
        self.assertEqual(core.current_requirement(Responsibility.QUESTION_SELECTION), replacement)
        self.assertEqual(replacement.supersedes_requirement_id, old.requirement_id)
        self.assertIn(old, core.requirements)
        self.assertIn(replacement, core.requirements)
        self.assertEqual(len(core.requirements), len(Responsibility) + 1)
        self.assertEqual(
            [item for item in core.dispositions if item.requirement_id == old.requirement_id],
            [old_disposition],
        )
        self.assertIsNone(core.current_disposition(Responsibility.QUESTION_SELECTION))
        self.assertEqual(len(core.dispositions), 5)
    def test_caller_final_accountability_is_rejected_in_mixed_input_containers(self):
        for output_name, reducer_output, policy_output, hitl_output in (
            (
                "reducer",
                {"outcomes": [{"nested": {"final_accountability": "satisfied"}}]},
                {"support": "mixed"},
                {"question_selection": "satisfied"},
            ),
            (
                "policy",
                {"outcome": "mixed"},
                {"reviews": [{"nested": {"final_accountability_status": "satisfied"}}]},
                {"question_selection": "satisfied"},
            ),
            (
                "hitl",
                {"outcome": "mixed"},
                {"support": "mixed"},
                {"groups": [{"nested": {"final_accountability": "satisfied"}}]},
            ),
        ):
            with self.subTest(output_name=output_name), self.assertRaisesRegex(
                ReportProjectionError,
                "^report body must not contain final accountability$",
            ):
                compose_scientific_report_body(
                    cycle_id=CYCLE,
                    source_revision=7,
                    reducer_output=reducer_output,
                    policy_output=policy_output,
                    hitl_output=hitl_output,
                    limitations=("Evidence is limited.",),
                )
    def test_body_content_is_frozen_from_exact_canonical_bytes(self):
        reducer_output = {"nested": {"values": [{"value": "original"}]}}
        policy_output = {"nested": {"status": "pending"}}
        hitl_output = {"nested": {"responsibility": "question_selection"}}
        body = compose_scientific_report_body(
            cycle_id=CYCLE,
            source_revision=7,
            reducer_output=reducer_output,
            policy_output=policy_output,
            hitl_output=hitl_output,
            limitations=("Evidence is limited.",),
        )

        reducer_output["nested"]["values"][0]["value"] = "mutated"
        policy_output["nested"]["status"] = "accepted"
        hitl_output["nested"]["responsibility"] = "final_accountability"

        self.assertEqual(body.content["scientific"]["nested"]["values"][0]["value"], "original")
        self.assertEqual(body.content["validation"]["nested"]["status"], "pending")
        self.assertEqual(body.content["responsibilities"]["nested"]["responsibility"], "question_selection")
        self.assertEqual(body.body_hash, byte_digest(body.body_utf8))
        self.assertEqual(canonical_json(body.content) + b"\n", body.body_utf8)
        with self.assertRaises(TypeError):
            body.content["scientific"]["nested"]["values"][0]["value"] = "mutated"

    def test_state_projection_excludes_opaque_final_accountability_history(self):
        state = initial_state(CYCLE, "Question?", "ai-scientist.v1",
                              {"kind": "cognitive_only", "description": "cognitive only"},
                              {"actor_kind": "human", "display_name": "Operator", "organization": None,
                               "role": "reviewer", "assertion_source": "operator_entry",
                               "verification_status": "operator_asserted_unverified",
                               "authority_scope": {"kind": "none", "scope": None}, "external_reference": None})
        final_requirement_id = state["requirements"]["final_accountability"]
        question_requirement_id = state["requirements"]["question_selection"]
        state["records"]["opaque_final_disposition"] = {
            "record_type": "responsibility_disposition",
            "content": {"responsibility": "final_accountability"},
        }
        state["records"]["question_disposition"] = {
            "record_type": "responsibility_disposition",
            "content": {
                "responsibility": "question_selection",
                "requirement_id": question_requirement_id,
                "scope_hash": state["records"][question_requirement_id]["content"]["scope_hash"],
            },
        }
        state["dispositions"] = {
            final_requirement_id: "opaque_final_disposition",
            question_requirement_id: "question_disposition",
        }
        body = ScientificReportProjector().compose_from_state(
            state=state, source_revision=0, body_kind="interim",
            limitations=("Evidence is limited.",),
        )
        self.assertNotIn(b"final_accountability", body.body_utf8)
        self.assertNotIn(b"opaque_final_disposition", body.body_utf8)
        self.assertIn(b"question_disposition", body.body_utf8)

    def test_state_projection_rejects_missing_or_malformed_accountability_maps(self):
        state = initial_state(CYCLE, "Question?", "ai-scientist.v1",
                              {"kind": "cognitive_only", "description": "cognitive only"},
                              {"actor_kind": "human", "display_name": "Operator", "organization": None,
                               "role": "reviewer", "assertion_source": "operator_entry",
                               "verification_status": "operator_asserted_unverified",
                               "authority_scope": {"kind": "none", "scope": None}, "external_reference": None})
        projector = ScientificReportProjector()
        for malformed in (
            {key: value for key, value in state.items() if key != "requirements"},
            state | {"requirements": []},
            state | {"dispositions": {"not-a-requirement": 7}},
        ):
            with self.assertRaises(ReportProjectionError):
                projector.compose_from_state(
                    state=malformed, source_revision=0, body_kind="interim",
                    limitations=("Evidence is limited.",),
                )
    def test_state_projection_rejects_stale_disposition_requirement_or_scope(self):
        state = initial_state(CYCLE, "Question?", "ai-scientist.v1",
                              {"kind": "cognitive_only", "description": "cognitive only"},
                              {"actor_kind": "human", "display_name": "Operator", "organization": None,
                               "role": "reviewer", "assertion_source": "operator_entry",
                               "verification_status": "operator_asserted_unverified",
                               "authority_scope": {"kind": "none", "scope": None}, "external_reference": None})
        requirement_id = state["requirements"]["question_selection"]
        for disposition_content in (
            {
                "responsibility": "question_selection",
                "requirement_id": "requirement_superseded",
                "scope_hash": state["records"][requirement_id]["content"]["scope_hash"],
            },
            {
                "responsibility": "question_selection",
                "requirement_id": requirement_id,
                "scope_hash": "sha256:stale",
            },
        ):
            state["records"]["stale_disposition"] = {
                "record_type": "responsibility_disposition",
                "content": disposition_content,
            }
            state["dispositions"] = {requirement_id: "stale_disposition"}
            with self.subTest(disposition_content=disposition_content), self.assertRaisesRegex(
                    ReportProjectionError, "current requirement and scope"):
                ScientificReportProjector().compose_from_state(
                    state=state, source_revision=0, body_kind="interim",
                    limitations=("Evidence is limited.",),
                )
    def test_state_projection_uses_only_explicit_current_assessment_records(self):
        state = initial_state(CYCLE, "Question?", "ai-scientist.v1",
                              {"kind": "cognitive_only", "description": "cognitive only"},
                              {"actor_kind": "human", "display_name": "Operator", "organization": None,
                               "role": "reviewer", "assertion_source": "operator_entry",
                               "verification_status": "operator_asserted_unverified",
                               "authority_scope": {"kind": "none", "scope": None}, "external_reference": None})
        stale = {"id": "assessment_stale", "record_type": "validation_assessment",
                 "content": {"assessment_state": "pending"}}
        current = {"id": "assessment_current", "record_type": "validation_assessment",
                   "content": {"assessment_state": "accepted"}}
        state["records"] |= {stale["id"]: stale, current["id"]: current}
        state["assessments"] = {stale["id"]: current}

        body = ScientificReportProjector().compose_from_state(
            state=state, source_revision=0, body_kind="interim",
            limitations=("Evidence is limited.",),
        )
        self.assertEqual(body.content["validation"], {current["id"]: current["content"]})
        self.assertNotIn(b"assessment_stale", body.body_utf8)

        state["assessments"] = {stale["id"]: stale | {"id": "assessment_missing"}}
        with self.assertRaisesRegex(ReportProjectionError, "current assessment"):
            ScientificReportProjector().compose_from_state(
                state=state, source_revision=0, body_kind="interim",
                limitations=("Evidence is limited.",),
            )

    def test_status_overlay_rejects_impossible_accountability_states(self):
        projector = ScientificReportProjector()
        for status, disposition_id in (
            ("closed", None),
            ("satisfied", None),
            ("satisfied", ""),
            ("pending", "disposition_committed"),
        ):
            with self.subTest(status=status, disposition_id=disposition_id), self.assertRaises(ReportProjectionError):
                projector.status_overlay(
                    report_body_id=REPORT, at_revision=7,
                    final_accountability_status=status, disposition_id=disposition_id,
                    generated_at="2026-07-19T00:00:00.000000Z",
                )

    def test_final_accountability_transition_changes_only_detached_overlay(self):
        projector = ScientificReportProjector()
        body = projector.compose(
            cycle_id=CYCLE,
            source_revision=7,
            reducer_output={"outcome": "mixed"},
            policy_output={"support": "mixed"},
            hitl_output={"question_selection": "satisfied"},
            limitations=("Evidence is limited.",),
        )
        self.assertTrue(body.body_utf8.endswith(b"\n"))
        self.assertNotIn(b"final_accountability", body.body_utf8)
        core = SignoffCore(CYCLE)
        requirement = core.rescope(
            Responsibility.FINAL_ACCOUNTABILITY, "report_body", (REPORT, body.body_hash),
        )
        pending = projector.status_overlay(
            report_body_id=REPORT,
            at_revision=7,
            final_accountability_status="pending",
            disposition_id=None,
            generated_at="2026-07-19T00:00:00.000000Z",
        )
        disposition = core.record_disposition(
            requirement_id=requirement.requirement_id,
            responsibility=Responsibility.FINAL_ACCOUNTABILITY,
            actor=operator(),
            asserted_at="2026-07-19T00:00:00.000000Z",
            status="satisfied",
            rationale="exact byte review",
            details={
                "report_body_id": REPORT,
                "report_body_hash": body.body_hash,
                "reviewed_exact_bytes": True,
                "limitations_acknowledged": True,
            },
        )
        self.assertEqual(core.final_accountability(REPORT, body.body_hash), disposition)
        body_after = projector.compose(
            cycle_id=CYCLE,
            source_revision=7,
            reducer_output={"outcome": "mixed"},
            policy_output={"support": "mixed"},
            hitl_output={"question_selection": "satisfied"},
            limitations=("Evidence is limited.",),
        )
        satisfied = projector.status_overlay(
            report_body_id=REPORT,
            at_revision=8,
            final_accountability_status="satisfied",
            disposition_id=disposition.disposition_id,
            generated_at="2026-07-19T00:01:00.000000Z",
        )
        self.assertEqual(body.body_utf8, body_after.body_utf8)
        self.assertEqual(body.body_hash, body_after.body_hash)
        self.assertNotEqual(pending, satisfied)
        self.assertEqual(pending["final_accountability_status"], "pending")
        self.assertEqual(satisfied["final_accountability_status"], "satisfied")
    def test_final_accountability_rejects_the_right_body_id_with_the_wrong_hash(self):
        core = SignoffCore(CYCLE)
        expected_hash = "sha256:" + "a" * 64
        requirement = core.rescope(
            Responsibility.FINAL_ACCOUNTABILITY, "report_body", (REPORT, expected_hash),
        )
        with self.assertRaisesRegex(SignoffError, "ID and hash"):
            core.record_disposition(
                requirement_id=requirement.requirement_id,
                responsibility=Responsibility.FINAL_ACCOUNTABILITY,
                actor=operator(),
                asserted_at="2026-07-19T00:00:00.000000Z",
                status="satisfied",
                rationale="reviewed a different body",
                details={
                    "report_body_id": REPORT,
                    "report_body_hash": "sha256:" + "b" * 64,
                    "reviewed_exact_bytes": True,
                    "limitations_acknowledged": True,
                },
            )
    def test_instance_and_static_disposition_validation_are_strictly_equivalent(self):
        core = SignoffCore(CYCLE)
        requirement = core.current_requirement(Responsibility.EXECUTION_ACCOUNTABILITY)
        payload = {
            "requirement_id": requirement.requirement_id,
            "scope_hash": requirement.scope_hash,
            "actor": asdict(operator()),
            "asserted_at": "2026-07-19T00:00:00.000000Z",
            "status": "satisfied",
            "rationale": "asserted handoff",
            "details": {
                "handoff_owner": asdict(operator("Handoff owner")),
                "execution_boundary": {"kind": "cognitive_only", "description": "No physical execution."},
            },
        }
        normalized = SignoffCore.validate_disposition_input(
            requirement={
                "id": requirement.requirement_id,
                "responsibility": requirement.responsibility.value,
                "scope_kind": requirement.scope_kind,
                "scope_ids": list(requirement.scope_ids),
                "scope_hash": requirement.scope_hash,
            },
            existing_disposition=None,
            responsibility=requirement.responsibility.value,
            payload=payload,
        )
        recorded = core.record_disposition(
            requirement_id=requirement.requirement_id,
            responsibility=Responsibility.EXECUTION_ACCOUNTABILITY,
            actor=operator(),
            asserted_at=payload["asserted_at"],
            status="satisfied",
            rationale=payload["rationale"],
            details={
                "handoff_owner": operator("Handoff owner"),
                "execution_boundary": payload["details"]["execution_boundary"],
            },
        )
        self.assertEqual(recorded.details, normalized["details"])

    def test_static_and_instance_disposition_validation_reject_the_same_invalid_categories(self):
        def execution_payload(requirement):
            return {
                "requirement_id": requirement.requirement_id,
                "scope_hash": requirement.scope_hash,
                "actor": asdict(operator()),
                "asserted_at": "2026-07-19T00:00:00.000000Z",
                "status": "satisfied",
                "rationale": "asserted handoff",
                "details": {
                    "handoff_owner": asdict(operator("Handoff owner")),
                    "execution_boundary": {
                        "kind": "cognitive_only",
                        "description": "No physical execution.",
                    },
                },
            }

        def requirement_mapping(requirement):
            return {
                "id": requirement.requirement_id,
                "responsibility": requirement.responsibility.value,
                "scope_kind": requirement.scope_kind,
                "scope_ids": list(requirement.scope_ids),
                "scope_hash": requirement.scope_hash,
            }

        def assert_rejected_by_both(name, static_payload, static_responsibility, instance_call):
            core = SignoffCore(CYCLE)
            requirement = core.current_requirement(Responsibility.EXECUTION_ACCOUNTABILITY)
            with self.subTest(case=name, validator="static"), self.assertRaises(SignoffError) as static_error:
                SignoffCore.validate_disposition_input(
                    requirement=requirement_mapping(requirement),
                    existing_disposition=None,
                    responsibility=static_responsibility,
                    payload=static_payload(requirement),
                )
            with self.subTest(case=name, validator="instance"), self.assertRaises(SignoffError) as instance_error:
                instance_call(core, requirement)
            self.assertIs(type(static_error.exception), type(instance_error.exception))

        assert_rejected_by_both(
            "malformed timestamp",
            lambda requirement: execution_payload(requirement) | {"asserted_at": "2026-07-19T00:00:00Z"},
            Responsibility.EXECUTION_ACCOUNTABILITY.value,
            lambda core, requirement: core.record_disposition(
                requirement_id=requirement.requirement_id,
                responsibility=Responsibility.EXECUTION_ACCOUNTABILITY,
                actor=operator(),
                asserted_at="2026-07-19T00:00:00Z",
                status="satisfied",
                rationale="asserted handoff",
                details={"handoff_owner": operator("Handoff owner"),
                         "execution_boundary": {"kind": "cognitive_only", "description": "No physical execution."}},
            ),
        )
        assert_rejected_by_both(
            "stale scope",
            lambda requirement: execution_payload(requirement) | {"scope_hash": "sha256:" + "a" * 64},
            Responsibility.EXECUTION_ACCOUNTABILITY.value,
            lambda core, requirement: core.record_disposition(
                requirement_id="requirement_11111111111111111111111111111111",
                responsibility=Responsibility.EXECUTION_ACCOUNTABILITY,
                actor=operator(),
                asserted_at="2026-07-19T00:00:00.000000Z",
                status="satisfied",
                rationale="asserted handoff",
                details={"handoff_owner": operator("Handoff owner"),
                         "execution_boundary": {"kind": "cognitive_only", "description": "No physical execution."}},
            ),
        )
        assert_rejected_by_both(
            "responsibility mismatch",
            execution_payload,
            Responsibility.QUESTION_SELECTION.value,
            lambda core, requirement: core.record_disposition(
                requirement_id=requirement.requirement_id,
                responsibility=Responsibility.QUESTION_SELECTION,
                actor=operator(),
                asserted_at="2026-07-19T00:00:00.000000Z",
                status="satisfied",
                rationale="asserted review",
            ),
        )
        assert_rejected_by_both(
            "missing handoff",
            lambda requirement: execution_payload(requirement) | {"details": {}},
            Responsibility.EXECUTION_ACCOUNTABILITY.value,
            lambda core, requirement: core.record_disposition(
                requirement_id=requirement.requirement_id,
                responsibility=Responsibility.EXECUTION_ACCOUNTABILITY,
                actor=operator(),
                asserted_at="2026-07-19T00:00:00.000000Z",
                status="satisfied",
                rationale="asserted handoff",
            ),
        )

        final_core = SignoffCore(CYCLE)
        final_requirement = final_core.rescope(
            Responsibility.FINAL_ACCOUNTABILITY,
            "report_body",
            (REPORT, "sha256:" + "a" * 64),
        )
        final_payload = {
            "requirement_id": final_requirement.requirement_id,
            "scope_hash": final_requirement.scope_hash,
            "actor": asdict(operator()),
            "asserted_at": "2026-07-19T00:00:00.000000Z",
            "status": "satisfied",
            "rationale": "wrong report binding",
            "details": {
                "report_body_id": "report_11111111111111111111111111111111",
                "report_body_hash": "sha256:" + "a" * 64,
                "reviewed_exact_bytes": True,
                "limitations_acknowledged": True,
            },
        }
        with self.assertRaises(SignoffError) as static_error:
            SignoffCore.validate_disposition_input(
                requirement=requirement_mapping(final_requirement),
                existing_disposition=None,
                responsibility=Responsibility.FINAL_ACCOUNTABILITY.value,
                payload=final_payload,
            )
        with self.assertRaises(SignoffError) as instance_error:
            final_core.record_disposition(
                requirement_id=final_requirement.requirement_id,
                responsibility=Responsibility.FINAL_ACCOUNTABILITY,
                actor=operator(),
                asserted_at=final_payload["asserted_at"],
                status="satisfied",
                rationale=final_payload["rationale"],
                details=final_payload["details"],
            )
        self.assertIs(type(static_error.exception), type(instance_error.exception))

    def test_disposition_rejects_malformed_timestamp_execution_and_final_binding(self):
        core = SignoffCore(CYCLE)
        execution = core.current_requirement(Responsibility.EXECUTION_ACCOUNTABILITY)
        with self.assertRaisesRegex(ValueError, "timestamp"):
            core.record_disposition(
                requirement_id=execution.requirement_id,
                responsibility=Responsibility.EXECUTION_ACCOUNTABILITY,
                actor=operator(), asserted_at="2026-07-19T00:00:00Z",
                status="satisfied", rationale="invalid timestamp",
                details={"handoff_owner": operator(), "execution_boundary": {"kind": "manual"}},
            )
        with self.assertRaisesRegex(ValueError, "handoff"):
            core.record_disposition(
                requirement_id=execution.requirement_id,
                responsibility=Responsibility.EXECUTION_ACCOUNTABILITY,
                actor=operator(), asserted_at="2026-07-19T00:00:00.000000Z",
                status="satisfied", rationale="missing handoff",
            )
        final = core.rescope(
            Responsibility.FINAL_ACCOUNTABILITY, "report_body", (REPORT, "sha256:" + "a" * 64),
        )
        with self.assertRaisesRegex(ValueError, "final accountability"):
            core.record_disposition(
                requirement_id=final.requirement_id,
                responsibility=Responsibility.FINAL_ACCOUNTABILITY,
                actor=operator(), asserted_at="2026-07-19T00:00:00.000000Z",
                status="satisfied", rationale="wrong report binding",
                details={"report_body_id": "report_11111111111111111111111111111111", "report_body_hash": "sha256:" + "a" * 64,
                         "reviewed_exact_bytes": True, "limitations_acknowledged": True},
            )

    def test_disposition_id_binds_actor_and_assertion_time_independently(self):
        def record(actor_name, asserted_at):
            core = SignoffCore(CYCLE)
            requirement = core.current_requirement(Responsibility.QUESTION_SELECTION)
            return core.record_disposition(
                requirement_id=requirement.requirement_id,
                responsibility=Responsibility.QUESTION_SELECTION,
                actor=operator(actor_name),
                asserted_at=asserted_at,
                status="satisfied",
                rationale="asserted review",
            )

        baseline = record("One", "2026-07-19T00:00:00.000000Z")
        changed_actor = record("Two", "2026-07-19T00:00:00.000000Z")
        changed_time = record("One", "2026-07-19T00:01:00.000000Z")
        self.assertNotEqual(baseline.disposition_id, changed_actor.disposition_id)
        self.assertNotEqual(baseline.disposition_id, changed_time.disposition_id)
    def test_append_only_history_views_cannot_be_rewritten(self):
        core = SignoffCore(CYCLE)
        requirement_view = core.requirements

        self.assertIsInstance(requirement_view, tuple)
        with self.assertRaises(AttributeError):
            requirement_view.append(requirement_view[0])
        with self.assertRaises(AttributeError):
            core.requirements = ()

        requirement = core.current_requirement(Responsibility.QUESTION_SELECTION)
        core.record_disposition(
            requirement_id=requirement.requirement_id,
            responsibility=Responsibility.QUESTION_SELECTION,
            actor=operator(),
            asserted_at="2026-07-19T00:00:00.000000Z",
            status="satisfied",
            rationale="asserted review",
        )
        disposition_view = core.dispositions
        self.assertIsInstance(disposition_view, tuple)
        with self.assertRaises(AttributeError):
            disposition_view.clear()
        with self.assertRaises(AttributeError):
            core.dispositions = ()
        self.assertEqual(core.requirements, requirement_view)
        self.assertEqual(len(core.dispositions), 1)
        with self.assertRaises(TypeError):
            disposition_view[0].details["replacement"] = True


if __name__ == "__main__":
    unittest.main()
