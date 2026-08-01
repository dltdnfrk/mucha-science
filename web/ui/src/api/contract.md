# Mucha Science browser API contract

The standalone UI reads `VITE_MUCHA_SCIENCE_API_URL`; its default is
`http://127.0.0.1:8787`. `VITE_MUCHA_SCIENCE_WS_URL` may override only the
WebSocket origin. All request and response bodies are JSON unless noted.

## Commands

`POST /api/commands/{command}` receives the same argument object formerly sent
to the desktop command bridge. A successful command returns its JSON result;
commands with no result may return `204 No Content`. Errors use a non-2xx status
and a human-readable response body.

| command | request body | success result |
| --- | --- | --- |
| `start_pipeline` | `{ topic, pipeline, depth?, envs?, appRunId? }` | `PipelineLaunchReceipt` (legacy callers may ignore the body) |
| `cancel_pipeline` | `{ appRunId, generation }` | `PipelineCancellationAcknowledgement` |
| `send_action` | `{ action, appRunId?, generation? }` | no content |
| `pipeline_runtime_status` | `{}` | `PipelineRuntimeStatus` |
| `get_buffered_events` | `{ appRunId? }` | JSON array of backend event objects or JSON-line strings |
| `check_cli_status` | `{}` | `CliStatus[]` |
| `check_cli_smoke` | `{ name }` | `CliSmokeResult` |
| `open_cli_auth` | `{ name }` | `CliAuthLaunch` |
| `start_scientific_sidecar` | `{ sidecarPath? }` | no content |
| `stop_scientific_sidecar` | `{}` | no content |
| `write_envelope` | `{ envelope }` | no content |

The CLI command names are retained for UI compatibility; on a remote server
they describe provider capabilities managed by that server rather than binaries
on the browser host.

## Events

Connect to `GET /api/events?channel=backend_event` using WebSocket. An optional
`run_id` query parameter scopes pipeline events. The server sends one JSON
message per event, either the payload directly or `{ "payload": payload }`.

`backend_event` carries both flat pipeline events (`{ "event": "..." }`) and
`ai-scientist.v1` scientific envelopes. The client filters scientific envelope
kinds into event/snapshot/diagnostic, response, and error handlers. Closing the
socket unsubscribes. The server should replay buffered events in backend order
when `run_id` is supplied so a remounted run page can reconstruct its state.

## Compatibility pipeline socket

The copied protocol parser tests retain `WS /api/pipeline` for servers that
implement the existing `mucha-science.web.v1` command protocol. Messages include
`run.start`, `run.cancel`, `run.action`, `runtime.status`, and `run.subscribe`;
responses and events use the corresponding shapes in
`src/lib/webPipelineProtocol.ts`. The standalone UI's active execution path is
the HTTP command API plus `/api/events`; this socket is a compatibility boundary.
