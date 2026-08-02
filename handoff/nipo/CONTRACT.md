# MUNI → nipo WetLabHandoff 계약

이 문서는 MUNI simulator의 건식 계산 결과를 nipo의 습식 검증 계획으로 넘길 때 지켜야 할 로컬 전달 계약이다. 두 저장소를 합치거나 상대 프로젝트를 이 저장소에서 수정하지 않는다. 전달물은 nipo-rooted 세션이 읽고, 검증하고, 사람의 판단으로 권위 사슬에 결속하기 위한 입력일 뿐이다.

## 1. 권위 사슬의 결속점

nipo의 권위 사슬은 다음과 같다.

`Project → Session → ActionPlan → approval → Run → Execution → ArtifactVersion → Review → Export`

WetLabHandoff가 결속되는 정확한 지점은 **Session 안에서 사람이 ActionPlan을 생성하는 시점**이다. MUNI의 handoff와 후보 내용 해시는 ActionPlan의 외부 건식 산출물 참조로 고정된다. 이 참조 고정은 approval보다 먼저 일어나야 한다. handoff 자체는 nipo의 ActionPlan, approval, Run 또는 Evidence가 아니며, 이를 자동 생성하거나 승인하지 않는다.

## 2. JSON 스키마

모든 `필수` 필드는 반드시 존재해야 한다. 별도 표기가 없는 문자열은 비어 있지 않아야 한다. `sha256`은 `sha256:` 뒤에 소문자 16진수 64자가 오는 내용 해시다. 현재 스키마의 선택 필드는 후보 워크플로가 보존하는 추가 속성뿐이며, 수신자는 알지 못하는 추가 후보 속성을 삭제하거나 권위 의미로 해석하지 않는다.

이 계약이 필드 집합을 정의하는 블록은 닫힌 스키마다. `handoff`, `persisted`, `boundary`, `study`, `review`, `candidate_set`, `provenance`와 그 `collected_data` 항목, `lineage`와 그 `collection_adapters` 항목·`workflow`·`workflow.run`, 후보의 `rationale`·`uncertainty`에 선언되지 않은 필드가 있으면 validator는 필드 위치와 이름을 들어 거부한다. 선언되지 않은 필드가 허용되는 자리는 명시된 자리뿐이다: 최상위 object(3절에서 보듯 어떤 digest에도 들어가지 않는다), `candidate_set.items[]`의 보존 워크플로 속성(2.8의 투영 규칙을 따라야 한다), `candidate_content` 안의 호출자 제공 속성, 그리고 `workflow.parameters`. 전방 호환은 조용한 관용이 아니라 `schema_version` 갱신으로만 이루어진다.

### 2.1 최상위

| 이름 | 타입 | 필수/선택 | 의미 |
|---|---|---:|---|
| `schema_version` | string | 필수 | 정확히 `muni-research-handoff.v4`. v4는 재계산 가능한 경계 digest와 저장소에서 조회 가능한 persisted 참조를 분리하고 provenance/lineage를 evidence digest로 결속한다. |
| `handoff` | object | 필수 | WetLabHandoff 식별자, persisted 레코드 참조와 산출물 위치. |
| `persisted` | object | 필수 | MUNI 저장소의 승인 ReviewRecord와 CandidateSet을 조회하기 위한 opaque 참조 묶음. |
| `boundary` | object | 필수 | exported projection에서 독립 재계산하는 CandidateSet/Review 경계 ID와 evidence digest. |
| `disclaimer` | string | 필수 | 정본 dry-lab 면책문. 변경·삭제 금지. |
| `study` | object | 필수 | 합성 연구 대상과 목적의 식별 문맥. |
| `review` | object | 필수 | 후보 집합에 결속된 MUNI 연구자 검토. |
| `candidate_set` | object | 필수 | 순위·처분·불확실성을 보존한 후보 집합. |
| `provenance` | object | 필수 | 수집 입력의 출처와 내용 해시. 비어 있을 수 없다. |
| `lineage` | object | 필수 | 수집 어댑터와 계산 워크플로 실행 계보. 비어 있을 수 없다. |

### 2.2 `handoff`

