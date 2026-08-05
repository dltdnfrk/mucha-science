# MUNI lab — Claude Science 구조 이식 참조 (docs/claude-science-reference)

> 2026-08-05 정리. 이 폴더는 MUNI lab 전용 문서·사진만 담는다.
> 공통 역설계/클론은 `~/Documents/MUNI/artifacts/claude-science-clone-reference-2026-08-04/` (1차: `nipo-science/apps/web/claude-shell`) 참조.

## 문서 (읽는 순서)

| 순서 | 파일 | 내용 |
|---|---|---|
| 1 | `Claude_Science_0.1.25_UI_UX_기능_역설계_및_온톨로지랩_MUNI_lab_이식_구현_명세_2026-08-04.md` | **공통 역설계** — Project→Session→Run→ArtifactVersion→Provenance→Reviewer 하니스 구조 (저장소 내 버전 관리) |
| 2 | `온톨로지랩_MUNI_lab_UI_UX_분석과_Claude_Science_구조_이식_방안_2026-08-04.md` | **실측 분석** — 근접도 65%, 이중 셸·산출물 0 등 결함 (저장소 내 버전 관리) |
| 3 | `MUNI_lab_Claude_Science_구조_이식_구현_명세_2026-08-04.md` | **앱 전용 구현 명세** — 목표 IA(단일 셸), Run 상태기계, Artifact 승격, HITL 회복, 라우트 계약, P0–P2 로드맵 |
| 4 | `MUNI_lab_시운전_버그리포트_재검수_2026-08-05.md` | **버그리포트 재검수** — QA-001~008 재검증 + 빠진 결함 4건(GAP-M1~M4) |
| 5 | (외부) `docs/qa/muni-lab-trial-scenarios.md` | 시운전 시나리오 11개 원본 |
| 6 | (외부) `~/Documents/MUNI/artifacts/muni-lab-trial-run-2026-08-04.md` | 시운전 결과 원본 |

> **버전 관리**: 1~4번 문서는 2026-08-05부터 저장소 안(`docs/claude-science-reference/`)에 있어 git 추적 대상이다. artifacts의 사본은 배포용이며, 수정 시 저장소 문서를 정본으로 한다.

## 이미지 (images/)

| 파일 | 내용 | 시점 |
|---|---|---|
| `muni-01-scientific-workspace.png` | 과학 워크스페이스 (레일+스레드+보고서) | 2026-08-05 신규 |
| `muni-02-sources.png` | 출처 설정 패널 | 2026-08-05 신규 |
| `muni-03-dual-shell-settings.png` | **이중 셸** — 레거시 Sidebar 설정 화면 (GAP-M3) | 2026-08-05 신규 |
| `muni-scientific-workspace.png` | 비교용 (클론 패키지) | 2026-08-04 |
| `muni-settings-dual-shell.png` | 비교용 (클론 패키지) | 2026-08-04 |
| `muni-sources.png` | 비교용 (클론 패키지) | 2026-08-04 |

## 핵심 이슈 요약 (2026-08-05 재검수 기준)

1. **QA-001 (Blocker)**: 설치 앱에 연구 백엔드 없음 — `ALLOWED_ORIGINS` 4173/5173만 허용, 여전히 오픈
2. **GAP-M4 (High)**: HITL changes_requested → 하드페일, 회복 UI 없음 (8/9 세션 error)
3. **GAP-M1 (High)**: 세션 제목 = 프롬프트 전문, 레일 9개 중복 (`createThreadLabel` 미사용)
4. **GAP-M2 (High)**: 성공 실행 산출물 2개 있으나 Library/뷰어 없음, "Live artifacts" 허상
5. **GAP-M3 (Medium)**: scientific ↔ 레거시 Sidebar 이중 셸

## 관련 자료

- 공통 클론 패키지: `~/Documents/MUNI/artifacts/claude-science-clone-reference-2026-08-04/`
- 통합 역설계: `~/Documents/MUNI/artifacts/Claude_Science_0.1.25_UI_UX_기능_역설계_및_온톨로지랩_MUNI_lab_이식_구현_명세_2026-08-04.md`
