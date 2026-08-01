# Mucha Science — 확정 설계 계약 v1 (ultrabrain 자문 확정본, 2026-08-01)

이 파일은 실행 워커의 단일 설계 기준이다. 사용자 승인(start-work bootstrap)으로 확정됐다.
상식과 충돌하면 이 문서가 이긴다. 변경은 새 인터뷰 → 새 Seed 경로로만.

## D1. 목적 함수 조합기 의미론

모든 비어있지 않은 목적 리스트는 하나의 권위 경로를 통과한다:

1. 모든 필수·사용자 하드 제약을 논리 AND로 평가한다.
2. `FAIL`은 후보를 배제(EXCLUDED), `UNKNOWN`은 자격 미해결로 기권(ABSTAINED).
3. 남은 후보에 대해 각 목적을 버전 관리된 유틸리티 `[0, 1_000_000]`(ppm)로 매핑.
4. 정규화 가중 산술평균을 계산한다.
5. 복합 점수로 정렬. Pareto 프런트는 표시·후보 생성용이며 최종 순위를 결정하지 않는다.

N=1은 자연스러운 특수 경우다. 하드 안전·합성 실패는 높은 점수로 상쇄되지 않는다.

```yaml
ApplicationType: [EX_VIVO_DIAGNOSTIC, CONTAINED_LAB, ENVIRONMENTAL_SPRAY, ENVIRONMENTAL_COATING, OTHER_ENVIRONMENTAL]
ConstraintOwner: [USER, PLATFORM_POLICY]
ConstraintOutcome: [PASS, FAIL, UNKNOWN]

ObjectiveTerm:
  term_id: string
  objective_ref: {id: string, version: string, sha256: string}
  weight_units: uint32        # 1..1_000_000, 상대 가중치. 0 금지
  parameters: canonical_json

Constraint:
  constraint_id: string
  owner: ConstraintOwner
  metric_ref: string
  operator: GTE | LTE | BETWEEN | EQ | IN
  threshold: {value: decimal_string, unit: string}
  policy_ref: string | null

UserQueryRevision:
  query_id: string
  revision_id: content_hash
  parent_revision_id: string | null
  application_type: ApplicationType
  objectives: ObjectiveTerm[]       # minItems: 1
  user_constraints: Constraint[]
  change_set: [ADD_OBJECTIVE | REMOVE_OBJECTIVE | SET_WEIGHT | ADD_CONSTRAINT | REMOVE_CONSTRAINT | SET_APPLICATION_TYPE]
  actor: string
  created_at: timestamp

RankingRun:
  query_revision_id: string
  policy_bundle_ref: {version: string, sha256: string}
  resolved_constraints: Constraint[]   # user + 주입된 platform 제약
  per_candidate_constraint_results: object[]
  per_objective_utility_ppm: object[]
  composite_score_ppm: integer | null
```

점수: `score_ppm(c) = round_half_even( sum(weight_units[i] * utility_ppm[i](c)) / sum(weight_units[i]) )`

규칙:
- 정규화기·방향성은 objective_ref의 일부. 모든 유틸리티는 "높을수록 좋음".
- 가중 0 금지. 목적 제거는 새 query revision에서 생략으로 표현.
- 활성 목적의 값이 없으면 ABSTAINED. 0 대입·후볳별 가중 재정규화 금지.
- 완전 중복 목적 term은 거부. 별도 스코프 인스턴스는 허용.
- 동점은 과학적 동률 유지, 직렬화/top-N 타이브레이크는 후보 content hash.
- 가중 스케일 불변: 3:1 == 6:2.
- 제약 평가는 계산상 short-circuit 가능하나 의미론은 스칼라화 전 AND.