| 이름 | 타입 | 필수/선택 | 의미 |
|---|---|---:|---|
| `handoff_id` | string | 필수 | `muni_wet_lab_handoff_<32 hex>` 형식의 내용 결정 식별자. |
| `review_ref` | string | 필수 | MUNI review store에 실제 존재하는 persisted ReviewRecord 참조. `persisted.review_ref`와 같다. |
| `candidate_set_ref` | string | 필수 | MUNI candidate-set store에 실제 존재하는 persisted CandidateSet 참조. `persisted.candidate_set_ref`와 같다. |
| `artifact_paths` | string[] | 필수 | 생성된 JSON과 Markdown 산출물 경로. 최소 1개이며 각 값은 비어 있지 않다. JSON/Markdown 파일명은 persisted `review_ref`에서 파생한다. 경로 자체는 전송 식별자가 아니므로 nipo는 `handoff_id`와 내용 해시를 권위 참조로 쓴다. |
| `disclaimer` | string | 필수 | 최상위 `disclaimer`와 바이트 단위로 같은 면책문. |
| `evidence_digest` | sha256 string | 필수 | `boundary.evidence_digest`와 같은 값이며 `handoff_id` preimage에 직접 포함된다. |

### 2.3 `persisted`

| 이름 | 타입 | 필수/선택 | 의미 |
|---|---|---:|---|
| `review_ref` | string | 필수 | producer가 승인 여부를 확인한 persisted ReviewRecord ID. 경계 내용으로 재계산하지 않는 opaque linkage이며 `handoff.review_ref`와 같아야 한다. |
| `candidate_set_ref` | string | 필수 | 해당 persisted ReviewRecord가 가리키는 persisted CandidateSet ID. 경계 내용으로 재계산하지 않는 opaque linkage이며 `handoff.candidate_set_ref`와 같아야 한다. |

### 2.4 `boundary`

| 이름 | 타입 | 필수/선택 | 의미 |
|---|---|---:|---|
| `review_id` | string | 필수 | exported review 내용과 `boundary.candidate_set_id`로 재계산하는 경계 Review digest. persisted 조회 참조가 아니다. |
| `candidate_set_id` | string | 필수 | exported candidate items 전체로 재계산하는 경계 CandidateSet digest. persisted 조회 참조가 아니다. |
| `evidence_digest` | sha256 string | 필수 | `{"provenance": provenance, "lineage": lineage}` 전체의 정본 JSON digest. 두 객체 안의 알려진 필드와 추가 필드를 모두 포함하며 `handoff_id` 계산에도 들어간다. |

### 2.5 `study`

| 이름 | 타입 | 필수/선택 | 의미 |
|---|---|---:|---|
| `study_id` | string | 필수 | `muni_study_<32 hex>` 형식의 MUNI Study 식별자. |
| `target_crop` | string | 필수 | 호출자가 선택한 작물 표지. 픽스처는 합성 표지만 사용한다. |
| `target_pathogen` | string | 필수 | 호출자가 선택한 병원체 표지. 픽스처는 합성 표지만 사용한다. |
| `purpose` | string | 필수 | 건식 연구 목적. 습식 결과나 효능 주장이 아니다. |
| `created_at` | UTC timestamp | 필수 | Study 식별자 계산에 포함되는 생성 시각. |
| `pack_ref` | string 또는 null | 필수 | Study 식별자 계산에 포함되는 pack 참조. 값이 없어도 필드와 `null`을 보존한다. |

### 2.6 `review`

| 이름 | 타입 | 필수/선택 | 의미 |
|---|---|---:|---|
| `review_id` | string | 필수 | MUNI review store에 실제 존재하는 persisted ReviewRecord ID. `handoff.review_ref`와 같다. |
| `candidate_set_ref` | string | 필수 | persisted ReviewRecord가 가리키는 CandidateSet ID. `candidate_set.set_id`와 같다. |
| `reviewer` | string | 필수 | MUNI 검토자 표지. nipo approval 주체와 동일하다고 가정하지 않는다. |
| `decision` | enum string | 필수 | handoff에서는 반드시 `APPROVED`. 계약 어휘는 `APPROVED`, `REJECTED`, `NEEDS_MORE`. |
| `note` | string | 필수 | 검토 메모. 습식 검증 결론이 아니다. |
| `decided_at` | UTC timestamp | 필수 | `YYYY-MM-DDTHH:MM:SS.ffffffZ` 형식의 검토 시각. |

### 2.7 `candidate_set`

