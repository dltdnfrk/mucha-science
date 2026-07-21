import base64
import json
from pathlib import Path
import unittest
import io
import hashlib
import subprocess
import sys

from src.muchanipo.events import ScientificEnvelope, emit, parse_action
from src.pipeline.scientific_contracts import ACTIONS, ERRORS, EVENTS, ContractError, byte_digest, canonical_json, event_frame_hash, validate_protocol_action


SCHEMA = Path(__file__).parents[1] / "config/protocol/ai-scientist.v1/schema/protocol.schema.json"
FIXTURE_ROOT = Path(__file__).parents[1] / "config/protocol/ai-scientist.v1"
FIXTURE_MANIFEST = FIXTURE_ROOT / "manifest.json"
FIXTURE_BUILDER = Path(__file__).parents[1] / "tools/build_protocol_fixtures.py"


class ProtocolFixtureContractTests(unittest.TestCase):
    def setUp(self):
        self.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.defs = self.schema["$defs"]

    def test_closed_root_and_exhaustive_continue_branches(self):
        self.assertEqual(self.schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
        branches = self.defs["continuePayload"]["oneOf"]
        self.assertEqual(len(branches), 8)
        self.assertEqual(
            {ref["$ref"].rsplit("/", 1)[-1] for ref in branches},
            {"landscapeContinue", "hypothesisContinue", "proposalContinue", "notRunContinue", "analysisContinue", "interimContinue", "finalContinue", "completeContinue"},
        )
        self.assertFalse(self.defs["baseEnvelope"]["additionalProperties"])

    def test_continue_discriminators_and_local_x_required_nulls_are_frozen(self):
        local = self.defs["notRunContinue"]["properties"]["stage_input"]
        self.assertFalse(local["additionalProperties"])
        self.assertEqual(local["properties"]["kind"]["const"], "execution.not_run")
        self.assertEqual(local["properties"]["accountable_party"]["type"], "null")
        self.assertEqual(local["properties"]["started_at"]["type"], "null")
        self.assertEqual(local["properties"]["performers"]["maxItems"], 0)

    def test_adjudication_has_create_and_transition_with_policy_and_a_links(self):
        branches = self.defs["adjudicatePayload"]["oneOf"]
        self.assertEqual(len(branches), 2)
        create = branches[0]["properties"]["assessment"]
        transition = branches[1]
        for branch in (create, transition):
            required = set(branch["required"])
            self.assertTrue({"claim_ids", "result_ids", "analysis_stage_id", "analysis_artifact_ids", "validation_policy_id", "validation_policy_version", "validation_policy_reference"} <= required)
            self.assertFalse(branch["additionalProperties"])
        policy = self.defs["policy"]
        self.assertEqual(policy["properties"]["validation_policy_id"]["anyOf"][0]["const"], "muchanipo.validation.general")

    def test_no_physical_control_action_is_catalogued(self):
        names = self.defs["actionEnvelope"]["allOf"][1]["properties"]["name"]["enum"]
        self.assertNotIn("execution.run", names)
        self.assertNotIn("instrument.command", names)
    def test_catalogs_are_complete_and_match_the_frozen_contract(self):
        action_names = set(self.defs["actionEnvelope"]["allOf"][1]["properties"]["name"]["enum"])
        event_names = set(self.defs["eventEnvelope"]["allOf"][1]["properties"]["name"]["enum"])
        self.assertEqual(action_names, ACTIONS)
        self.assertEqual(event_names, EVENTS)
        self.assertEqual(
            set(self.defs["responseEnvelope"]["allOf"][1]["properties"]["name"]["enum"]),
            {"protocol.welcome.response", "command.accepted.response", "cycle.replay.response",
             "cycle.resume.response", "export.get.response", "report.render.response",
             "cycle.acknowledged.response"},
        )
        self.assertTrue(ERRORS >= {"protocol_invalid", "protocol_unsupported", "unknown_action"})
        hello = self.defs["helloPayload"]
        self.assertEqual(set(hello["required"]), {
            "handshake_idempotency_key", "client_instance_id", "supported_versions",
            "capabilities", "projection", "cursors",
        })
        self.assertFalse(hello["additionalProperties"])
        self.assertEqual(hello["properties"]["cursors"]["items"]["$ref"], "#/$defs/cursor")
    def test_every_action_has_a_closed_payload_branch_and_reject_vector(self):
        payload_branches = {}
        for branch in self.defs["actionEnvelope"]["allOf"][1]["allOf"]:
            name = branch.get("if", {}).get("properties", {}).get("name", {}).get("const")
            payload = branch.get("then", {}).get("properties", {}).get("payload")
            if name and payload:
                payload_branches[name] = payload["$ref"].rsplit("/", 1)[-1]

        self.assertEqual(set(payload_branches), ACTIONS)
        for action, definition in payload_branches.items():
            shape = self.defs[definition]
            if "oneOf" in shape:
                continue
            self.assertFalse(shape["additionalProperties"], action)

            with self.subTest(action=action):
                envelope = {
                    "protocol": "muchanipo",
                    "protocol_version": "ai-scientist.v1",
                    "kind": "action",
                    "name": action,
                    "message_id": "message_00000000000000000000000000000000",
                    "cycle_id": None,
                    "correlation_id": "message_00000000000000000000000000000000",
                    "causation_id": None,
                    "sequence": 0,
                    "revision": 0,
                    "idempotency_key": None,
                    "timestamp": "1970-01-01T00:00:00.000000Z",
                    "payload": {"unexpected": True},
                    "extensions": {},
                }
                with self.assertRaises(ContractError):
                    validate_protocol_action(envelope)

    def test_mutation_cycle_revision_idempotency_and_external_scope_are_frozen(self):
        action_rules = self.defs["actionEnvelope"]["allOf"][1]["allOf"]
        mutation_rule = action_rules[-1]["then"]["properties"]["idempotency_key"]
        self.assertEqual(mutation_rule, {"type": "string", "minLength": 1})
        cycle_rule = action_rules[-2]["then"]["properties"]["cycle_id"]
        self.assertEqual(cycle_rule, {"$ref": "#/$defs/id"})
        externally_asserted = self.defs["authorityScope"]["allOf"][1]["then"]["properties"]["scope"]
        self.assertEqual(externally_asserted, {"type": "string", "minLength": 1})

    def test_canonical_json_uses_utf16_code_unit_object_ordering(self):
        self.assertEqual(canonical_json({"\ue000": 1, "😀": 2}), b'{"\xf0\x9f\x98\x80":2,"\xee\x80\x80":1}')
    def test_scientific_envelope_materializes_identity_and_isolates_payload(self):
        payload = {"nested": {"value": "original"}}
        extensions = {"trace": {"attempt": 1}}
        envelope = ScientificEnvelope(kind="event", name="cycle.started", payload=payload, extensions=extensions)

        first = envelope.to_json()
        payload["nested"]["value"] = "changed"
        extensions["trace"]["attempt"] = 2

        self.assertEqual(envelope.to_json(), first)
        self.assertEqual(envelope.message_id, json.loads(first)["message_id"])
        self.assertEqual(envelope.timestamp, json.loads(first)["timestamp"])
        self.assertEqual(json.loads(first)["payload"], {"nested": {"value": "original"}})
        self.assertEqual(json.loads(first)["extensions"], {"trace": {"attempt": 1}})
        with self.assertRaises(TypeError):
            envelope.payload["replacement"] = True

    def test_legacy_actions_reject_unknown_names_and_events_stay_permissive(self):
        self.assertIsNone(parse_action('{"action": ""}'))
        self.assertIsNone(parse_action('{"action": "unknown"}'))
        self.assertEqual(parse_action('{"action": "abort"}').action, "abort")
        with self.assertRaises(ValueError):
            emit("", stream=io.StringIO())
        # Outbound legacy telemetry is deliberately permissive: the full
        # research pipeline emits event names beyond the stub-era catalog
        # (e.g. final_report) and clients preserve unknown legacy events.
        stream = io.StringIO()
        emit("full-pipeline-telemetry", stream=stream, value=1)
        self.assertEqual(json.loads(stream.getvalue()), {"event": "full-pipeline-telemetry", "value": 1})

    def test_checked_in_protocol_fixture_bytes_match_the_manifest_and_generator(self):
        manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual(manifest["unicode_version"], "15.1.0")
        self.assertEqual(manifest["normalization_profile"], "unicode-nfc-whitespace")
        self.assertEqual({entry["path"] for entry in manifest["files"]}, {
            "bytes/corpus.jsonl", "invalid/corpus.jsonl", "legacy/corpus.jsonl",
            "replay/corpus.jsonl", "valid/corpus.jsonl",
        })
        for entry in manifest["files"]:
            fixture = FIXTURE_ROOT / entry["path"]
            raw = fixture.read_bytes()
            self.assertEqual(len(raw), entry["length"], entry["path"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(), entry["sha256"], entry["path"])
            self.assertTrue(raw.endswith(b"\n"), entry["path"])
            [json.loads(record) for record in raw.splitlines()]

        checked = subprocess.run(
            [sys.executable, str(FIXTURE_BUILDER), "--check"],
            cwd=FIXTURE_ROOT.parents[2],
            capture_output=True,
            text=True,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_protocol_fixture_corpus_covers_the_frozen_boundary_cases(self):
        records = [
            json.loads(record)
            for entry in json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))["files"]
            for record in (FIXTURE_ROOT / entry["path"]).read_bytes().splitlines()
        ]
        cases = {record.get("case") for record in records}
        self.assertTrue({
            "required-frame-preimage", "frame-hash", "member-order", "marker-mismatch",
            "event-hash", "invalid-id", "trailing-bytes", "partial-frame",
            "interior-corruption", "identity-null-cycle-start", "retry-same-key",
            "six-dispositions", "eight-continue-branches-and-inverses",
            "adjudication-links-policy", "normalization-unicode-15.1",
            "safe-integer-boundaries",
        } <= cases)
        envelopes = {(record.get("kind"), record.get("name")) for record in records}
        self.assertTrue({("event", name) for name in EVENTS} <= envelopes)
        self.assertTrue({("response", name) for name in {
            "protocol.welcome.response", "command.accepted.response", "cycle.replay.response",
            "cycle.resume.response", "export.get.response", "report.render.response",
            "cycle.acknowledged.response",
        }} <= envelopes)
        self.assertTrue({("error", name) for name in {"command.rejected.error", "protocol.invalid.error"}} <= envelopes)
        self.assertIn(("snapshot", "cycle.snapshot"), envelopes)
        self.assertIn(("ack", "cycle.acknowledged"), envelopes)

    def test_byte_fixture_vectors_carry_exact_frame_preimages_and_corrupt_streams(self):
        records = {
            record["case"]: record
            for record in map(
                json.loads,
                (FIXTURE_ROOT / "bytes/corpus.jsonl").read_bytes().splitlines(),
            )
        }
        for case in ("event-frame-genesis", "event-frame-non-ascii", "frame-hash-member-order"):
            vector = records[case]
            preimage = base64.b64decode(vector["frame_preimage_utf8_base64"])
            event_line = base64.b64decode(vector["event_line_utf8_base64"])
            marker_line = base64.b64decode(vector["marker_line_utf8_base64"])
            self.assertEqual(byte_digest(preimage), vector["expected_frame_hash"])
            self.assertEqual(canonical_json(json.loads(preimage)), preimage)
            frame = json.loads(event_line)
            marker = json.loads(marker_line)
            self.assertEqual(event_frame_hash(frame), vector["expected_frame_hash"])
            self.assertEqual(marker["frame_hash"], frame["frame_hash"])
            self.assertEqual(marker["frame_id"], frame["frame_id"])
            self.assertEqual(marker["event_hash"], byte_digest(canonical_json(frame["event"])))
            self.assertEqual(
                byte_digest(event_line + marker_line),
                vector["combined_bytes_sha256"],
            )
        for case in (
            "marker-frame-hash-mismatch", "event-hash-mismatch", "frame-id-mismatch",
            "trailing-event", "partial-marker", "interior-corruption",
        ):
            stream = base64.b64decode(records[case]["stream_utf8_base64"])
            self.assertEqual(byte_digest(stream), records[case]["stream_sha256"])

    def test_tampered_fixture_bytes_are_rejected_by_the_validator(self):
        target = FIXTURE_ROOT / "bytes/corpus.jsonl"
        original = target.read_bytes()
        try:
            target.write_bytes(original + b"{}")
            checked = subprocess.run(
                [sys.executable, str(FIXTURE_BUILDER), "--check"],
                cwd=FIXTURE_ROOT.parents[2],
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(checked.returncode, 0)
        finally:
            target.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
