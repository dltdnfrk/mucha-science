import unittest

from src.evidence.scientific_validation import (
    ApplicabilityContext, Assessment, AssessmentLinks, PolicyDisposition,
    Qualification, SupportStatus, ValidationError, ValidationPolicy,
    adjudicate_current, aggregate_support, policy_decision,
)
from src.pipeline.scientific_contracts import (
    AssessmentState, AssertionSource, AuthorityKind, AuthorityScope, ContractError,
    ExternalReference, Outcome, ValidationLevel, VerificationStatus, canonical_id_array,
)


LINKS = AssessmentLinks(
    ("claim_00000000000000000000000000000000",),
    ("result_00000000000000000000000000000000",),
    "stage_00000000000000000000000000000000",
    ("artifact_00000000000000000000000000000000",),
)
GENERAL = ValidationPolicy("muchanipo.validation.general", "1.0.0", None)
CONTEXT = ApplicabilityContext(LINKS.claim_ids, LINKS.result_ids, LINKS.analysis_stage_id,
                               LINKS.analysis_artifact_ids, GENERAL)


def assessment(identifier, *, outcome=Outcome.SUPPORTS, state=AssessmentState.ACCEPTED.value,
               level=ValidationLevel.V1, quality="low", confidence="0.9999",
               policy=GENERAL, qualifications=(Qualification("subject_matter", True),),
               assessor_asserted_unverified=True, **kwargs):
    return Assessment(identifier, LINKS, state, outcome, level, quality, confidence,
                      "applicable", policy, qualifications,
                      assessor_asserted_unverified=assessor_asserted_unverified, **kwargs)


