# MUNI lab × Claude Science 0.1.25 구조 이식 구현 명세

- **작성일**: 2026-08-04
- **대상 앱**: MUNI lab (`~/Documents/MUNI/muni-lab`, UI `web/ui`, 라이브 `http://127.0.0.1:5173`)
- **기준축**: Claude Science 0.1.25 라이브 재검증 (`http://localhost:8766`, runtime `0.1.25-release`)
- **스택**: React 18 + Vite + Tailwind + HashRouter · bun · WebSocket pipeline (`mucha-science.web.v1`)
- **브랜치 참고**: `feat/mucha-science-live-web-research` (작업 전 `git status` 재확인)
- **관련 문서**:
  - 통합 역설계: `Claude_Science_0.1.25_UI_UX_기능_역설계_및_온톨로지랩_MUNI_lab_이식_구현_명세_2026-08-04.md`
  - 선행 UX 분석: `온톨로지랩_MUNI_lab_UI_UX_분석과_Claude_Science_구조_이식_방안_2026-08-04.md`
- **라벨**: `CS-observed` / `MUNI-observed` / `recommendation`

---

## 0. 한 줄 결론

MUNI lab은 **공통 셸 골격이 Claude Science에 가장 가깝다**(대화 레일 + 헤더 + 중앙 타임라인 + 우측 패널).  
부족한 것은 껍데기가 아니라 **지속성 하니스**다.

```
지금:   Session(localStorage) → Turn → progress/sourceIds/artifactIds(문자열) → error 문자열
목표:   Project → Session → Run → ArtifactVersion → Provenance → VerificationCheck
        + HumanDecision(HITL) 회복 경로
```

이식 대상은 색/버튼이 아니라:

1. Project 컨텍스트  
2. 제목 있는 Session  
3. 회복 가능한 Run  
4. 실행 중·완료 산출물의 Artifact 승격  
5. Library + 버전 뷰어 + Provenance  
6. Reviewer(자동)와 HITL(인간) 분리  
7. **단일 셸** (scientific / settings 이중 셸 제거)

---

## 1. 기준축: Claude Science에서 가져올 것만 (MUNI 관점)

### 1.1 가져올 것 (semantics)

| CS 패턴 | MUNI에 필요한 이유 |
|---|---|
| Dashboard = Projects + Recent sessions | 연구 단위 탐색, 제목 중복 해소의 상위 구조 |
| Project 좌측 레일 Sessions/Files/Compute | 지금 rail은 대화 목록+도구 링크만 있음 |
| 탭 스트립 + Split/Merge | 보고서·노트북·세션 동시 열람 |
| Composer `@artifact #session /skill` | 후속 질문이 산출물/세션을 명시 참조 |
| Library 그룹(업로드/세션) + Grid/List | Live artifacts 허상 제거 |
| ArtifactVersion + Show changes | 보고서 수정 이력 |
| Provenance 5탭 | 39 logs를 accordion으로 던지는 문제 해소 |
| Reviewer finding 카드 | validation 패널을 claim-level로 격상 |
| Session options: Auto-review / Reviewer model / Delegation | 실행 설정과 연구 셸 통합 |
| Plan 승인 ≠ Reviewer ≠ HITL 지식 게이트 | 지금 HITL이 하드페일로 붕괴하는 원인 분리 |

### 1.2 가져오지 말 것

- Bun/SQLite monorepo shape  
- CS 색/타이포  
- 8767 MCP-UI proxy 전체를 당장 복제  
- BOOKMARKER (이 설치에서도 비활성)  
- `lineage_messages` 컬럼 맹복제  

### 1.3 CS 실측 앵커 (이 세션)

- 포트 8766, version 0.1.25  
- Library / Provenance / Reviewer / Compose 분리 표면 라이브 snapshot  
- DB: projects 3, frames 92, artifacts 213, versions 234, deps 391, checks 62  
- OPERON: artifacts-not-answers  
- REVIEWER: trace-only, python/bash/save_artifacts/web_search 제외  

---

## 2. MUNI lab 현황 (MUNI-observed)

### 2.1 코드 지도