안전·합성 정책:
- 합성가능성은 항상 플랫폼 제약으로 주입.
- ENVIRONMENTAL_SPRAY/COATING/OTHER_ENVIRONMENTAL은 작물 약해·토양/유익 미생물·취급자 노출 스크린을 자동 주입.
- 플랫폼 제약은 사용자가 제거·비활성·가중 축소·UNKNOWN→PASS 처리 불가. 더 엄격한 제약 추가만 가능.
- application_type 변경은 감사되는 새 query revision.
- 디버그 뷰가 차단 후보를 보여줄 수는 있으나 순위 실험 우선순위로 표시·남낼 수 없음.
- 스크린 통과는 "선언된 스크리닝 정책 하 배제 신호 없음"일 뿐 "안전"이 아님.

결정론 픽스처(AC-01/06/07):
- 유틸리티 [800000, 200000], 가중 [3,1] → 650000.
- N=1, 유틸리티 800000 → 같은 함수로 800000.
- 두 번째 유틸리티 결측 → 복합 점수 없음, ABSTAINED.
- 하드 제약 FAIL → EXCLUDED. UNKNOWN → ABSTAINED.
- spray 질의는 3개 안전 제약 자동 포함, 삭제 시도는 validation error.
- 목적 제거는 새 revision + 나머지 상대 가중 자동 재정규화.

## D2. 증거 사다리와 예측-실측 짝

원칙: 경험적 `AssayObservation`과 예측-검증 짝 `Measurement`를 분리한다. 소급 예측을 날조하지 않는 유일한 정직한 방법이다.

```yaml
EvidenceTier: [PURIFIED_ENZYME, LYSATE, WHOLE_ISOLATE, SPIKED_MATRIX, RETROSPECTIVE_FIELD, PROSPECTIVE_FIELD]
ObservationOrigin: [PLATFORM_ASSAY, EXPLORATORY_ASSAY, IMPORTED_EXTERNAL]
PredictionOrigin: [PLATFORM_COMPUTATION, EXTERNAL_COMPUTATION]
PairingDesign: [PROSPECTIVE_LOCKED, RETROSPECTIVE_BLINDED, EXTERNAL_PREEXISTING]
PairRelation: [DIRECT_ESTIMAND, DOWNSTREAM_CONTEXT]
ResultKind: [POINT, INTERVAL, LEFT_CENSORED, RIGHT_CENSORED, CATEGORICAL, FAILED]

AssayObservation:
  observation_id: content_hash
  evidence_tier: EvidenceTier
  origin: ObservationOrigin
  candidate_id: string | null
  target_id: string | null
  endpoint_ref: string
  assay_condition_id: string
  result: {kind: ResultKind, value: any, unit: string | null}
  raw_artifact_refs: string[]
  replicate_group_ref: string | null
  source_record_id: string | null
  assay_started_at: timestamp | null
  observed_at: timestamp
  qc_status: PASS | FAIL | PENDING

Prediction:
  prediction_id: content_hash
  prediction_series_id: string
  origin: PredictionOrigin
  estimand: {candidate_id, target_id|null, endpoint_ref, unit, condition_scope_hash}
  result: object
  issued_at: timestamp
  locked_at: timestamp
  invocation_lineage_hash: string
  # evidence_tier 필드는 금지 — 예측은 사다리 등급이 아니다

Measurement:
  measurement_id: content_hash
  observation_id: string
  originating_prediction_id: string   # 정확히 1개, 불변
  pairing_design: PairingDesign
  pair_relation: PairRelation
  benchmark_split_role: NONE | TRAIN | VALIDATION | TEST
  pair_created_at: timestamp
  compatibility_check_ref: string
```

짝 불변식:
1. Measurement는 정확히 하나의 불변 예측과 하나의 경험 관측을 참조.
2. 예측과 관측은 candidate·endpoint 일치, 단위 변환 가능.
3. PROSPECTIVE_LOCKED는 prediction.locked_at <= assay_started_at 요구.
4. RETROSPECTIVE_BLINDED는 결과 은닉을 증명하는 사전 커밋 분할/접근 manifest 요구.
5. EXTERNAL_PREEXISTING은 외부 예측이 어세이보다 선행함을 보이는 SourceRecord+스팬 요구.
6. 정정은 supersede로, 예측·관측·짝을 재작성하지 않음.
7. 하나의 최종 endpoint 예측은 반복·등급을 가로질러 다수 Measurement를 가질 수 있음. 도킹 등 구성 출력은 lineage이지 복수의 "originating" 예측이 아님.

