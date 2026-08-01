# Mucha Science web UI

Standalone Vite + React copy of the Mucha Science desktop UI.

```sh
npm ci
npm run dev
```

The browser connects to `http://127.0.0.1:8787` by default. Set
`VITE_MUCHA_SCIENCE_API_URL` to change the HTTP API origin and optionally
`VITE_MUCHA_SCIENCE_WS_URL` to change the WebSocket origin. See
[`src/api/contract.md`](src/api/contract.md) for the server contract.