| 이름 | 타입 | 필수/선택 | 의미 |
|---|---|---:|---|
| `set_id` | string | 필수 | MUNI candidate-set store에 실제 존재하는 persisted CandidateSet ID. exported projection digest는 `boundary.candidate_set_id`다. |
| `workflow_ref` | string | 필수 | `lineage.workflow.run.run_id`와 같은 계산 실행 참조. |
| `kind` | enum string | 필수 | `DIAGNOSTIC_DISCOVERY` 또는 `COMPOUND_SCREENING`. |
| `count` | integer | 필수 | 0 이상의 후보 수. `items` 길이와 같아야 한다. |
| `items` | object[] | 필수 | 후보별 불변 참조, 점수, 처분, 근거와 불확실성. |

### 2.8 `candidate_set.items[]`

| 이름 | 타입 | 필수/선택 | 의미 |
|---|---|---:|---|
| `candidate_id` | string | 필수 | 워크플로 안에서 후보를 가리키는 식별자. `candidate_content.candidate_id`와 반드시 같아야 하며 validator가 검사한다. |
| `candidate_content` | object | 필수 | v4 경계의 후보 내용 정본. 원 CandidateSet item에서 이전 `candidate_content_hash`만 제외한 모든 필드를 그대로 투영한다. 임의의 호출자 제공 후보 속성도 보존한다. |
| `candidate_content_hash` | sha256 string | 필수 | `candidate_content`의 정본 JSON 바이트에 대한 SHA-256. ActionPlan에 고정할 후보/예측의 불변 내용 참조이며 조용한 갱신은 금지한다. |
| `query_revision_id` | string | 필수 | 후보를 산출한 질의 개정 식별자. |
| `disposition` | enum string | 필수 | `RANKED`, `EXCLUDED`, `ABSTAINED` 중 하나. |
| `composite_score_ppm` | integer 또는 null | 필수 | `RANKED`이면 0..1,000,000, 그 외에는 `null`. 습식 성과 수치가 아니다. |
| `rationale` | object | 필수 | 계산 근거 묶음. |
| `rationale.reasons` | JSON value[] | 필수 | 순위·제외 이유 목록. |
| `rationale.objective_evaluations` | object[] | 필수 | 목적별 평가 레코드 목록. |
| `rationale.per_objective_utility_ppm` | object<string, integer> | 필수 | 목적 ID별 0..1,000,000 유틸리티. |
| `rationale.gate_result_ids` | JSON value[] | 필수 | 적용된 gate 결과 참조 목록. |
| `uncertainty` | object | 필수 | 미해결 상태 묶음. |
| `uncertainty.abstention_reasons` | string[] | 필수 | 기권 사유 어휘. |
| `uncertainty.required_next_evidence` | string[] | 필수 | 다음 검증 필요사항. 이미 획득한 증거 등급 선언이 아니다. |
| 그 밖의 워크플로 속성 | JSON value | 선택 | 원래 CandidateSet item에서 보존된 `rank`, 원시 근거 배열 등. 수신자가 의미를 모르면 그대로 보존한다. |

**검사되는 투영 불변식.** producer는 원 CandidateSet item의 필드를 `candidate_content`에 모두 보존하고, 같은 필드를 item 평면에 거울처럼 투영한다. validator는 이 결속을 세 규칙으로 검사한다. (1) `candidate_content`의 모든 필드는 같은 이름과 같은 값으로 item 평면에 존재해야 한다. (2) item 평면에는 `candidate_content`에 없는 필드로 `candidate_content`, `candidate_content_hash`, `rationale`, `uncertainty` 네 개만 올 수 있다. (3) `rationale`은 content의 `reasons`, `objective_evaluations`, `per_objective_utility_ppm`, `gate_result_ids`를, `uncertainty`는 content의 `abstention_reasons`, `required_next_evidence`를 그대로 모은 결정론적 투영과 같아야 한다. 따라서 평면 수준과 해시된 content가 서로 다른 후보나 근거를 가리키는 문서는 재계산된 digest를 갖추어도 거부된다.

### 2.9 `provenance`

| 이름 | 타입 | 필수/선택 | 의미 |
|---|---|---:|---|
| `collected_data` | object[] | 필수 | 최소 1개의 수집 출처 레코드. |
| `collected_data[].job_ref` | string | 필수 | 수집 작업 참조. 같은 값이 lineage 어댑터에 있어야 한다. |
| `collected_data[].source_ref` | string | 필수 | 수집 소스/어댑터 정체성. |
| `collected_data[].source_record_ref` | string | 필수 | 소스 내부 레코드 참조. |
| `collected_data[].digest` | sha256 string | 필수 | 수집된 정확한 바이트의 내용 해시. |