자동 보정 자격(파생, 사용자 설정 불가):
```
eligible = tier in {PURIFIED_ENZYME, LYSATE}
  AND observation.qc_status == PASS
  AND pair_relation == DIRECT_ESTIMAND
  AND prediction.origin == PLATFORM_COMPUTATION
  AND pairing_design in {PROSPECTIVE_LOCKED, RETROSPECTIVE_BLINDED}
  AND benchmark_split_role not in {VALIDATION, TEST}
```
그 외 짝도 전부 기록 가능. 상위 등급 불일치는 HumanInterpretationSignal을 만들고 모델 파라미터를 갱신하지 않는다.

비짝 습식 결과:
- 탐색 어세이·대조군·외부 인제스트는 원래 등급의 1급 AssayObservation.
- Claim·어세이 설계·회고 데이터셋을 지지할 수 있음.
- 적중률·보정·"예측 검증됨" 통계에는 들어가지 않음.
- null/합성/사후 예측을 외래키 충족용으로 만들지 않음.
- 기존 관측은 결과 은닉이 입증될 때만 회고 블라인드 평가가 될 수 있음. 아니면 사전등록 예측+새 어세이 필요.
- 한 어세이가 여러 endpoint를 낳으면 각각 별개 관측, 독립 짝 가능.
- 기술 반복은 하나의 measurement로 묶고 독립 성공으로 세지 않음.

P3 개정 문구(명세서 반영): "모든 습식 데이터는 6개 증거 등급 중 하나의 경험적 AssayObservation으로 저장된다. Measurement는 예측-검증 서브타입으로 정확히 하나의 불변·endpoint 호환 예측을 참조해야 한다. 진정한 선행 예측이 없는 탐색·인제스트 관측은 명시적으로 비짝으로 남고 예측 적중률·보정 통계에서 제외된다. 플랫폼은 소급 예측을 날조하지 않는다."

## D3. 어댑터 재현성과 예측 버전 모델

소프트웨어 라벨은 기술용, content hash가 권위.

```yaml
ReproducibilityMode: [CANONICAL_EXACT, TOLERANCE]
SeedHandling: [HONORED, NOT_SUPPORTED, IGNORED, UNKNOWN]

AdapterInvocation:
  invocation_id: string
  adapter: {id, contract_version, build_sha256}
  tool: {name, reported_version, executable_sha256|null, container_digest|null, dependency_lock_sha256}
  environment: {os_arch, cpu, gpu|null, driver_runtime_versions, environment_manifest_sha256}
  full_parameters: canonical_json
  parameter_sha256: string
  requested_seed: uint64
  seed_handling: SeedHandling
  input_manifest_sha256: string
  source_snapshot_ids: string[]
  raw_output_sha256: string
  canonical_output_sha256: string
  limitation_profile_sha256: string
  reproducibility_mode: ReproducibilityMode
  tolerance_profile_sha256: string | null
  status: SUCCEEDED | FAILED | CANCELLED

Prediction(+D2 필드에 추가):
  prediction_id: "pred_<sha256(canonical_payload)>"
  revision: uint32
  recomputes_prediction_id: string | null
  predictor_signature: string   # 전처리·도구빌드·파라미터 프로파일·구조/모델 버전·후처리·점수 변환의 해시. 후보 입력·출력·시드·시각 제외
  input_hashes: string[]
  uncertainty: object
  objective_normalizer_hash: string
  calibration_model_hash: string | null
  epistemic_status: RANKABLE_PREDICTION | HYPOTHESIS_ONLY

ToleranceProfile:
  profile_id: string
  version: string
  comparators: [{field_or_artifact, metric: ABS_ERROR|REL_ERROR|RMSD|RANK_CORRELATION|TOP_K_OVERLAP, threshold: decimal}]
  decision_invariants: [same_constraint_disposition, same_abstention_disposition]
```

