# Mucha Science web UI

The browser is the Mucha Science product surface. It runs locally and connects
to the Python research pipeline over a loopback WebSocket.

```sh
cd /path/to/mucha-science
uv sync
npm --prefix web/ui ci
bash scripts/run-local-web.sh
```

Open `http://127.0.0.1:5173`. The launcher selects an available loopback port
for the pipeline and supplies it to Vite automatically. Stop it with `Ctrl-C`;
the WebSocket backend exits with the browser server.

Configure a live run from **실행 설정** in the scientific workspace:

- provider: MiMo, OpenCode Go, or MiMo followed by OpenCode Go fallback
- model: MiMo model and, when selected, an OpenCode model
- research effort: Quick, Deep, Max, or Superdeep pipeline depth

API keys remain only for the current browser session. Provider, model, and
research-effort preferences persist in the browser.