### 2.10 `lineage`

| 이름 | 타입 | 필수/선택 | 의미 |
|---|---|---:|---|
| `collection_adapters` | object[] | 필수 | 최소 1개의 어댑터 계보. |
| `collection_adapters[].adapter_identity` | string | 필수 | 해당 provenance `source_ref`와 같은 어댑터 정체성. |
| `collection_adapters[].job_ref` | string | 필수 | 해당 provenance `job_ref`와 같은 작업 참조. |
| `workflow` | object | 필수 | 후보 계산 워크플로 계보. |
| `workflow.tool_identity` | string | 필수 | MUNI 계산 도구 정체성. |
| `workflow.run` | object | 필수 | 완료된 WorkflowRun 스냅샷. |
| `workflow.run.run_id` | string | 필수 | `candidate_set.workflow_ref`와 같은 실행 식별자. |
| `workflow.run.study_ref` | string | 필수 | `study.study_id`와 같은 Study 참조. |
| `workflow.run.kind` | enum string | 필수 | `candidate_set.kind`와 같은 워크플로 종류. |
| `workflow.run.status` | string | 필수 | handoff에서는 반드시 `SUCCEEDED`. |
| `workflow.run.started_at` | UTC timestamp | 필수 | 계산 시작 시각. |
| `workflow.run.finished_at` | UTC timestamp | 필수 | 계산 완료 시각. `started_at`과 같거나 늦어야 하며 validator가 검사한다. |
| `workflow.parameters` | object | 필수 | 비어 있지 않은 재현 파라미터. 진단 워크플로는 `query_revision_ids`를 포함하며 다른 워크플로는 목적·적용형·제약·seed를 추가할 수 있다. |

## 3. v4 식별자와 persisted linkage 규칙

모든 식별자는 아래의 동일한 정본 JSON 규칙을 사용한다. JSON 값은 RFC 8785의 이 계약 지원 부분집합(`null`, boolean, UTF-8 string, 절댓값이 `9,007,199,254,740,991` 이하인 integer, array, string-key object)이어야 한다. binary float, surrogate code point, 중복 object key는 허용하지 않는다. object key는 UTF-16 code unit 순서로 정렬하고, UTF-8/`ensure_ascii=false`로 인코딩하며, 멤버·배열 구분자 뒤 공백 없이 직렬화한다. digest는 `"sha256:" + lowercase_hex(SHA-256(canonical_json(value)))`다.

내용 결정 ID의 공통 계산은 다음과 같다. 먼저 아래 표의 `content` object를 digest하고, `seed = {"seed_schema":"ai-scientist.identity.v1","kind":<kind>,"content_hash":<content digest>}`를 같은 정본 JSON으로 직렬화하여 SHA-256한다. 결과 ID는 `<kind>_<그 SHA-256 소문자 hex 앞 32자>`다. 필드 순서는 입력 순서가 아니라 위 정본 key 정렬 규칙으로 결정되며, 표에 없는 필드는 해당 ID preimage에 넣지 않는다.

| 식별자 | `kind` / 알고리즘 | 정확한 `content` 필드 |
|---|---|---|
| `study.study_id` | `muni_study` / 공통 내용 결정 ID | `target_crop`, `target_pathogen`, `purpose`, `created_at`, `pack_ref` |
| `boundary.candidate_set_id` | `muni_candidate_set` / 공통 내용 결정 ID | `workflow_ref`, `kind`, `items`, `count`; 값은 exported `candidate_set`에서 persisted `set_id`를 제외한 필드로 계산한다. |
| `boundary.review_id` | `muni_review` / 공통 내용 결정 ID | `candidate_set_ref`에는 `boundary.candidate_set_id`를 사용하고, 나머지는 exported `review`의 `reviewer`, `decision`, `note`, `decided_at`을 사용한다. |
| `handoff.handoff_id` | `muni_wet_lab_handoff` / 공통 내용 결정 ID | `review_ref`, `artifact_paths`, `disclaimer`, `evidence_digest`; 마지막 값은 `boundary.evidence_digest`에서 가져온다. |
| `candidate_set.items[].candidate_content_hash` | ID prefix/truncation 없이 위 digest 직접 사용 | 같은 item의 `candidate_content` object 전체 |