도구 업그레이드는: tool build hash와 predictor signature 변경 / 새 불변 Prediction revision / `recomputes_prediction_id` 링크 / 구 예측·짝 재작성 금지 / 구 예측 무효를 뜻하지 않음. 결함 발견 시 별도 retraction 주석 이벤트(원본 짝은 감사 가능하게 유지).

보정 계약 — 층(stratum) = (predictor_signature, endpoint_definition_hash, evidence_tier, assay_condition_family_hash, pairing_design):
- 층별로 보정 피팅·보고. 보정 모델은 학습 짝 해시 전부·시간 컷오프·분할 manifest·방법 버전·적용 도메인을 기록.
- 새 predictor signature는 미보정 상태로 시작, 최소 지지 수량까지 abstention 유발.
- 버전 풀링은 동일 고정 입력으로 구·신 버전을 돌리는 사전등록 bridge 연구 + 명시적 VersionEquivalenceGroup 이후만.
- 9장 전체 지표는 층 보고의 고정 가중 매크로 집계. 무단 마이크로 풀링 금지.
- 신뢰도 곡선·Brier/ECE는 항상 n과 predictor signature 표기.
- 여러 도구 버전이 하나의 관측과 비교되면 관측/후보로 클러스터링 — 독립 습식 결과로 세지 않음.
- 보정기 학습에 쓰인 짝은 그 보정기 평가에 사용 불가.
- 상위 등급은 기술적으로 평가 가능하나 자동 보정기 학습은 하위 2등급만.

R1/R2:
- R1 Replayable: 동일 코드/컨테이너·환경 manifest·입력·파라미터·시드로 재호출 가능(레시피).
- R2 Computationally reproducible: 사전 선언 비교기 하에서 의미 있는 출력과 하류 결정이 일치.
- 계약: 순위 생산 어댑터는 R1 replay 캡슐 제공 + R2 적합성 프로파일 통과.
- 결정론적 도구: CANONICAL_EXACT(정준 출력 해시 일치; 원시 로그의 시각·순서 차이는 허용).
- GPU/비결정 도구: TOLERANCE(원시 해시는 기록하되 판정은 핀된 tolerance profile + 결정 불변).
- 하드 필터·기권 경계를 넘는 replay는 수치가 허용 오차 내여도 R2 실패.
- 모델/빌드·환경을 핀할 수 없는 원격 서비스는 R0이며 R1/R2를 주장하거나 정상 rankable 예측을 생산할 수 없음.

## D4. Abstention과 hypothesis_only

예측의 인식론 상태와 순위 결정을 분리한다(하나의 boolean으로 합치지 않음).

```yaml
PredictionEpistemicStatus: [RANKABLE_PREDICTION, HYPOTHESIS_ONLY]
GateOutcome: [PASS, FAIL, UNKNOWN]
CandidateDisposition: [RANKED, EXCLUDED, ABSTAINED]
AbstentionReason: [MISSING_REQUIRED_PREDICTION, LOW_STRUCTURE_CONFIDENCE, STRUCTURE_ENSEMBLE_DISAGREEMENT, OLIGOMER_STATE_AMBIGUOUS, COFACTOR_STATE_AMBIGUOUS, OUT_OF_DISTRIBUTION, UNCERTAINTY_TOO_HIGH, UNCALIBRATED_PREDICTOR_VERSION, REQUIRED_PROVENANCE_MISSING, ADAPTER_LIMITATION_TRIGGERED, CONFLICTING_SUPPORT, MANDATORY_CONSTRAINT_UNRESOLVED]

QualityGateResult:
  gate_id: string
  policy_ref: {version, sha256}
  subject_prediction_id: string
  metric: string
  observed_value: any
  threshold_or_predicate: object
  outcome: GateOutcome
  reason: string

CandidateRankingDecision:
  candidate_id: string
  query_revision_id: string
  disposition: CandidateDisposition
  objective_evaluations: [{objective_term_id, status: SCORED|HYPOTHESIS_ONLY|ABSTAINED, utility_ppm: int|null}]
  abstention_reasons: AbstentionReason[]
  gate_result_ids: string[]
  required_next_evidence: string[]
  composite_score_ppm: int | null
```

