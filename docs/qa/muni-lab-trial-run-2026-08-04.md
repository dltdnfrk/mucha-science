# MUNI lab 시운전 결과 — 2026-08-04

- 실행 시각: 2026-08-04 20:39–21:07 KST
- 기준 문서: `docs/qa/muni-lab-trial-scenarios.md`
- 브랜치/HEAD: `feat/mucha-science-live-web-research` / `76e092d`
- 설치 앱: `/Users/hyunjun/Applications/MUNI lab.app` (`ai.muni.lab`, 1.0.0)
- 라이브 주소: `http://127.0.0.1:65196/#/scientific`
- 결과 요약: **PASS 3 / PARTIAL 2 / FAIL 3 / BLOCKED 3**

> 실제 유료/외부 모델 호출은 하지 않았다. 연결 검증에는 가짜 QA 키만 잠시 사용했고, 공급자에 도달하기 전에 로컬 WebSocket 연결에서 실패했다. 가짜 키는 즉시 제거했다.

## 시나리오 결과

| # | 시나리오 | 결과 | 실제 관찰 |
|---|---|---|---|
| 1 | Spotlight 실행 | BLOCKED | 현재 샌드박스가 macOS LaunchServices와 통신하지 못해 `kLSServerCommunicationErr (-10822)`가 발생했다. 번들 이름·아이콘·서명·첫 화면 렌더는 별도로 확인했다. |
| 2 | 중복 실행 | BLOCKED | 같은 이유로 Spotlight/`open` 재실행 3회를 수행하지 못했다. 현재 관찰된 MUNILab 리스너는 PID 77234 한 개뿐이다. 소스상 reopen은 기존 URL을 기본 브라우저로 다시 열며 탭 재사용 로직은 없다. |
| 3 | 기본 연구 화면 | PASS (수정 후) | MUNI lab 브랜딩, favicon, Sidebar, 추천 질문, 3개 기본 출처, 설정 왕복을 확인했다. 최초에는 미제출 질문이 설정 왕복 뒤 사라졌으나 세션별 draft 보존으로 수정·재검증했다. 금지 문구는 사용자 화면에서 보이지 않았다. |
| 4 | 자격 증명 없는 실행 | PASS | 즉시 `error`로 끝났고 무한 스피너가 없었다. 필요한 OpenCode Go 키와 설정 경로를 안내했으며 입력창이 다시 활성화되었다. |
| 5 | Quick 과학 질문 | FAIL | 정확한 지정 질문을 제출했으나 `웹 연구 서버에 연결하지 못했습니다`로 종료했다. 후보/채택/근거/질문 단계에 도달하지 못했다. |
| 6 | 수정 요청 후 재검색 | FAIL | #5의 blocker로 실 UI 단계에 도달하지 못했다. 추가로 현재 HITL 액션은 `status`만 전송하며 수정 문구를 전송하지 않는다. 백엔드는 같은 `plan`을 한 번 다시 실행하므로 `임상시험 근거를 추가해줘`가 반영될 수 없다. |
| 7 | 공급자 타임아웃 | PARTIAL | 실제 공급자 중단은 #5 때문에 불가했다. 로컬 연구 서버 부재 및 저장된 실행 재연결 실패는 시험했다. 최초에는 전체 프론트엔드가 unhandled rejection으로 죽고 `running`이 남았으나 수정 후 명확한 `error`로 종료하고 입력 가능 상태로 복구된다. |
| 8 | 최종 보고서 | FAIL | #5 때문에 실제 보고서를 생성하지 못했다. 별도 `/report/:runId` 라우트는 있으나 현재 대화 흐름은 보고서를 inline 렌더하고 Markdown 내보내기만 제공한다. “실제 보고서 페이지로 이동” 동작이 연결되어 있지 않다. |
| 9 | 앱 종료 수명주기 | BLOCKED | 샌드박스에서 기존 MUNILab PID 종료가 `Operation not permitted`로 차단되었고 LaunchServices 재실행도 차단됐다. 정적 서버가 앱 프로세스에 종속된 구조인 것은 확인했다. |
| 10 | 재실행 및 세션 보안 | PARTIAL | 키는 `sessionStorage`에만 기록되고 legacy `localStorage` 값은 제거된다. 고유 가짜 키는 MUNI lab Chrome/Aside/Chrome 데이터 루트에서 평문 매치를 찾지 못했고 제거·reload 후 키가 없었다. 저장된 `running+generation` 복구 크래시는 수정했다. 다만 앱이 매 실행 랜덤 포트를 쓰므로 origin별 `localStorage` 대화 복구는 새 실행에서 끊길 위험이 확인된다. |
| 11 | 작은 화면 | PASS | Aside 창을 700×600으로 줄였을 때 페이지 viewport 367×523, 가로 overflow 0이었다. 연구·설정 화면과 Sidebar 접기/펼치기를 확인했다. 설정 컨트롤은 viewport 밖으로 나가지 않았다. compact utility 링크의 접근 가능한 이름이 사라지는 낮은 우선순위 문제가 남는다. |

## 핵심 결함

### QA-001 — 설치 앱에 연구 백엔드가 없음

