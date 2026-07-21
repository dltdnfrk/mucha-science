# Pi Autoresearch External Code Review: Muchanipo Desktop/TUI

## Summary

Reviewed the current desktop UI/Tauri/Swift changes in the requested scope, focusing on the React Tauri app, Rust bridge, Swift native shell, and Python event server contract. I could not use `git diff` from this pi session because shell commands require interactive approval, so the review is based on the current working tree files in the scoped areas rather than a verified `HEAD~1..HEAD` diff. I also checked TypeScript LSP diagnostics for `app/muchanipo-tauri/src` and found no static TS errors.

**Recommendation: REQUEST CHANGES.** There are several blocking runtime/contract issues. The Tauri React UI currently never starts the backend pipeline, and the mounted streaming components listen for an event schema (`type`, `delta`, `council_token`, `council_round_end`) that does not match the Rust/Python protocol (`event`, `markdown`, `council_persona_token`, `council_round_done`). The Swift shell has a separate decode mismatch for interview options emitted as strings.

## Critical findings

### 1. Tauri React flow never invokes `start_pipeline`, so the Python backend is never started

**Evidence**

- `app/muchanipo-tauri/src/lib/tauri.ts:30-31` defines `startPipeline(topic)` as the wrapper around `invoke("start_pipeline", { topic })`.
- `app/muchanipo-tauri/src/pages/HomePage.tsx:20-22` only navigates to `/interview` with the topic; it does not start the pipeline.
- `app/muchanipo-tauri/src/pages/InterviewPage.tsx:34-39` only navigates to `/council` with a local placeholder answer; it does not call `startPipeline` or `send_action`.
- `app/muchanipo-tauri/src/pages/CouncilPage.tsx:30-31` mounts `<InterviewQuestion />` and `<CouncilMonitor />`, both of which wait for `backend_event` messages, but no code starts the process before they mount.
- Rust command registration exists in `app/muchanipo-tauri/src-tauri/src/main.rs:14-15` and process launch exists in `app/muchanipo-tauri/src-tauri/src/python_bridge.rs:36-42`, so the missing piece is frontend orchestration.

**Impact**

The desktop Tauri app appears to progress through static routes, but the actual backend pipeline never runs. The interview/council/report components stay in waiting/empty states forever unless some external code invokes the command.

**Suggested fix**

Introduce a single pipeline/session owner in React, for example a `PipelineProvider` or route-level controller that:

1. Calls `startPipeline(topic)` when a new topic is submitted.
2. Subscribes once to `backend_event` before or immediately after starting.
3. Stores latest backend state in React context or route state.
4. Sends the backend interview answer via `sendAction({ action: "interview_answer", q_id, answer })` instead of using the placeholder `InterviewPage` state.
5. Navigates based on backend `phase_change`/`done` events, not on static button flow.

**Verification commands**

```bash
cd app/muchanipo-tauri
npm run build
npm run tauri dev
# Start a topic and verify the Rust command launches `python3 -m muchanipo serve`,
# the backend emits an interview question, answer submission unblocks stdin,
# council events stream, and REPORT.md chunks render.
```

## High findings

### 2. React event listeners check `payload.type`, but Rust/Python emit `event`

**Evidence**

- Rust serializes and emits a `BackendEvent` with an `event` field in `app/muchanipo-tauri/src-tauri/src/events.rs:5-8` and forwards it through Tauri in `app/muchanipo-tauri/src-tauri/src/python_bridge.rs:144-145`.
- Python emits JSON lines using `event`, e.g. `src/muchanipo/server.py:54-58` and `src/muchanipo/events.py:50-55`.
- React component listeners use `payload.type`:
  - `app/muchanipo-tauri/src/components/InterviewQuestion.tsx:49-52`
  - `app/muchanipo-tauri/src/components/ReportViewer.tsx:47-50`
  - `app/muchanipo-tauri/src/components/CouncilMonitor.tsx:52-64`
- `app/muchanipo-tauri/src/lib/tauri.ts:3-17` defines the actual Tauri payload shape with `event`, but the mounted components import `app/muchanipo-tauri/src/lib/types.ts`, which defines a separate incompatible `type`-based schema.

**Impact**

Even if the pipeline is started, the UI ignores every real backend event because `payload.type` is undefined. Interview questions, council updates, report chunks, done, and errors will not render.

**Suggested fix**

Unify the frontend event model around the actual protocol. Prefer one shared `BackendEvent` type that uses `event`, or normalize at the Tauri boundary:

```ts
listen<RawBackendEvent>("backend_event", ({ payload }) => {
  const normalized = normalizeBackendEvent(payload); // maps event -> discriminant and field names
  dispatch(normalized);
});
```

Do not keep both `lib/tauri.ts` and `lib/types.ts` as competing canonical schemas.