| 영역 | 경로 |
|---|---|
| 라우트/이중 셸 | `web/ui/src/App.tsx` |
| 연구 셸 | `pages/AiScientistWorkspace.tsx` |
| 대화 | `pages/ResearchConversationPage.tsx` |
| 턴 UI | `components/ai-scientist/ResearchConversationTurn.tsx` |
| 우측 패널 | `components/ai-scientist/ResearchOutputPanel.tsx` |
| 레일 | `components/ai-scientist/ResearchConversationRail.tsx` |
| 세션 훅 | `hooks/useResearchConversation.ts` |
| WS 브리지 | `hooks/useResearchPipelineBridge.ts` |
| 턴 데이터 | `lib/researchConversation.ts` |
| 저장 | `lib/researchConversationStorage.ts` |
| 제목 유틸(미연결) | `lib/researchConversationPresentation.ts` `createThreadLabel` |
| 파이프라인 WS | `lib/webPipelineClient.ts`, `src/muchanipo/web/*` |
| HITL 서버 | `src/muchanipo/server.py` `JSONLineHITLAdapter` |
| evidence 재게이트 | `src/pipeline/idea_to_council.py` |
| live hard-fail | `src/runtime/live_mode.py` `assert_live_hitl` |
| resumable 계약(미연결) | `src/hitl/plannotator_review_artifact.py` |

### 2.2 라우트 실측

```
#/scientific              → chat (AiScientistWorkspace)
#/scientific/sources      → sources panel
#/scientific/validation   → validation panel
#/settings, #/muni, #/browser/:runId, #/report/:runId → 레거시 Sidebar 셸
#/browser, #/studio/*     → scientific redirect (허상)
```

Sidebar에 “Live artifacts → /browser”가 남아 실제 라이브러리가 없음.

### 2.3 라이브 localStorage 감사 (2026-08-04)

키 prefix: `muchanipo.research-conversation.v1.*`

| session | status | logs | sources | artifacts | final report |
|---|---|---:|---:|---:|---|
| 다수 error 세션 | error | 24–63 | 2–12 | **0** | N |
| `session-bae42855-…` | **complete** | 42 | 4 | **2** | Y |
| 활성 error 세션 | error | 39 | 6 | 0 | N |

공통 실패 문구:

```
live mode requires approved HITL gate 'evidence'; got 'changes_requested'
```

UI: 실행 중단 문장만, **재승인/재개 버튼 없음**.  
레일 제목: 프롬프트 전체 복붙 → 9개 중 고유 문장 2종 수준.

### 2.4 HITL 실패 체인 (end-to-end)

```
1. 서버 emit hitl_gate(evidence) + options approved|changes_requested
2. ResearchInteractionCard → hitl_decision (comment 필수 if changes)
3. idea_to_council: changes_requested면 research 1회 보강 후 재게이트
4. 재게이트도 approved 아니면 assert_live_hitl → LiveModeViolation
5. pipeline_error/error 이벤트로 UI completeRun(..., "error")
6. Turn에 recoveryActions 없음 → 사용자 막힘
```

모순: `plannotator_review_artifact`는 `changes_requested`를 **resumable**로 정의. scientific chat 경로가 이를 무시.

### 2.5 산출물 0 문제의 정확한 의미

- 이벤트에 `artifact_ids`가 안 오면 0  
- 성공 턴은 2개까지 기록됨 → **승격 로직 전무가 아니라 Library/뷰어/버전 부재**  
- `formatResearchArtifactLabel`만 있고 열람 라우트 없음  
- 보고서는 turn.finalReport로 대화에 렌더될 뿐 Artifact 시스템이 아님  

### 2.6 강점 (깨지 말 것)

1. 실행 타임라인 요약 (“N초 · X 로그 · 출처 Y · 산출물 Z”)  
2. 채택/제외 출처 + DOI  
3. 정직한 실패 노출  
4. HITL 카드 + comment 강제 테스트  
5. 검색 경로·quality readiness 구조  
6. 접근성/반응형 CSS  

---

## 3. 목표 정보구조 (recommendation)

### 3.1 단일 셸

```
ms-science-shell (유일)
├─ Rail
│  ├─ New session
│  ├─ Sessions (createThreadLabel, 그룹 Today/Older)
│  ├─ Library (badge = committed artifacts)
│  ├─ Sources
│  ├─ Validation / Review
│  └─ Settings (기존 /settings 내용 이식)
├─ Header
│  ├─ Project · Session title
│  ├─ Search
│  └─ Panel toggle
├─ Center
│  ├─ Tab strip: Session | Artifact | Notebook(optional)
│  ├─ Transcript + Run timeline
│  ├─ HITL / recovery bar
│  └─ Composer (@artifact #session /skill)
└─ Right tabs
   Artifacts | Sources | Review | Run/Provenance
```

