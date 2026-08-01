# Mucha Science 거버넌스 개정 payload (2026-08-01)

이 문서는 Ouroboros 인터뷰 이어서로 기록할 개정 질문/답변 세트다.
아래 답변은 모두 이미 승인된 결정만 요약하며, 새 요구사항을 만들지 않는다.

## Q&A 1 — D1 목적 함수 조합기

**Q.** 조합기 의미론은 어떻게 개정하는가?

**A.** 하드 제약을 먼저 평가한다. `FAIL`은 후보를 제외(EXCLUDED)하고 `UNKNOWN`은 자격 미해결로 기권(ABSTAINED)시킨다. 남은 후보에 대해 목적별 유틸리티를 `[0, 1_000_000]` ppm으로 정규화하고, 정규화 가중 산술평균으로 복합 점수를 계산한다. Pareto 전선은 정보 표시용이며 최종 순위를 결정하지 않는다. 질의 편집은 불변 `UserQueryRevision`을 생성하며 기존 revision은 덮어쓰지 않는다. 플랫폼은 합성가능성 제약을 항상 주입하고, 환경 노출형 application type에는 3개 안전 스크린을 항상 주입하며, 이 플랫폼 제약은 제거·비활성화·가중 축소가 불가하다.

## Q&A 2 — D2 증거 모델

**Q.** P3와 예측-실측 짝 규칙은 어떻게 바꾸는가?

**A.** P3를 “모든 측정이 예측과 짝”에서 “모든 예측-검증 측정은 정확히 하나의 불변 예측과 짝”으로 바꾼다. 비짝 관측은 1급 `AssayObservation` 레코드로 저장하되 hit-rate·calibration 통계에서는 제외한다. 플랫폼은 소급 예측을 날조하지 않는다. 자동 보정 자격은 파생 규칙으로만 계산한다.

## Q&A 3 — D3 재현성

**Q.** R1/R2와 예측 버전 모델은 어떻게 정의하는가?

**A.** R1은 replay capsule(레시피), R2는 conformance profile이다. 결정론적 도구는 byte-exact 일치만 요구하고, 원격 서비스는 R0로 capped 한다. 예측은 content-addressed immutable version으로 저장하며, 업그레이드는 항상 새 `predictor_signature` + 새 `revision`을 만든다. 기존 이력은 절대 다시 쓰지 않는다.

## Q&A 4 — D4 보정 층화

**Q.** 보정 층(stratum)은 무엇으로 나누는가?

**A.** `(predictor_signature, endpoint, tier, condition family, pairing design)`으로 층화한다. 서로 다른 버전의 pooling은 사전등록 bridge study를 거친 경우에만 허용한다.

## Q&A 5 — D5 기권(abstention)

**Q.** 인식론 상태와 후보 처분은 어떻게 분리하는가?

**A.** `PredictionEpistemicStatus`와 `CandidateDisposition`을 분리한다. 기권 사유는 버전 관리된 enum으로 기록한다. 보편 pLDDT 임계값은 쓰지 않고, 대신 버전 관리된 `StructureConfidencePolicy`를 사용한다.

## Q&A 6 — D6 신규 레코드 타입

**Q.** 어떤 새 레코드를 추가하는가?

**A.** `SourceRecord`, `AssayCondition`, `Claim`을 추가한다. `SourceRecord`의 라이선스 결정은 `ALLOWED/RESTRICTED/UNKNOWN/DENIED`로 기록한다. `AssayCondition`은 controls/replication을 명시하고 `NOT_REPORTED`를 0과 구분한다. `Claim`은 source span과 entailment를 가진다. Council 기원 주장은 승인 후에도 비증거이며 evidence tier가 되지 않는다.

## Q&A 7 — 배포 형태

**Q.** 제품 배포 형태는 어떻게 바뀌는가?

**A.** Tauri desktop app은 spec에서 제거한다. 제품은 로컬 서버 웹앱으로 제공하며, 단일 Docker image와 docker-compose로 패키징한다. 프런트엔드는 기존 React UI를 재사용한다. Supabase와 AWS는 기각하며, 단일 사용자 로컬 환경에서 file ledger가 authority이고 cloud는 명시적 비목표다.

## Q&A 8 — 명세 bookkeeping

**Q.** 상태 안내와 seed 텍스트는 어떻게 정리하는가?

**A.** 상태 노트의 untracked count를 2에서 4로 갱신한다. Appendix A의 seed는 기존 `Measurement` 축약 설명을 새 seed로 교체할 예정임을 명시하고, 이 개정 문서는 그 치환을 위한 payload만 제공한다.

## Q&A 9 — 추적성 확인

**Q.** 위 결정들은 어떤 설계 계약에 근거하는가?

**A.** D1~D6는 각각 design-contracts-v1.md의 동일 항목에 대응한다. 본 문서는 그 계약을 spec revision 인터뷰 continuation으로 옮겨 적는 것뿐이며, 새 요구를 추가하지 않는다.

## 스펙 섹션/AC 변경 매핑

| spec section / AC | amendment item | 변경 요약 |
|---|---|---|
| section 2 | Q&A 7 | Tauri desktop 제거, local-server web app + Docker + React 재사용, cloud 비목표 |
| section 3 | Q&A 2 | 3-list output 관점에서 ranked / excluded / abstained 정렬 규칙 정리 |
| section 4 | Q&A 1 | combiner semantics: hard constraints, ppm weighted mean, Pareto informational only, immutable revision |
| section 5 P3 | Q&A 2 | every measurement → every prediction-validation measurement, unpaired observations first-class |
| section 6 | Q&A 2 | auto-calibration eligibility derivation rule 명시 |
| section 8 | Q&A 3 | adapter contract: R1 replay capsule, R2 conformance profile, byte-exact only deterministic tools |
| section 9 | Q&A 4 | stratified calibration strata 정의 및 bridge study 조건 |
| section 11 | Q&A 1,2,3,4,5,6,7 | AC updates and new AC-10 for web delivery 반영 |
| section 12 | Q&A 7 | cloud non-goal 및 local-only authority ledger 명문화 |
| appendix A | Q&A 8 | seed replacement notice 반영 |

## Traceability note

이 payload의 모든 개념은 다음 계약에서만 가져왔다.
- D1 combiner semantics
- D2 AssayObservation / Measurement split + auto-calibration eligibility
- D3 reproducibility + immutable prediction versions
- D4 calibration stratification
- D5 abstention separation + structure confidence policy
- D6 SourceRecord / AssayCondition / Claim schemas

## 보완 기록 (2026-08-01, 감사 후속)

세 출처 감사 후 `docs/PRODUCT_SPEC.md`에 플랫폼 수준의 명명된 데이터 소스 정책과 전체
R0-R5 재현성 사다리를 보완했다. 이로써 승인된 리서치 반영 중 누락됐던 데이터 소스 명명과
R3-R5 정의를 완료했으며, 첫 도메인 팩의 구체적 대상은 미결정 상태로 유지한다.