**Verification commands**

```bash
cd app/muchanipo-tauri
npm run build
# Add/execute a small component/unit test that feeds { event: "interview_question", data: ... }
# and asserts InterviewQuestion renders it.
```

### 3. React council/report schema names do not match Python event names and payload fields

**Evidence**

- Python event names are canonicalized in `src/muchanipo/events.py:16-25` as `council_persona_token`, `council_round_done`, and `report_chunk`.
- Python emits council persona tokens at `src/muchanipo/server.py:91-95` with fields `persona` and `delta`, but no `type: "council_token"`.
- Python emits report chunks at `src/muchanipo/server.py:105-110` with `markdown=body`, not `delta`.
- React council code expects `event.type === "council_token"` and `event.type === "council_round_end"` in `app/muchanipo-tauri/src/components/CouncilMonitor.tsx:52-64`.
- React report code expects `payload.type === "report_chunk"` and appends `payload.delta` in `app/muchanipo-tauri/src/components/ReportViewer.tsx:47-50`.

**Impact**

After fixing the `event` vs `type` discriminant, council and report streaming would still fail: persona tokens and round completion events use different names, and report chunks append `undefined` instead of markdown content.

**Suggested fix**

Either change Python/Rust to emit the frontend schema, or more safely adapt React to the backend schema:

- `event === "council_persona_token"` -> append `delta`
- `event === "council_round_done"` -> mark the current/identified round done
- `event === "report_chunk"` -> append `markdown` (or support both `markdown` and `delta` if future streaming uses deltas)
- `interview_question` -> extract `data.q_id`, `data.text`, and normalize string options.

**Verification commands**

```bash
python -m muchanipo serve --topic contract-smoke --no-wait
cd app/muchanipo-tauri
npm run build
# Feed the emitted JSON lines through frontend normalization tests and assert all event kinds update UI state.
```

### 4. Swift native shell fails to decode the current interview question because Python emits option strings but Swift expects option objects

**Evidence**

- Python emits the interview question data with string options at `src/muchanipo/server.py:60-63`:
  - `"options": ["A. ship a product", "B. write a report", "C. learn"]`
- Swift models options as objects in `app/Muchanipo/Sources/Muchanipo/Event.swift:14-17` (`let options: [InterviewOption]`).
- `InterviewOption` is a keyed object type in `app/Muchanipo/Sources/Muchanipo/Event.swift:24-29`.
- The event stream decodes each JSON line into `BackendEvent` in `app/Muchanipo/Sources/Muchanipo/EventStream.swift:33-51`, and `PythonRunner` stops consuming on decode errors at `app/Muchanipo/Sources/Muchanipo/PythonRunner.swift:38-45`.

**Impact**

The Swift native shell will hit a decode error as soon as the first `interview_question` is emitted. Because the backend is waiting for stdin after that question, the UI cannot answer it and the pipeline stalls.

**Suggested fix**

Make the protocol canonical and update one side:

- Prefer emitting structured option objects from Python (`[{"id":"A", "label":"ship a product"}, ...]`) and update tests accordingly; or
- Make Swift `InterviewOption` decode from either a string or an object for backward compatibility.

Also add an end-to-end Swift decoding test using actual `muchanipo serve --no-wait` output.

**Verification commands**

```bash
python -m muchanipo serve --topic swift-contract --no-wait > /tmp/muchanipo-events.jsonl
cd app/Muchanipo
swift test
# Include/verify a test that decodes every line from /tmp/muchanipo-events.jsonl as BackendEvent.
```

## Medium findings

### 5. Tauri process launch depends on ambient `python3`/environment and likely fails from a packaged app

**Evidence**

- Rust launches `Command::new("python3")` in `app/muchanipo-tauri/src-tauri/src/python_bridge.rs:36`.
- It sets `.current_dir(workspace_root())` in `app/muchanipo-tauri/src-tauri/src/python_bridge.rs:37-38`.
- `workspace_root()` is derived from compile-time `CARGO_MANIFEST_DIR` parent traversal in `app/muchanipo-tauri/src-tauri/src/python_bridge.rs:150-156`.
- The Python smoke tests explicitly set `PYTHONPATH` to the repo root before invoking `python -m muchanipo` in `tests/test_muchanipo_server.py:19-31`; the Tauri launcher does not set `PYTHONPATH`.

**Impact**

This may work in a developer checkout, but packaged `.app` execution is likely to fail with `No module named muchanipo` or use the wrong Python interpreter/module version. It also relies on the user's `PATH` and installed `python3`, which is brittle for a desktop distribution.

**Suggested fix**

Define a packaging/runtime strategy:

