# Final Code Review — Claude Science P0 Port

**Branch:** `feat/mucha-science-live-web-research` @ `3cd5af3`
**Reviewer:** senpi (automated)
**Date:** 2026-08-05

---

## Verdict: **APPROVE**

No blockers. All five P0 specs are implemented correctly, tests pass, and no unrelated scope creep was detected.

---

## Verification Evidence

| Check | Command | Result |
|---|---|---|
| TypeScript build | `bun run build` (web/ui) | ✅ 356 modules, 907ms |
| Frontend tests | `bun run test` (web/ui) | ✅ 231 passed, 39 files, 587ms |
| Python HITL resume tests | `pytest tests/test_live_product_gate.py -k resume` | ✅ 3 passed |

---

## Per-Spec Assessment

### P0-1 HITL 회복 (commits `1dcae6d`, `d974056`)

**Spec alignment:** ✅ Matches §5.1 exactly.

**Backend (`live_mode.py`, `idea_to_council.py`, `server.py`):**
- `HitlResumeRequired(LiveModeViolation)` subclass carries structured `event` dict — clean inheritance, doesn't break existing `LiveModeViolation` catch blocks.
- `assert_live_hitl` gained `on_changes_requested: "resume" | "fail"` kwarg; default remains `"fail"` for backward compat. Chat/web path passes `"resume"`.
- `hitl_resume_required_event()` builds the exact JSON structure from the spec (`event`, `gate`, `revision_count`, `resumable`, `message`).
- `server.py` catches `HitlResumeRequired` before `LiveModeViolation`, emits `done` with `status=run_awaiting_human`, returns 0 (clean exit, no abort).
- `IdeaToCouncilPipeline` passes `on_changes_requested` through and emits the progress event before re-raising.

**Frontend (`useResearchPipelineBridge.ts`, `ResearchConversationTurn.tsx`):**
- Bridge handles both `done/run_awaiting_human` and `hitl_resume_required` events as `"resumable"` terminal status.
- Recovery card renders the four spec actions: 다시 승인 UI 열기, 수정 의견 보내며 재개, 여기까지 Artifact 저장, 새 Run으로 포크.
- `resumeRun` re-attaches to the run and optionally sends `changes_requested` with a comment via `sendAction`.
- `pendingInteractionRef` pattern correctly captures the latest interaction for the resume callback.

**Tests (3 new Python, 2 new frontend):**
- `test_pipeline_live_mode_emits_resume_required_not_hard_fail` — verifies event shape, gate name, revision count, resumable flag.
- `test_hitl_second_approval_continues_pipeline_with_resume_mode` — verifies evidence gate passes on second approval.
- `test_assert_live_hitl_resume_vs_fail_mode` — verifies mode distinction and `HitlResumeRequired ⊂ LiveModeViolation`.
- Bridge tests cover resumable terminal paths; turn test covers recovery card render.

**Code quality:** Good. Type annotations are complete. The `HitlResumeRequired` subclass design is clean — it's still a `LiveModeViolation` so existing error handling doesn't break, but carries structured data for the resume path.

### P0-2 세션 제목 (commit `e6d9983`)

**Spec alignment:** ✅ Matches §5.2.

- `createConversationSummary` uses `createThreadLabel(prompt)` for the rail title (32-char cap + ellipsis).
- `disambiguateDuplicateThreadTitles` appends `· N` suffix for repeated labels (2nd occurrence gets `· 2`, etc.).
- Full prompt preserved as `preview` line.

**Tests (3 new):** compressed title + preview, duplicate suffix, distinct titles remain untouched.

**Code quality:** Clean. The disambiguation is a pure function operating on the already-sorted summary array — no side effects.

### P0-3 Artifact Library (commit `084b2da`)

**Spec alignment:** ✅ Matches §5.3.