### 3.2 라우트 목표

| 경로 | 역할 |
|---|---|
| `#/scientific` | chat |
| `#/scientific/library` | artifact library |
| `#/scientific/library/:artifactId` | viewer + versions + provenance |
| `#/scientific/sources` | sources |
| `#/scientific/validation` | validation/reviewer |
| `#/scientific/settings` | settings in-shell |
| `#/browser`, `#/studio` | 삭제 또는 library로 대체 |
| `#/muni` | Project template 또는 숨김(fetch 수정 전) |
| 레거시 `#/settings` | scientific/settings로 redirect |

---

## 4. 데이터 모델 이식

### 4.1 현재 타입 (요약)

```ts
Session { sessionId, turns[] }
Turn {
  turnId, runId, prompt,
  progress[], reportChunks[], finalReport,
  sourceIds[], artifactIds[], eventIds[]
}
Runtime { status, activity?, error?, generation?, ... }
```

localStorage only. Project 없음. Run 메타는 runtime 맵에 흩어짐.

### 4.2 목표 프리미티브

```ts
type Project = {
  id: string
  name: string
  createdAt: number
  updatedAt: number
}

type Session = {
  id: string
  projectId: string
  title: string          // createThreadLabel 결과
  createdAt: number
  updatedAt: number
  status: 'active' | 'archived'
}

type RunStatus =
  | 'queued'
  | 'planning'
  | 'running'
  | 'awaiting_human'
  | 'reviewing'
  | 'completed'
  | 'failed'
  | 'cancelled'

type Run = {
  id: string
  sessionId: string
  projectId: string
  status: RunStatus
  phase?: string
  generation?: number
  startedAt: number
  completedAt?: number
  error?: string
  hitl?: HitlState
  totals: { logs: number; sources: number; artifacts: number }
}

type HitlState = {
  gate: 'plan' | 'brief' | 'evidence' | 'report'
  status: 'pending' | 'approved' | 'changes_requested'
  comment?: string
  resumable: boolean
  revisionCount: number
  maxRevisions: number  // default 1 (현 파이프라인과 동일) 후 설정화
}

type Artifact = {
  id: string
  projectId: string
  sessionId?: string
  runId?: string
  filename: string
  kind: 'report' | 'source-audit' | 'source-card' | 'quality-summary' | 'ledger' | 'upload' | 'other'
  latestVersionId: string
}

type ArtifactVersion = {
  id: string
  artifactId: string
  versionNumber: number
  contentType: string
  checksum: string
  storagePathOrInlineRef: string
  createdAt: number
  parentVersionId?: string
  lifecycle: 'ephemeral' | 'committed' | 'superseded'
  runId?: string
}

type ArtifactDependency = {
  artifactVersionId: string
  dependsOnVersionId: string
  referenceName?: string
}

type VerificationCheck = {
  id: string
  runId?: string
  artifactVersionId?: string
  claim: string
  verdict: 'pass' | 'warn' | 'fail' | 'inconclusive'
  status: 'open' | 'resolved' | 'unaddressed'
  evidence?: string
  reviewerModel?: string
  createdAt: number
}

type HumanDecision = {
  id: string
  runId: string
  gate: string
  decision: 'approved' | 'changes_requested' | 'rejected' | 'aborted'
  comment?: string
  actor: string
  createdAt: number
}
```

### 4.3 저장 전략

**P0 (최소 침습)**  
- localStorage schema `v1` → `v2`  
- Session에 `title`, `projectId`  
- Turn/Runtime에 `runStatus`, `hitl`, `artifacts: ArtifactRef[]`  
- migrate 함수 1회  

**P1**  
- 서버 `CycleRepository` / pipeline artifact staging과 정렬  
- run 디렉터리의 REPORT.md, ledger를 ArtifactVersion storagePath로 연결  

### 4.4 상태기계 (Run)

```
queued → planning → running ⇄ awaiting_human
running → reviewing → completed
any active → cancelled
awaiting_human → running (resume) | failed | cancelled
revision exhausted + still not approved → awaiting_human (NOT silent hard-fail)
  optional: user chooses "fail run"
```

**불변식**

1. `changes_requested`만으로 `status=error` 금지 (사용자 회복 UI 없이)  
2. VerificationCheck ≠ HumanDecision  
3. ephemeral artifact는 completed 시 commit 또는 drop 명시  
4. artifactIds 문자열 배열만으로 Library 구성 금지 → 구조화 ref  

