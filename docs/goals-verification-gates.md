# GOALS Verification Gates

Checklist of verification gates for the GOALS pipeline beyond the original
6-pane verification. Each gate names its claim, how it is enforced, and where
the regression evidence lives.

## Gate: deterministic event-only replay (issue #44) — ACTIVE

**Claim.** A saved GOALS event stream (`events.jsonl`) can reconstruct the
complete final report bundle (`final_report_html_yaml_bundle.v1`) without
reading transient runtime state, artifact files, or in-memory objects.

**Mechanism.**

- `final_report_event_metadata` embeds the complete `final_bundle` payload in
  every final-report lifecycle event (`stage_completed` / `stage_blocked`),
  making the persisted event self-sufficient.
- `src/pipeline/goals_replay.py` (`replay_final_bundle`) reconstructs the
  bundle purely from the event sequence. The last final-report lifecycle event
  wins, mirroring append-only supersession (a blocked final report replaced by
  a completed rerun replays to the completed bundle).
- Replay is deterministic: identical event inputs produce byte-identical
  sorted-JSON bundles (`bundle_fingerprint`).
- Corrupt streams and missing bundles fail closed with stable error codes
  (`replay_event_stream_corrupt`, `replay_no_final_report_event`,
  `replay_bundle_missing`, `replay_bundle_contract_mismatch`).

**Evidence.** `tests/test_goals_event_replay.py` covers an end-to-end GOALS
event stream (JSONL round trip included) whose replayed bundle is compared
byte-for-byte against the produced artifact bundle, plus determinism,
blocked-final replay, supersession, and every failure code.
Contract report: `goals_replay_gate_report()`.

## Gate: live-provider full-product run (issue #45) — PENDING

Not yet implemented. Must exercise the full GOALS flow with configured live
providers without logging credentials, and record provider/model metadata for
reproducibility. Deterministic/offline CI must not depend on it.

## Gate: complete final-bundle UI consumability (issue #46) — ACTIVE

**Claim.** Run Progress consumes every field in the
`final_report_html_yaml_bundle.v1` contract: reader-facing fields are rendered,
technical envelope fields are intentionally hidden, and partial or malformed
payloads produce explicit degradation copy.

**Mechanism.**

- `app/muchanipo-tauri/src/lib/finalBundle.ts` owns tolerant parsing, complete
  field accounting, event extraction, and degradation status.
- `app/muchanipo-tauri/src/components/FinalBundlePanel.tsx` renders the
  reader-facing fields and clear partial/malformed states.
- `app/muchanipo-tauri/src/pages/RunProgress.tsx` captures the embedded bundle
  from final-report lifecycle events and renders the panel beside the report.

**Evidence.** `app/muchanipo-tauri/src/lib/finalBundle.test.ts` covers complete,
partial, and malformed payloads and asserts that every contract field is
rendered or intentionally hidden. The implementation was merged in PR #52 and
closed issue #46.
