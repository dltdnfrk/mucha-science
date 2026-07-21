#!/usr/bin/env bash
# E2E smoke — Python pipeline 단독 실행 → 6 chapter MBB 보고서까지 검증.
# Tauri shell 없이 backend만 확인. PR 머지 전 sanity check.

set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PYTHON_BIN="${PYTHON_BIN:-}"
if [[ -z "$PYTHON_BIN" ]]; then
  # pyproject requires Python >=3.11; prefer explicit modern interpreters over
  # whatever `python`/`python3` happens to be on PATH (macOS often ships 3.8/3.9).
  for candidate in "$ROOT/.venv/bin/python" python3.12 python3.11 python python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
if [[ -z "$PYTHON_BIN" ]]; then
  echo "[smoke] no Python >=3.11 interpreter found on PATH (set PYTHON_BIN)" >&2
  exit 1
fi
TMP="${TMPDIR:-/tmp}"
REPORT="$TMP/muchanipo_smoke_report.md"
EVENTS="$TMP/muchanipo_smoke_events.jsonl"

rm -f "$REPORT" "$EVENTS"

cd "$ROOT"

echo "[smoke] running full pipeline…"
MUCHANIPO_OFFLINE=1 "$PYTHON_BIN" -m muchanipo serve \
  --topic "딸기 진단키트 시장성 (smoke)" \
  --pipeline full \
  --no-wait \
  --report-path "$REPORT" \
  > "$EVENTS"

# 1) report file exists
if [[ ! -f "$REPORT" ]]; then
  echo "[smoke] FAIL: report not generated at $REPORT"
  exit 1
fi

# 2) all six chapters present
for n in 1 2 3 4 5 6; do
  if ! grep -q "^## Chapter $n" "$REPORT"; then
    echo "[smoke] FAIL: Chapter $n missing"
    exit 1
  fi
done

# 3) all 8 stage events emitted
for s in intake interview targeting research evidence council report finalize; do
  if ! grep -q "\"stage\": \"$s\"" "$EVENTS"; then
    echo "[smoke] FAIL: stage $s missing in events"
    exit 1
  fi
done

# 4) final_report event with markdown
if ! grep -q "\"event\": \"final_report\"" "$EVENTS"; then
  echo "[smoke] FAIL: final_report event missing"
  exit 1
fi

# 5) done event terminates the stream
if ! tail -1 "$EVENTS" | grep -q "\"event\": \"done\""; then
  echo "[smoke] FAIL: stream did not end with done event"
  exit 1
fi

echo "[smoke] PASS: 6 chapters + 8 stages + final_report + done"
echo "[smoke] Report : $REPORT"
echo "[smoke] Events : $EVENTS"