- 심각도: **Blocker**
- 재현: 설치 앱에서 자격 증명을 준비한 뒤 Quick 질문 제출
- 기대: 검색/후보/채택/HITL/보고서 파이프라인 시작
- 실제: `웹 연구 서버에 연결하지 못했습니다. muchanipo-web 실행 상태를 확인하세요.`
- 근거:
  - Swift 앱은 정적 web bundle만 서빙한다: `packaging/macos/MUNILabApp.swift:104-147`
  - 빌드도 Swift 실행 파일과 Vite `dist`만 포함한다: `packaging/macos/build-app.sh:11-38`
  - 브라우저는 기본적으로 `ws://127.0.0.1:8765/api/pipeline`을 사용한다: `web/ui/src/lib/webPipelineClient.ts:199-202`
  - 앱 실행 중 8765 리스너가 없었다.
  - 백엔드를 수동 기동해도 앱 origin `http://127.0.0.1:65196`은 HTTP 403으로 거부되며 5173만 허용됐다: `src/muchanipo/web/websocket_server.py:34-40`

### QA-002 — 저장된 실행 재연결 실패가 프론트엔드 전체를 죽임

- 심각도: **High**
- 상태: **수정 및 라이브 재검증 완료**
- 수정:
  - 부분 subscription 실패 시 detach: `web/ui/src/hooks/useResearchPipelineBridge.ts:157-189`
  - 초기 reattach rejection을 catch하고 turn을 `error`로 확정: `web/ui/src/hooks/useResearchConversation.ts:132-156`
- 재검증: `running + generation=7` 상태를 주입한 뒤 reload. 수정 전에는 frontend boot rejection과 `running` 잔존, 수정 후에는 앱이 정상 렌더되고 `이전 연구 실행에 다시 연결하지 못했습니다`로 종료했다.

### QA-003 — 설정 왕복 시 미제출 질문 소실

- 심각도: **Medium**
- 상태: **수정 및 라이브 재검증 완료**
- 수정: 대화 session별 draft를 `sessionStorage`에 보관하고 제출 성공 시 삭제: `web/ui/src/pages/ResearchConversationPage.tsx:13-69,173-194`
- 재검증: `임시 입력 유지 확인 - 수정 후` 입력 → 설정 → 뒤로. 원문 유지 확인 후 테스트 draft 삭제.

### QA-004 — 실패한 turn에 “실행 투영을 기다리는 중” 표시

- 심각도: **Medium**
- 상태: **수정 및 라이브 재검증 완료**
- 수정: error/canceled/complete 상태별 빈 activity 문구 분기: `web/ui/src/components/ai-scientist/ResearchConversationTurn.tsx:32-40`

### QA-005 — 수정 요청 문구가 재검색에 전달되지 않음

- 심각도: **High**
- 상태: 미수정
- 근거: HITL 액션은 `gate`와 `status`만 전송한다 (`useResearchPipelineBridge.ts:214-245`). 백엔드는 동일 `plan`을 재실행한다 (`idea_to_council.py:509-533`).

### QA-006 — 대화 보고서와 실제 보고서 페이지 연결 부재

- 심각도: **High**
- 상태: 미수정
- 근거: 대화는 inline markdown과 “연구 기록 내보내기”만 제공한다 (`ResearchConversationTurn.tsx:84-110`). 별도 report route는 존재하지만 대화에서 연결되지 않는다 (`App.tsx:88-97`).

### QA-007 — 랜덤 포트와 origin별 저장소 충돌

- 심각도: **High**
- 상태: 미수정
- 앱은 실행마다 임의의 loopback port를 선택한다. 대화/설정은 브라우저 `localStorage`이므로 새 포트에서 이전 origin 데이터가 보이지 않는다.

### QA-008 — 작은 화면 compact 링크의 접근 가능한 이름 소실

- 심각도: **Low**
- 상태: 미수정
- 367px viewport에서 클릭 크기와 overflow는 합격했으나 compact 연구 도구 링크가 accessibility tree에서 이름 없는 `link`로 노출됐다.

## 적용한 코드 변경

- `web/ui/src/hooks/useResearchPipelineBridge.ts`
- `web/ui/src/hooks/useResearchPipelineBridge.test.ts`
- `web/ui/src/hooks/useResearchConversation.ts`
- `web/ui/src/components/ai-scientist/ResearchActivitySummary.tsx`
- `web/ui/src/components/ai-scientist/ResearchConversationTurn.tsx`
- `web/ui/src/components/ai-scientist/ResearchConversationTurn.test.tsx`
- `web/ui/src/pages/ResearchConversationPage.tsx`

설치 앱도 현재 소스로 재빌드했다. source `dist/index.html`과 설치 bundle `index.html` SHA-256이 일치하고 codesign 검증이 통과했다.

## 검증 게이트

- Web unit: **36 files, 214 passed**
- Web production build: **PASS**
- Focused backend WebSocket/security/runtime: **24 passed**
- Installed app signature: **PASS**
- Full Python: **1800 passed, 4 skipped, 4 failed, 66 subtests passed**
  - Python 코드에 손대지 않은 이번 TS 패치와 무관한 기존 불일치다.
  - `test_pipeline_runner`: live preflight 검증 순서 기대 불일치
  - `test_runtime_paths`: vault placeholder fallback 기대 불일치
  - sidecar build 2건: 현재 repo `.venv`는 Python 3.12이지만 builder는 3.11을 요구함. 로컬에 Python 3.11.14는 있으나 해당 pinned sidecar 의존성이 설치되지 않았다.

## 다음 우선순위

1. **P0:** macOS bundle이 연구 WebSocket backend를 실제로 소유·기동·종료하도록 sidecar 통합
2. **P0:** random app origin을 안전하게 인증/허용하거나 단일 고정 origin으로 통합
3. **P0:** #5 → #6 → #8을 실제 외부 연구로 다시 시운전
4. **P1:** HITL 수정 텍스트를 action schema와 연구 plan에 반영
5. **P1:** 대화 최종 보고서를 `/report/:runId` 저장소/라우트와 연결
6. **P1:** 고정 origin 또는 native persistence로 재실행 세션 복구