---

## 5. 기능별 이식 명세

### 5.1 P0-1 HITL 회복 (최우선)

**백엔드**

- `assert_live_hitl` 호출 전에 scientific/web 경로 옵션:
  - `on_changes_requested`: `resume` | `fail`  
  - default for chat UI: **resume** (emit `hitl_gate` again or `run_awaiting_human`)  
- revision loop 소진 시 `LiveModeViolation` 대신 구조화 이벤트:

```json
{
  "event": "hitl_resume_required",
  "gate": "evidence",
  "revision_count": 1,
  "resumable": true,
  "message": "근거 승인이 필요합니다."
}
```

- `execution_cancelled` / `pipeline_error`와 구분  

**프론트**

`ResearchConversationTurn` error 대신 recovery card:

- [다시 승인 UI 열기]  
- [수정 의견 보내며 재개]  
- [여기까지 Artifact 저장]  
- [새 Run으로 포크]  

앵커:

- `useResearchPipelineBridge.ts` terminal error 분기  
- `ResearchConversationTurn.tsx` isError 렌더  
- `idea_to_council.py` evidence block  
- `live_mode.py`  

**테스트**

- `test_changes_requested_emits_resume_required_not_hard_fail`  
- `test_hitl_second_approval_continues_pipeline`  
- 기존 comment-required 테스트 유지  

### 5.2 P0-2 세션 제목

- `listResearchConversationSummaries` / rail 라벨에 `createThreadLabel(prompt)` 연결  
- 동일 title 다수 시 `· 2` suffix  
- Session 생성 시 title 확정, 첫 턴 후 한 번 refresh 가능  

파일: `researchConversationStorage.ts`, `ResearchConversationRail.tsx`

### 5.3 P0-3 Artifact 승격 + Library

**승격 규칙**

| 이벤트/상태 | kind | lifecycle |
|---|---|---|
| source accepted | source-card | ephemeral→committed on run end |
| source_audit | source-audit | committed |
| report_chunk | report-draft | ephemeral |
| final_report | report | committed v1 |
| quality summary | quality-summary | committed |
| user export md | export | committed |

**UI**

- Rail “Library”  
- `#/scientific/library` grid/list  
- 클릭 → viewer (markdown/html/json)  
- Output panel Artifacts 탭 = 현재 세션 필터  

**최소 API (로컬)**

```ts
listArtifacts({ sessionId?, runId? })
getArtifact(id)
listVersions(artifactId)
```

P0는 inline content / objectURL로 충분. P1에 파일 경로.

### 5.4 P0-4 단일 셸 + 라우트 정리

- `App.tsx`: settings를 `AiScientistWorkspace` view로 편입  
- Sidebar 레거시 레이아웃 제거 또는 `#/legacy/*`  
- Nav “Live artifacts” → library  
- `/browser`, `/studio` 링크 삭제  

### 5.5 P0-5 Run 타임라인 구조화

지금: progress 문자열 39개를 ol로 나열.  

목표:

```
RunTimeline
  stages: targeting | research | evidence | hitl | council | report | eval
  each: status, summary (1줄), keyEvents[0..5], artifactIds
  disclosure: raw events
```

매핑 힌트: `runProgressStages.ts`, research progress stage 문자열 파서 재사용.

### 5.6 P1 Provenance

Artifact viewer 액션 “계보”:

| 탭 | MUNI 소스 |
|---|---|
| Code | (없으면 “해당 없음” 정직 표시) |
| Execution Log | turn.progress + WS events |
| Messages | session turns slice |
| Environment | backend_mode, depth, source profile, model keys presence(마스킹) |
| Review | VerificationCheck + quality readiness |

### 5.7 P1 Auto Reviewer

- trace-only: final_report + source list + quality gate 결과만  
- claim 단위 pass/warn/fail  
- HumanDecision과 별도 패널  
- 모델 설정은 Session options로  

### 5.8 P2

- Project 다중  
- Split tabs  
- `@artifact` 멘션  
- Skills  
- 서버 durable artifact store와 CycleRepository 정렬  

---

## 6. 컴포넌트 분해 (권장 파일)