- For development, explicitly set `PYTHONPATH` to the repo root or invoke the project venv interpreter.
- For release, bundle the Python runtime/module or expose a configured path in app settings.
- Emit a clear user-facing error if Python/module discovery fails.
- Add CI smoke tests for `npm run tauri build` and a launch smoke that verifies `start_pipeline` can import `muchanipo`.

**Verification commands**

```bash
cd app/muchanipo-tauri
npm run tauri build
./src-tauri/target/release/muchanipo-tauri
# Start a topic from outside the repo cwd and verify Python import succeeds.
```

### 6. Report route can miss streamed chunks because listeners are mounted per route and no state is retained

**Evidence**

- `ReportViewer` subscribes to `backend_event` only while mounted in `app/muchanipo-tauri/src/components/ReportViewer.tsx:41-55`.
- `CouncilPage` lets users navigate to `/report` manually in `app/muchanipo-tauri/src/pages/CouncilPage.tsx:19-24`.
- Backend emits a single report chunk before `done` in `src/muchanipo/server.py:105-114`.

**Impact**

If report chunks are emitted before `ReportViewer` mounts, they are lost. The report page then remains empty even though the backend completed and wrote `REPORT.md`.

**Suggested fix**

Centralize event subscription and store report content/path in an app-level session store. Route components should render from retained state, not from only live Tauri events. Optionally read `report_path` on `done` as a fallback.

**Verification commands**

```bash
# In Tauri dev, start a pipeline, wait until after REPORT phase, then navigate to Report.
# The already-emitted report must still render.
```

### 7. No frontend/Rust contract tests cover the desktop event protocol

**Evidence**

- Existing tests in `tests/test_muchanipo_server.py` validate Python server events and actions, but they do not decode those events through the Rust bridge, React normalization, or Swift models.
- TypeScript diagnostics pass for `app/muchanipo-tauri/src`, but the schema mismatch is runtime-only because the frontend types are self-consistent yet not consistent with backend output.

**Impact**

The current regressions are exactly the type of cross-language contract mismatch that unit tests should catch. Static TypeScript alone is insufficient here.

**Suggested fix**

Add protocol fixture tests:

1. Generate/commit sample JSONL events from `muchanipo serve --no-wait`.
2. Test Swift `BackendEvent` decoding against the fixture.
3. Test React normalization/reducers against the same fixture.
4. Test Rust `BackendEvent::from_json_line` against the fixture.
5. Add a Tauri command smoke test where practical.

**Verification commands**

```bash
pytest tests/test_muchanipo_server.py
cd app/muchanipo-tauri && npm run build
cd app/muchanipo-tauri/src-tauri && cargo test
cd app/Muchanipo && swift test
```

## Low findings

### 8. Tauri CSP is disabled while rendering backend-provided Markdown/Mermaid

**Evidence**

- Tauri config disables CSP with `"csp": null` in `app/muchanipo-tauri/src-tauri/tauri.conf.json:24-25`.
- `ReportViewer` renders backend-provided markdown via ReactMarkdown and then injects Mermaid-rendered SVG through `pre.innerHTML = svg` in `app/muchanipo-tauri/src/components/ReportViewer.tsx:68-72`.
- Mermaid is initialized with `securityLevel: "strict"` in `app/muchanipo-tauri/src/components/ReportViewer.tsx:18-24`, which helps, but CSP is still a defense-in-depth control for desktop webviews.

**Impact**

This is not currently a demonstrated exploitable issue because ReactMarkdown escapes raw HTML by default and Mermaid strict mode is enabled. However, disabling CSP in a desktop shell increases blast radius if later plugins/options allow raw HTML or a Mermaid sanitization bypass appears.

**Suggested fix**

Set a restrictive CSP for the Tauri app and keep Markdown raw HTML disabled. Avoid `innerHTML` where possible, or keep Mermaid output constrained/sanitized and covered by CSP.

**Verification commands**

```bash
cd app/muchanipo-tauri
npm run tauri build
# Verify Markdown and Mermaid still render under the configured CSP.
```

## Notes on unstaged working tree changes

I could not inspect unstaged changes via `git status`/`git diff` because shell commands are blocked in this pi session. The findings above are based on the current file contents visible through pi read/search tools.

## Verification performed

- Read scoped React, Rust, Swift, and Python files.
- Ran LSP diagnostics on `app/muchanipo-tauri/src`: **0 TypeScript diagnostics**.

## Merge-blocking items

Block merge until at least these are fixed and verified:

1. Start the backend pipeline from the Tauri UI and wire answer submission to backend stdin.
2. Collapse frontend event types to one canonical schema matching Rust/Python (`event` or a deliberate normalized equivalent).
3. Fix council/report event name and payload-field mismatches.
4. Fix Swift interview option decoding or Python option emission.
5. Add cross-language protocol tests so future schema drift is caught before review.