파이프라인:
1. 구조/도구 출력은 품질 무관 기록. 2. 핀된 policy bundle이 품질 게이트 평가.
3. 필수 구조 게이트 FAIL/UNKNOWN → 그 구조 예측은 HYPOTHESIS_ONLY.
4. 상태는 명시적 dependency lineage로만 도킹/친화도 예측에 전파.
5. 양의 가중 목적이 HYPOTHESIS_ONLY 결과에 의존하면 그 후보는 ABSTAINED, 복합 점수 없음.
6. 그 구조와 무관한 목적은 사용 가능. 7. 하드 과학 실패=EXCLUDED, 지식 부족=ABSTAINED.
8. 출력은 세 리스트: ranked / excluded(사유) / abstained(필요 증거).

구조 신뢰 정책: 보편 pLDDT 임계값을 명세에 박지 않는다. 승인·버전 관리된 StructureConfidencePolicy(local/pocket confidence, PAE, ensemble disagreement, oligomer, cofactor/metal, 구조 출처 유형 술어 포함)를 요구. 프로파일 없으면 HYPOTHESIS_ONLY. 실험 구조는 출처별 품질 프로파일 사용. 사용자는 게이트를 강화할 수만 있음. 사람이 기권 가설을 시험할 수는 있으나 rankable/증거로 재라벨하지 않음.

## D5. 신규 레코드 3종

### SourceRecord
```yaml
SourceKind: [PUBLICATION, DATABASE_RECORD, DATASET_RELEASE, WEB_RESOURCE, USER_FILE, EXPERIMENTAL_IMPORT]
LicenseDecision: [ALLOWED, RESTRICTED, UNKNOWN, DENIED]
SourceRecord:
  source_id: content_hash
  source_kind: SourceKind
  namespace: string
  accession: string
  source_release: string
  version_status: PINNED | UNVERSIONED | UNKNOWN | NOT_APPLICABLE
  schema_version: string
  api_version: string
  canonical_uri: string
  retrieved_at: timestamp
  artifact: {sha256, media_type, byte_size}
  license: {expression(SPDX|LicenseRef), terms_uri|null, terms_snapshot_sha256|null, decision: LicenseDecision, restrictions: string[], decided_by|null, decided_at|null}
  citation: canonical_csl_json
  provenance: {parent_source_ids: string[], adapter_invocation_id: string|null}
```
규칙: 가변 "latest" API는 스냅샷 필수(retrieval+content hash가 실질 버전). UNKNOWN/DENIED 라이선스는 재배포·팩 활성화 차단. 갱신은 새 레코드, 기존 스팬은 구 해시에 묶임. URL이 아니라 artifact hash가 provenance 앵커.

