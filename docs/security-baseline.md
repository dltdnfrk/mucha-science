# Mucha Science Security Baseline

Mucha Science is not an Express web server, so the immediate baseline is not
`helmet()`. The product is a local web UI talking to a loopback WebSocket
pipeline server, so the equivalent protection lives in the browser origin
boundary, the bind address, and local-runtime hygiene.

## Current shape

- Vite + React local web UI under `web/ui/`, started by `scripts/run-local-web.sh`.
- Python pipeline WebSocket server under `src/muchanipo/web/websocket_server.py`.
- Python CLI/event pipeline under `src/muchanipo/server.py`.
- No Express/Helmet server in the runtime path today.

## Baseline rules

### Browser origin allowlist

The WebSocket server owns mutable scientific-cycle state, so it must reject
cross-site handshakes instead of relying on the browser alone. `ALLOWED_ORIGINS`
in `src/muchanipo/web/websocket_server.py` enumerates the accepted origins.

Required properties:

- every allowed browser origin is a loopback origin (`127.0.0.1` or `localhost`)
- no wildcard origin, and no public-hostname origin
- an unlisted origin fails the handshake with HTTP 403 before any protocol
  action can execute

### Loopback-only dev server

Both servers bind to loopback only:

```text
ws://127.0.0.1:<port>/api/pipeline
http://127.0.0.1:5173
```

`create_websocket_server` raises `NonLoopbackHostError` for any non-loopback
host, and `scripts/run-local-web.sh` starts Vite with `--host 127.0.0.1`.
Do not use `0.0.0.0` unless a future reviewed remote-device workflow explicitly
requires it.

### Frame and message limits

The WebSocket transport caps inbound messages at 1 MiB and closes on binary
frames with code `1003`. Keep those limits when adding protocol messages;
large payloads belong in run artifacts on disk, not in the socket.

### Local Python/runtime boundary

If Mucha Science later exposes an HTTP API, it should default to:

- bind to `127.0.0.1`, not all interfaces
- no debug mode in production-like runs
- strict CORS allowlist
- no token, credential, or log dumping in responses
- no broad static file serving from user/workspace directories
- server implementation headers hidden where the framework supports it

### No Express/Helmet server

If Mucha Science later adds an Express/Node server, add Helmet at the server
edge:

```js
app.disable("x-powered-by");
app.use(helmet());
```

Until then, do not add unused Express/Helmet dependencies just for appearance.
The active security baseline is the origin allowlist + loopback bind + transport
limits, guarded by tests.

## Regression tests

The security baseline is guarded by:

```bash
python -m pytest tests/test_security_baseline.py tests/test_websocket_origin.py -q
```