class ScientificValidationTests(unittest.TestCase):
    def test_orthogonality_matrix_does_not_upgrade_validation_level(self):
        weak = assessment("weak", quality="low", confidence="1")
        strong = assessment("strong", quality="high", confidence="0", level=ValidationLevel.V1)
        self.assertEqual(weak.validation_level, ValidationLevel.V1)
        self.assertEqual(strong.validation_level, ValidationLevel.V1)
        self.assertEqual(policy_decision(strong, CONTEXT).disposition, PolicyDisposition.ACCEPTABLE)
        self.assertEqual(policy_decision(weak, CONTEXT).disposition, PolicyDisposition.ACCEPTABLE)

    def test_negative_mixed_and_inconclusive_are_not_confidence_tiebroken(self):
        self.assertEqual(aggregate_support([assessment("r", outcome=Outcome.REFUTES)]).status,
                         SupportStatus.REFUTING)
        high_confidence_support = assessment("high-support", confidence="1")
        low_confidence_refutation = assessment(
            "low-refutation", outcome=Outcome.REFUTES, confidence="0",
        )
        self.assertEqual(
            aggregate_support([high_confidence_support, low_confidence_refutation]).status,
            SupportStatus.MIXED,
        )
        high_confidence_refutation = assessment(
            "high-refutation", outcome=Outcome.REFUTES, confidence="1",
        )
        low_confidence_support = assessment("low-support", confidence="0")
        self.assertEqual(
            aggregate_support([high_confidence_refutation, low_confidence_support]).status,
            SupportStatus.MIXED,
        )
        self.assertEqual(aggregate_support([assessment("i", outcome=Outcome.INCONCLUSIVE)]).status,
                         SupportStatus.INCONCLUSIVE)
        self.assertEqual(aggregate_support([assessment("p", state=AssessmentState.PENDING.value)]).status,
                         SupportStatus.UNASSESSED)
    def test_noncurrent_terminal_history_cannot_override_current_pending_assessment(self):
        aggregation = aggregate_support([
            assessment("withdrawn-history", state="withdrawn", current=False),
            assessment("superseded-history", state="superseded", current=False),
            assessment("current-pending", state=AssessmentState.PENDING.value),
        ])

        self.assertEqual(aggregation.status, SupportStatus.UNASSESSED)
        self.assertEqual(aggregation.accepted_assessment_ids, ())

    def test_general_policy_never_accepts_maximally_qualified_v3(self):
        decision = policy_decision(
            assessment(
                "v3",
                level=ValidationLevel.V3,
                quality="high",
                confidence="1",
                qualifications=(
                    Qualification("subject_matter", True),
                    Qualification("benchmark", True),
                ),
                methods_and_statistics=True,
                independent=True,
                assessor_asserted_unverified=True,
            ),
            CONTEXT,
        )
        self.assertEqual(decision.disposition, PolicyDisposition.PENDING)
    def test_every_validation_level_has_explicit_policy(self):
        expected = {
            ValidationLevel.V0: PolicyDisposition.PENDING,
            ValidationLevel.V1: PolicyDisposition.ACCEPTABLE,
            ValidationLevel.V2: PolicyDisposition.ACCEPTABLE,
            ValidationLevel.V3: PolicyDisposition.PENDING,
        }
        for level, disposition in expected.items():
            candidate = assessment(
                f"assessment-{level.value}",
                level=level,
                quality="moderate" if level is ValidationLevel.V2 else "low",
                methods_and_statistics=level is ValidationLevel.V2,
                independent=level is ValidationLevel.V2,
            )
            self.assertEqual(policy_decision(candidate, CONTEXT).disposition, disposition)

    def test_omitted_assurance_fails_closed(self):
        self.assertEqual(
            policy_decision(assessment("missing-assessor", assessor_asserted_unverified=False), CONTEXT).disposition,
            PolicyDisposition.PENDING,
        )
        self.assertEqual(
            policy_decision(
                assessment("missing-qualification", qualifications=(Qualification("subject_matter"),)),
                CONTEXT,
            ).disposition,
            PolicyDisposition.PENDING,
        )

    def test_adjudication_uses_frozen_wire_vocabulary(self):
        source = {
            "assessment_id": "assessment_00000000000000000000000000000000",
            "claim_ids": list(LINKS.claim_ids),
            "result_ids": list(LINKS.result_ids),
            "analysis_stage_id": LINKS.analysis_stage_id,
            "analysis_artifact_ids": list(LINKS.analysis_artifact_ids),
            "assessment_state": "pending",
            "result_outcome": "supports",
            "validation_level": "V1",
            "evidence_quality": "low",
            "model_confidence": None,
            "applicability": "applicable",
            "qualifications": [{"kind": "subject_matter", "asserted_unverified": True}],
            "assessor": {
                "actor_kind": "human",
                "display_name": "Assessor",
                "organization": None,
                "role": "reviewer",
                "assertion_source": "operator_entry",
                "verification_status": "operator_asserted_unverified",
                "authority_scope": {"kind": "none", "scope": None},
                "external_reference": None,
            },
            "validation_policy_id": GENERAL.policy_id,
            "validation_policy_version": GENERAL.version,
            "validation_policy_reference": None,
        }
        self.assertEqual(adjudicate_current(source=source, context=CONTEXT).disposition,
                         PolicyDisposition.ACCEPTABLE)
        legacy = dict(source)
        legacy["state"] = legacy.pop("assessment_state")
        legacy["outcome"] = legacy.pop("result_outcome")
        with self.assertRaises(ValidationError):
            adjudicate_current(source=legacy, context=CONTEXT)
        malformed_quality = dict(source, evidence_quality="limited")
        with self.assertRaises(ValidationError):
            adjudicate_current(source=malformed_quality, context=CONTEXT)
        accepted_without_pending = dict(source, assessment_state="accepted")
        with self.assertRaises(ValidationError):
            adjudicate_current(source=accepted_without_pending, context=CONTEXT)
        with self.assertRaises(ValidationError):
            adjudicate_current(source=source, context=CONTEXT, prior_state="accepted")
        v3_accepted = dict(source, assessment_state="accepted", validation_level="V3",
                           evidence_quality="high")
        with self.assertRaises(ValidationError):
            adjudicate_current(source=v3_accepted, context=CONTEXT, prior_state="pending")

    def test_consequential_policy_without_qualified_references_is_export_only(self):
        with self.assertRaises(ValidationError):
            ValidationPolicy("external:clinical", "1", None, consequential=True)
        reference = ExternalReference(
            "policy", "External issuer", "Clinical policy", "policy:1", "sha256:" + "a" * 64,
            AssertionSource.EXTERNAL_REFERENCE, VerificationStatus.EXTERNAL_REFERENCE_UNVERIFIED,
            AuthorityScope(AuthorityKind.NONE, None),
        )
        policy = ValidationPolicy("external:clinical", "1", reference, consequential=True)
        context = ApplicabilityContext(LINKS.claim_ids, LINKS.result_ids, LINKS.analysis_stage_id,
                                       LINKS.analysis_artifact_ids, policy)
        self.assertEqual(policy_decision(assessment("external", policy=policy, qualifications=()), context).disposition,
                         PolicyDisposition.EXPORT_ONLY)
        wrong = ApplicabilityContext(
            ("claim_11111111111111111111111111111111",), LINKS.result_ids,
            LINKS.analysis_stage_id, LINKS.analysis_artifact_ids, GENERAL,
        )
        with self.assertRaises(ValidationError):
            policy_decision(assessment("a"), wrong)
    def test_canonical_id_arrays_reject_strings_and_non_protocol_ids(self):
        with self.assertRaises(ContractError):
            canonical_id_array("claim_00000000000000000000000000000000")
        with self.assertRaises(ContractError):
            canonical_id_array(["plain_ascii_id"])



if __name__ == "__main__":
    unittest.main()
