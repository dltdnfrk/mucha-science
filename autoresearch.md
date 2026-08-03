# Autoresearch: Mucha Science App Completion Loop

## Objective
Drive Mucha Science toward a reliable local Tauri app and terminal-first autoresearch loop that can run the full research pipeline, call local CLI providers, preserve progress across remounts, and render a final report without false failures.

The next-cycle benchmark input is Google's 2026-04-21 Deep Research Max announcement. Mucha Science should adopt the useful product surfaces without copying the product shape: keep the six-stage flow, offline-first demo, Korean grounded personas, and bottom-up council synthesis.

## Metrics
- **Primary**: `quality_score` (points, higher is better) - composite pass score from backend smoke, frontend build, Rust bridge tests, and targeted provider/gateway tests.
- **Secondary**: `duration_seconds`, `failures`, `frontend_build`, `rust_tests`, `python_tests`, `depth_contract`.

## How to Run
`./autoresearch.sh` prints `METRIC name=value` lines.

For unattended monitoring:
`MAX_ITERATIONS=96 SLEEP_SECONDS=300 scripts/overnight_loop.sh`

## Files in Scope
- `app/muchanipo-tauri/src-tauri/src/python_bridge.rs` - Tauri bridge, CLI status/smoke/auth, event replay.
- `app/muchanipo-tauri/src/pages/*.tsx` - Settings, RunProgress, ReportView UX.
- `app/muchanipo-tauri/src/lib/*.ts` - Tauri client contracts and run index.
- `src/execution/**` - provider calls, model routing, gateway fallback, telemetry.
- `src/governance/**` - budget/cost/audit logging.
- `src/muchanipo/server.py` and `src/pipeline/**` - full pipeline event stream and backend smoke.
- `src/research/depth.py` and `src/research/planner.py` - shallow/deep/max autoresearch budget profiles.
- `tests/**` - regression coverage for touched behavior.
- `scripts/**` - repeatable smoke/autoresearch runners.

## Off Limits
- Do not delete user runtime data under `vault/`, `raw/`, `.omc/`, `.omx/`, or `muchanipo-pipeline-*`.
- Do not remove installed CLI auth state.
- Do not add dependencies unless explicitly requested.
- Do not perform destructive git operations.

## Constraints
- Keep diffs small and commit with Lore protocol.
- Run frontend build, Rust tests, and relevant Python tests before claiming a keep.
- Treat provider stderr/noisy CLI output as diagnostic unless the subprocess exits non-zero.
- Preserve CLI mode as the default local execution path.
- Keep `/Applications/Mucha Science.app` as the canonical installed app; avoid duplicate app installs.

## What's Been Tried
- Stabilized GUI `.app` PATH and explicit CLI binary injection.
- Added Settings CLI status, smoke, and auth launch flows.
- Fixed report chunk replay duplication and abort sidebar cleanup.
- Separated non-fatal backend warnings from fatal errors so benign stderr no longer blocks report navigation.
- Added provider/model metadata to cost-log reservations and normalized provider model override telemetry.

## Reconciled Backlog (2026-07-29)

This section is the live backlog. Unchecked boxes in `.omo/`, `_assignments/`,
`progress.txt`, and agent templates are historical execution records unless an
item is reconfirmed here.

Repository baseline:

- GitHub's default `main` is `06b1f62`.
- `recovery/incident-20260728` preserves recovered work through `0c119fe`.
- Local `main` is clean at merge commit `e487c82`, four commits ahead of
  GitHub `main`; it combines the GitHub mainline with the recovered research
  and chat-first workspace.

### P0 — protect and close the recovered integration

- [ ] Revalidate local merge `e487c82` on the exact current tree: focused
  Python/Vitest/Rust suites, frontend build, and a real Tauri smoke covering
  chat-owned execution, cancellation, evidence projection, and final-report
  navigation. Publish only after review; no push is implied by this backlog.
- [ ] Implement GitHub issue
  [#45](https://github.com/dltdnfrk/mucha-science/issues/45): an opt-in
  live-provider full-product gate that records reproducible provider/model
  metadata without secrets and does not make offline CI depend on live
  services.

### P1 — confirmed product gaps

- [ ] Add a real Tauri GUI full-run check for
  `IdeaSubmit -> RunProgress -> ReportView`. The existing
  `tests/test_e2e_tauri_smoke.py` is backend-only and explicitly runs without
  the Tauri shell.
- [ ] Add CLI `--pdf` / `--csv` input normalization. PDF extraction exists in
  the low-level ingest path, but the run/TUI CLI exposes neither flag and CSV
  is not a supported ingest extension.
- [ ] Add an explicit production MCP research-ingestion lane. The research
  runner has injectable seams such as `exa_search`, and the Tauri debug build
  can load an MCP bridge, but the product runner does not yet wire and verify
  an MCP-backed research source end to end.

### Conditional

- [ ] Expand full-pipeline HITL contract tests only if interactive full mode
  becomes a required product mode.

### Reconciled complete

- [x] `--depth shallow|deep|max`, including the 120-second shallow profile.
- [x] Editable HITL plan review before execution, with Plannotator UI and
  pipeline tests.
- [x] Mermaid/HTML report visualization and safe Tauri rendering.
- [x] Packaged `.app` workspace resolution for moved/clean-machine installs,
  with Rust fixtures.
- [x] Provider/API credentials are session-only and legacy persistent
  `localStorage` values are purged at startup.
- [x] Manual Terminal fallback copy is returned when `open_cli_auth` automation
  is blocked.
- [x] GOALS final-bundle UI consumability (issue #46), merged in PR #52.