v4 producer는 경계 후보 hash를 먼저 계산하고 그 전체 exported item으로 `boundary.candidate_set_id`를 계산한 다음, 그 경계 참조로 `boundary.review_id`를 계산한다. 별도로 전체 `provenance`와 `lineage` 객체를 정확히 `{"provenance": provenance, "lineage": lineage}`로 투영해 `boundary.evidence_digest`를 계산한다. `handoff_id`는 persisted `review_ref`, artifact 경로, disclaimer와 이 evidence digest로 계산한다. 따라서 점수·처분·근거 변경은 candidate-set 경계 ID를, review 메모 변경은 review 경계 ID를, provenance 또는 lineage의 어떤 내용 변경도 evidence digest를 바꾼다. evidence digest를 함께 바꾸면 handoff ID도 바뀐다. 수신 validator는 재료 하나라도 없으면 검사를 생략하지 않고 `cannot verify identity` 또는 `cannot verify evidence digest`로 거부해야 한다.

암호학적 범위는 blanket한 JSON 전체가 아니다. `study_id`는 2.5절의 다섯 Study 필드만, candidate content hash는 해당 `candidate_content` 객체만, candidate-set/review 경계 ID는 위 표의 필드만, evidence digest는 `provenance`와 `lineage` 객체 전체만, handoff ID는 위 표의 네 값만 포함한다. persisted 조회 ID들(`persisted.*`, `review.review_id`, `candidate_set.set_id`, `handoff.candidate_set_ref`)은 암호학적으로 재계산하지 않고 교차 동일성만 검사한다. `schema_version`과 정본 면책문은 validator가 정확한 값으로 검사하지만 별도 digest 대상은 아니며, 알 수 없는 최상위 추가 필드는 어떤 ID나 digest에도 포함되지 않는다. 그러므로 수신자는 validator 성공을 문서 전체의 포괄적 tamper-evidence로 표현해서는 안 되며, 반입한 JSON 전체 바이트 hash를 별도로 고정해야 한다.

모든 digest와 내용 결정 ID는 **키가 없는(unkeyed) 정합성 digest**다. 위 알고리즘은 공개되어 있으므로 문서를 보유한 사람은 누구나 provenance, lineage, 후보 또는 다른 내용을 바꾼 뒤 모든 digest와 ID를 재계산해 완전히 자기정합적인 사슬을 만들 수 있다. 따라서 validator의 VALID 판정은 보유한 바이트가 내부적으로 정합하다는 사실만 증명하며, 문서의 출처나 작성자의 진위는 증명하지 않는다. 반입한 JSON 전체 바이트의 hash 고정은 수신 시점 이후의 변경을 탐지할 뿐, 수신 시점 이전의 작성 행위를 인증하지 않는다.

Markdown 산출물(`handoff-*.md`)의 바이트는 어떤 digest나 ID에도 포함되지 않고 validator도 검사하지 않는다. Markdown이 JSON과 어긋나도 JSON은 VALID로 판정되므로, 어긋난 Markdown은 사람 독자를 오도할 수 있다. **JSON이 유일한 정본**이며, Markdown은 사람용 렌더링일 뿐 권위 참조로 사용하지 않는다.

Persisted ID는 원 저장 레코드와 exported 경계 projection의 preimage가 다르므로 exported projection으로 재계산하지 않는다. 대신 `handoff.review_ref = persisted.review_ref = review.review_id`와 `handoff.candidate_set_ref = persisted.candidate_set_ref = review.candidate_set_ref = candidate_set.set_id`를 검증한다. 이 값들은 opaque linkage이며 producer가 실제 store lookup과 내용 일치 검사를 마친 레코드를 가리킨다. 경계 digest chain은 `boundary`에서 독립적으로 재계산한다.

## 4. ActionPlan 입력 매핑