- `researchArtifactLibrary.ts`: `listArtifacts({ sessionId?, runId? })`, `getArtifact(id)`, `listVersions(artifactId)` — exact API from spec.
- Derives four artifact kinds: `report`, `report-draft`, `source-audit`, `quality-summary` — matches the spec table.
- `LibraryPanel.tsx`: grid with kind badge, title, session, time; markdown/json viewer with back navigation.
- Route at `#/scientific/library` with rail entry and `LibraryIcon`.
- `loadAllResearchSessions` added to storage for cross-session queries.

**Tests (5 new):** list, filter, get, versions, empty/labels.

**Code quality:** Solid. The `recordsForTurn` function is a clean extractor. Content types are properly discriminated (`markdown` | `json` | `list`). IDs are deterministic (`artifact:${kind}:${sessionId}:${turnId}`).

### P0-4 단일 셸 (commit `ef4a13b`)

**Spec alignment:** ✅ Matches §5.4.

- `Sidebar.tsx` deleted (215 lines removed).
- Settings moved into `AiScientistWorkspace` at `#/scientific/settings`.
- Legacy `/settings` redirects to `/scientific/settings`.
- `/studio` and `/browser` phantom redirects removed; `/browser/:runId` and `/report/:runId` kept for run progress.
- Rail nav updated: 실행 설정 → shell view, Library entry added.

**Tests:** Rail nav assertions updated for new routes.

**Code quality:** Clean deletion. The `App.tsx` simplification removes the wrapper `<div className="flex h-dvh">` + `<Sidebar>` pattern, leaving a flat `<main>` with routes. No dead imports remain.

### P0-5 Run 타임라인 (commits `babead0`, `3cd5af3`)

**Spec alignment:** ✅ Matches §5.5.

- `runTimeline.ts`: classifies progress strings into 7 stages (`targeting | research | evidence | hitl | council | report | eval`).
- Per-stage: `status` (pending/completed), `summary` (1-line), `keyEvents` (capped at 5), `label` (Korean).
- `CLASSIFY_ORDER` correctly prioritizes `hitl` over `evidence` to avoid keyword collision (e.g. "근거 승인" → hitl, not evidence).
- `RunTimeline.tsx` component: stage rows with status dots, summaries, raw event disclosure.
- Report stage shows artifact count (fixed in `3cd5af3` to avoid duplication).
- Unclassified events default to `"research"` — reasonable fallback.

**Tests (4 new):** classification, key-event cap, pending stages, empty progress.

**Code quality:** Well-structured. The keyword-based classifier is simple and testable. The `CLASSIFY_ORDER` priority comment explains the hitl-over-evidence rationale clearly.

---

## Scope Discipline

No unrelated changes detected across all 7 commits. Each commit touches only the files relevant to its spec section. The largest deletion (Sidebar.tsx, 215 lines) is explicitly called for by §5.4.

---

## Minor Observations (non-blocking)

1. **`disambiguateDuplicateThreadTitles`**: The first occurrence keeps its original title while subsequent ones get `· N`. This means if there are 3 conversations with the same label, they appear as `"제목"`, `"제목 · 2"`, `"제목 · 3"`. This matches the spec but could be slightly confusing — the first one doesn't show `· 1`. Non-blocking; spec-compliant.

2. **`listVersions`** in artifact library calls `listArtifacts()` twice (once via `getArtifact`, once directly). For local storage with small session counts this is fine; would need optimization at scale (P1 concern).

3. **`resumeRun` in bridge**: The `pendingInteractionRef` pattern works but adds a ref that mirrors state. This is a standard React pattern for accessing latest state in async callbacks — acceptable.

---

## Summary

| P0 Item | Status | Tests | Code Quality |
|---|---|---|---|
| P0-1 HITL 회복 | ✅ Implemented | 3 py + 2 ts | Good |
| P0-2 세션 제목 | ✅ Implemented | 3 ts | Good |
| P0-3 Artifact Library | ✅ Implemented | 5 ts | Good |
| P0-4 단일 셸 | ✅ Implemented | Updated existing | Good |
| P0-5 Run 타임라인 | ✅ Implemented | 4 ts | Good |

**Verdict: APPROVE** — All P0 specs implemented correctly, all verification checks pass, no blockers.
