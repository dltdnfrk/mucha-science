# Muchanipo Tauri App

Tauri 2 desktop shell for Muchanipo. The Python CLI/TUI runner is the product
core; this app is a viewer/control shell over `python3 -m muchanipo serve`.

## Stack

- Tauri 2 (Rust shell, system WebView)
- Vite + React 18 + TypeScript (frontend)
- Subprocess bridge to `python3 -m muchanipo serve` for the research pipeline
- Same pipeline core as `python3 -m muchanipo run` and `python3 -m muchanipo tui`
- Bundled native scientific sidecar for the opt-in ai-scientist.v1 mode (Python is not required on the installed machine)

## Prerequisites

- Node 18+ and npm
- Rust 1.77+ (`rustup`)
- macOS: Xcode Command Line Tools (`xcode-select --install`)
- Python 3.11 with PyInstaller 6.11.1 (build time only)

## Run (dev)

```bash
cd app/muchanipo-tauri
npm install
npm run tauri dev
```

A native macOS window titled **Muchanipo** opens to the dark Muchanipo research workspace, with the idea intake composer ready to start a run. The negotiated scientific-cycle beta lives at the `/scientific` route.

For terminal-first usage without Tauri:

```bash
muchanipo
muchanipo "딸기 진단키트 시장성"
muchanipo tui "딸기 진단키트 시장성"
```

## Scientific workflow activation

The packaged scientific protocol is fail-closed and disabled by default. On macOS, create:

`~/Library/Application Support/ai.muchanipo.app/muchanipo/config.json`

with an explicit policy, for example:

```json
{
  "ai_scientist": {
    "enabled": true,
    "protocol_capability": true,
    "allow_new_cycles": true,
    "allow_external_result_import": false,
    "emergency_read_only": false,
    "approved_import_roots": []
  }
}
```

Enabling external-result import also requires one or more absolute, canonical, existing, non-symlink directories in `approved_import_roots`. Physical work remains external; the app only admits staged result bytes and records operator-asserted, unverified accountability.

## Build (release)

```bash
cd app/muchanipo-tauri
npm install
uv venv --python 3.11 /tmp/muchanipo-sidecar-venv
uv pip install --python /tmp/muchanipo-sidecar-venv/bin/python pyinstaller==6.11.1
MUCHANIPO_SIDECAR_PYTHON=/tmp/muchanipo-sidecar-venv/bin/python npm run tauri build
# → target/release/bundle/macos/Muchanipo.app
```

## Layout

```
app/muchanipo-tauri/
├── package.json           # Vite + React + Tauri CLI
├── Cargo.toml             # Cargo workspace
├── index.html
├── src/                   # React frontend
│   ├── main.tsx
│   └── App.tsx
└── src-tauri/             # Rust backend
    ├── Cargo.toml
    ├── build.rs
    ├── tauri.conf.json
    ├── capabilities/default.json
    └── src/main.rs
```

## Continuous Integration & Release (C35)

GitHub Actions는 main push, PR, tag 푸시마다 macOS-14 runner에서 자동 빌드합니다 (`.github/workflows/tauri-build.yml`).

### 결과물

- **PR**: debug 빌드만 — 머지 차단 검증용 (artifact 업로드 없음).
- **main / workflow_dispatch**: release 빌드 + `.app` + `.dmg` artifact 30일 보관.
- **`vX.Y.Z` 태그 push**: 위 + GitHub Release 자동 생성, `.dmg` 다운로드 링크 공유 가능.

### 배포 가이드

로컬 테스트 후 `git tag v0.1.0`으로 릴리즈 태그를 만들고, 태그를 origin에 게시하면
Actions가 자동 빌드해 Release 페이지에 `.dmg`를 등록한다. 태그 게시는 사람이 직접
터미널에서 수행한다 (자동화 경로에 두지 않는다).

협업자/서브 맥북에서 `Releases` 탭 → `.dmg` 다운로드 → 설치.

### 코드사인 (후속)

현재는 ad-hoc sign — 다른 머신에서 "확인되지 않은 개발자" 경고. 정식 배포 시 Apple Developer Certificate 추가:
- Repo Secrets: `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`
- workflow에 `tauri-action` (or sign step) 추가 — 별도 sprint 권장.