| WetLabHandoff 원천 | nipo ActionPlan 입력 | 결속 규칙 |
|---|---|---|
| `handoff.handoff_id` | `external_handoff_ref` | 전달물의 MUNI 정체성으로 고정한다. 파일 경로로 대체하지 않는다. |
| 전달 JSON 전체 바이트의 SHA-256 | `external_handoff_content_hash` | nipo 반입 시 계산해 고정한다. 동일 ID의 내용 변화를 거부한다. |
| `study.study_id` | `external_study_ref` | ActionPlan의 Project/Session 문맥에 연결하되 MUNI 식별자를 재작성하지 않는다. |
| `study.target_crop`, `study.target_pathogen`, `study.purpose` | `study_context` | 실험 설계 문맥으로 복사한다. 관측 결과로 취급하지 않는다. |
| `handoff.candidate_set_ref` | `candidate_set_ref` | MUNI store에 실제 존재하는 후보 목록의 조회 참조. 경계 `candidate_set.set_id`로 대체하지 않는다. |
| `candidate_set.items[].candidate_id` | `planned_subject.external_candidate_id` | 각 실험 대상의 외부 식별자. |
| `candidate_set.items[].candidate_content_hash` | `prediction_reference.content_hash` | **핵심 결속값**. ActionPlan 생성 시 고정하고 이후 Run/Execution에서 바꾸지 않는다. |
| 후보의 `disposition`, `composite_score_ppm`, `rationale`, `uncertainty` | `planning_basis` | 우선순위와 설계 근거. Evidence 또는 습식 결과로 승격하지 않는다. |
| `handoff.review_ref`, `review.decision`, `review.decided_at` | `source_review_ref` | MUNI store에 실제 존재하는 검토의 승인 계보. 경계 `review.review_id`로 대체하지 않으며 nipo의 별도 human approval을 대신하지 않는다. |
| `provenance` | `external_input_provenance` | 건식 입력 추적에 보존한다. |
| `lineage.workflow` | `external_computation_lineage` | 도구·실행·파라미터 재현 계보로 보존한다. |
| `disclaimer` | `dry_lab_disclaimer` | ActionPlan 표시와 후속 검토 화면까지 손실 없이 전달한다. |
| 해당 필드 없음 | `intended_evidence_tier` | 사람이 공유 정본 어휘에서 습식 계획의 목표 등급을 선택한다. MUNI 후보에서 추론하거나 복사하지 않는다. |

표의 nipo 입력 이름은 ActionPlan에서 보존해야 할 논리 입력을 명명한다. nipo 구현 세션은 현행 ActionPlan 스키마에 맞춰 물리 필드를 배치하되, 위 결속 의미를 약화해서는 안 된다.

## 5. 교차 불변식

1. **식별자 정합성**: persisted chain은 `handoff.review_ref = persisted.review_ref = review.review_id`, `handoff.candidate_set_ref = persisted.candidate_set_ref = review.candidate_set_ref = candidate_set.set_id`이고, 재계산 가능한 경계 digest는 `boundary.candidate_set_id`와 `boundary.review_id`에 있어야 한다. 또한 `candidate_set.workflow_ref = lineage.workflow.run.run_id`, `lineage.workflow.run.study_ref = study.study_id`여야 하며 provenance와 adapter lineage의 `job_ref`/source 정체성도 정확히 대응해야 한다. 각 후보 item의 평면 필드는 해시된 `candidate_content`의 거울 투영이어야 하고(2.8의 세 규칙), `lineage.workflow.run.finished_at`은 `started_at`과 같거나 늦어야 한다.
2. **불변 후보/예측 참조**: ActionPlan은 `candidate_content_hash`를 원문 그대로 고정한다. 후보를 재계산하면 새 내용 해시와 새 참조를 만들며 기존 ActionPlan을 조용히 갱신하지 않는다.
3. **증거 등급 어휘 공유**: 습식 관측에만 `PURIFIED_ENZYME`, `LYSATE`, `WHOLE_ISOLATE`, `SPIKED_MATRIX`, `RETROSPECTIVE_FIELD`, `PROSPECTIVE_FIELD`의 정본 어휘를 쓴다. 양쪽에서 같은 이름의 의미를 따로 재정의하지 않는다.
4. **권위 경계**: nipo kernel은 Project부터 Export까지의 권위 레코드를 생성·승인·실행·변이·리뷰·발행·익스포트·재실행하지 않는다. MUNI도 nipo 권위 레코드를 변이하지 않는다. ActionPlan 결속과 approval은 사람/권위 surface의 행위다.
5. **후보는 증거 등급이 아님**: MUNI 후보, 점수, 처분, 검토 승인은 어떤 evidence tier도 갖지 않으며 tier로 승격되지 않는다. `required_next_evidence`는 결측 요구사항이지 증거 획득 선언이 아니다.

## 6. 주장 경계

**WetLabHandoff는 습식 검증을 기다리는 dry-lab 산출물이다.** 후보와 점수는 실험 우선순위를 표현할 뿐이며, 효능·유효성·치료·방제·살균 또는 실험실 성과를 주장하지 않는다. 실제 습식 관측은 nipo 권위 사슬을 거쳐 별도 ArtifactVersion과 검토 기록으로 남아야 한다.