### AssayCondition
```yaml
ControlType: [POSITIVE, NEGATIVE, BLANK, VEHICLE, MATRIX, PROCESS]
ReportingStatus: [REPORTED, NOT_REPORTED, NOT_APPLICABLE]
AssayCondition:
  condition_id: content_hash
  protocol_source_id: string | null
  assay_type_ref: string
  matrix: {vocabulary_term, source_or_species|null, lot_or_batch|null, preparation}
  test_system: {organism_or_isolate_refs: string[], inoculum|null, candidate_concentration|null}
  environment: {temperature|null, duration, pH|null, sampling_schedule|null}
  modifiers: [{role: PERMEABILIZER|INHIBITOR|COFACTOR|BUFFER|OTHER, substance_ref_or_name, concentration|null}]
  controls: {reporting_status, definitions: [{type: ControlType, material_ref_or_description, expected_outcome}]}
  replication: {reporting_status, biological_n|null, technical_n|null, unit_of_replication|null, randomization|null, blinding|null}
  instrument_or_method_ref: string | null
```
규칙: 등급은 Observation/Measurement에, matrix로 추론하지 않음. NOT_REPORTED는 0개와 다름. 조건은 의도된 셋업, 편차는 관측에. 기술 반복 ≠ 독립 생물학 결과. 불완전 인제스트 어세이는 기록 가능하나 필수 대조군·반복 정보 없으면 보정 자격 실패.

### Claim
```yaml
ClaimOrigin: [LITERATURE_EXTRACTION, MEASUREMENT_ANALYSIS, COUNCIL, COMPUTATION, HUMAN]
EntailmentDecision: [ENTAILED, CONTRADICTED, NOT_ENOUGH_INFORMATION]
Applicability: [DIRECT, PARTIAL, OUT_OF_SCOPE, UNKNOWN]
ClaimStatus: [SUPPORTED, CONTRADICTED, MIXED, UNKNOWN]
ApprovalStatus: [PENDING, APPROVED, REJECTED]
SourceSpan: {source_id, artifact_sha256, selector: {type: UTF8_BYTE_RANGE|PDF_PAGE_BOX|JSON_POINTER|TABLE_CELL, value}, quoted_text_sha256, quoted_text|null}
ClaimEvidenceLink: {source_span: SourceSpan, entailment, applicability, verifier: {method: HUMAN|MODEL|RULE, version, verified_by, verified_at}}
Claim:
  claim_id: content_hash
  proposition: {display_text, subject_refs: string[], predicate_ref, object, qualifiers}
  origin: ClaimOrigin
  source_links: ClaimEvidenceLink[]
  supporting_record_refs: string[]
  status: ClaimStatus
  approval: {status: ApprovalStatus, actor|null, decided_at|null}
  supersedes_claim_id: string | null
```
규칙: 문헌 SUPPORTED는 ENTAILED+적용 가능 스팬 1개 이상. 상충 스팬은 MIXED(다수결로 지우지 않음). NOT_ENOUGH_INFORMATION → UNKNOWN + 주장 수준 기권. 표/그림은 TABLE_CELL/PAGE_BOX 셀렉터. 제한 라이선스는 인용 남출 억제 가능(좌표·해시는 유지). Council/계산 주장은 사람 승인 후에도 비증거 — 승인은 지식/워크플로 사용 허가일 뿐 EvidenceTier를 만들지 않음. 정정은 superseding claim 추가.

연결: 외부 ProteinRecord·SubstanceCandidate·인제스트 관측 → SourceRecord / 모든 짝 Measurement → AssayCondition / Council 출력 → Claim[](origin=COUNCIL) / ClaimEvidenceLink.source_span → 불변 SourceRecord.artifact.

## 위험과 완화
| 위험 | 완화 |
|---|---|
| 가중 평균이 트레이드오프를 가림 | 구성 유틸리티·Pareto 진단 항상 노출, 권위 규칙은 단일 |
| fail-closed로 순위 후보가 적어짐 | 게이트 완화 대신 기권 사유·필요 증거 반환 |
| 새 도구 버전의 희소 보정 층 | 고정 입력 bridge 연구·섀도 평가, 기본 풀링 금지 |
| Observation/Measurement 명명 혼동 | 스키마·UI에서 "unpaired empirical observation"/"paired validation measurement"로 일관 표기 |
| 신뢰 임계값이 보편 상수처럼 보임 | 승인·버전 관리 policy profile + 파일럿 보정 |
| 소스 라이선스·스팬 변경 | 스팬은 불변 artifact hash에 묶고 새 revision 추가 |