```
web/ui/src/
  shell/
    WorkbenchShell.tsx          # 유일 셸
    SessionRail.tsx             # 기존 ResearchConversationRail 개조
    WorkbenchHeader.tsx
  artifacts/
    ArtifactLibraryPage.tsx
    ArtifactViewer.tsx
    ArtifactCard.tsx
    provenance/ProvenancePane.tsx
  run/
    RunTimeline.tsx
    HitlRecoveryCard.tsx
    RunStatusBadge.tsx
  review/
    VerificationCheckCard.tsx
    ValidationWorkspace.tsx     # 기존 개조
  lib/
    models.ts                   # Project/Session/Run/Artifact...
    runStateMachine.ts
    artifactPromotion.ts
    storage/v2.ts
```

기존 `ai-scientist/*`는 점진 이전. 한 방 rewrite 금지.

---

## 7. 백엔드/WS 계약 변경

### 7.1 추가 이벤트 (recommendation)

```json
{"event":"artifact_created","artifact_id":"...","kind":"report","version":1,"uri":"..."}
{"event":"hitl_resume_required","gate":"evidence","resumable":true,"revision_count":1}
{"event":"run_status","status":"awaiting_human","phase":"evidence"}
```

### 7.2 action 유지

```json
{"action":"hitl_decision","gate":"evidence","status":"approved"|"changes_requested","comment":"..."}
{"action":"run_resume","run_id":"..."}        // 신규
{"action":"run_fork","from_run_id":"..."}     // 신규 optional
```

### 7.3 포트

UI WS: `VITE_MUCHA_SCIENCE_WS_URL` 또는 `ws://hostname:8765`  
주의: CS도 8766/8765 혼동 여지 — MUNI web 서버 포트와 문서에 명시.

---

## 8. 구현 로드맵 (MUNI only)

### Sprint A — 신뢰 (P0)

1. HITL soft-fail + recovery card  
2. session title  
3. routes: library stub + settings in-shell  
4. browser/studio nav 제거  

### Sprint B — 산출물 (P0/P1)

1. artifact promotion on final_report/sources  
2. library page + viewer  
3. output panel Artifacts tab  
4. run timeline structured stages  

### Sprint C — 계보/리뷰 (P1)

1. provenance 5탭 (Exec/Messages/Review 우선)  
2. verification checks  
3. version bump on report regenerate  

### Sprint D — 셸 완성 (P2)

1. Project  
2. split tabs  
3. composer mentions  
4. server-backed artifact store  

---

## 9. 테스트 계획 기준

### 자동화

- [ ] changes_requested → resume_required (not hard error without UI)  
- [ ] second approved decision continues  
- [ ] createThreadLabel used in summaries  
- [ ] final_report creates committed artifact ref  
- [ ] library route renders artifact  
- [ ] settings reachable inside scientific shell  
- [ ] no nav to dead /browser artifacts  
- [ ] storage v1→v2 migrate  
- [ ] 기존 HITL comment-required, pipeline bridge tests green  

### 수동 QA (라이브)

- [ ] 동일 프롬프트 2회 → 레일 제목 구분  
- [ ] evidence에서 수정 요청 → 재승인 → 보고서  
- [ ] 완료 턴 Library에서 report 열림  
- [ ] 실행 중단 카드에서 포크 가능  
- [ ] settings 들어가도 셸 유지  

---

## 10. 수락 기준 (DoD)

1. 사용자가 `changes_requested` 이후 **클릭 3번 이내**로 재개 또는 포크 가능  
2. 완료 Run은 Library에 보고서·출처 요약이 **열람 가능** 상태로 존재  
3. 세션 레일에 프롬프트 전문 대신 **압축 제목**  
4. scientific **단일 셸**에서 출처·검증·설정·라이브러리 이동  
5. Verification(quality/auto)와 Human HITL이 UI·타입에서 분리  
6. 회귀: 성공 경로 보고서 렌더·export·source connections 유지  

---

## 11. 명시적 비범위

- 온톨로지랩 코드 변경 (별도 문서)  
- CS 런타임을 MUNI에 임베드  
- 전체 council/persona UI 재설계  
- 상용 배포/멀티테넌트  

---

## 12. 증거 인덱스

| 주장 | 근거 |
|---|---|
| 이중 셸/redirect | `App.tsx` |
| HITL hard-fail | live error string; `live_mode.py`; `idea_to_council.py` |
| resume 계약 미연결 | `plannotator_review_artifact.py` vs chat bridge |
| artifacts 0/2 | localStorage audit 2026-08-04 |
| title helper unused | `createThreadLabel` |
| CS 기준 구조 | 라이브 8766 + operon-cli.db + agents/*.yaml |

---

*MUNI lab 전용. 온톨로지랩은 형제 문서를 본다.*
