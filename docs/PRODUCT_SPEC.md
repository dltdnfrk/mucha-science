# Mucha Science — 제품 명세서

```yaml
schema_version: 1
doc_id: muni-lab-product-spec-001
project: muni-lab
status: draft
owner: hyunjun (human-approval-required)
baseline_commit: e487c82f54383278553c1a9a9334c684f679abac
class: new
supersedes: none
created_at: 2026-08-01
source_interview: interview_20260801_060542
source_seed: seed_3dc497ab4be9
build_agent: senpi
governance_standard: MUNI/Ouroboros/documentation-governance (2026-08-01 확정)
```

> **상태 안내**: 이 문서는 `draft`다. 작업트리에 미커밋 변경(41 modified + 4 untracked)이
> 있으므로 실행 전 별도 세션에서 G0/G1 확인이 필요하다.
> P0 Scientific Control Plane recovery는 별도 절차이며 이 문서의 범위가 아니다.

---

## 1. 존재 이유

**작물 보호·병원균 대응 물질 연구의 범용 리서치 툴**
(엔자임/프로틴 컴퓨트 시뮬레이터).

대상 기능은 **병원균 진단, 방제, 작물 보호, 코팅 등 복수**이며,
하나의 물질이 복수 기능을 갖는 경우를 포함한다.

**성격**: 특정 기능이나 특정 병원균 전용 도구가 **아니다.**
구조 예측 도구가 단 하나의 단백질만 예측하지 않듯,
이 플랫폼도 하나의 기능이나 하나의 대상에 묶이지 않는다.
사용자가 가져오는 타깃과 목적을 받아 처리한다.

구현되어 있는 자율 리서치 엔진(인제스트 → 다중 페르소나 Council 토론 → 사람 검증 →
지식 축적)은 그 목표를 향한 **기반**이지 목적 자체가 아니다.

## 2. 대상 사용자와 사용 맥락

- 사용자: 단일 연구자. 로컬 서버 웹앱으로 사용한다.
- 배포: API와 기존 React UI를 재사용한 프런트엔드를 하나의 로컬 서버가 제공하며,
  단일 Docker image와 `docker-compose`로 패키징한다.
- 용도: 연구 목적 및 제품 R&D. 외부 판매 대상이 아니다.
- 품질 기준: 상용화 수준 그 이상.
- 제품명은 Mucha Science, 내부 모듈명은 호환성을 위해 `muchanipo` 유지.

## 3. 한 문장 정의

> 대상 병원균의 프로테옴과 도메인 팩이 정의한 대비 집합을 입력하면,
> **선택된 기능 목적에 맞는** 표적을 선정하고 그 기능을 수행하는 물질 후보를 평가해,
> 순위 후보, 사유가 명시된 제외 후보, 기계 판독 가능한 사유와 필요한 다음 증거가 명시된
> 기권 후보의 세 목록으로 예상 선택성과 근거와 습식 검증 우선순위를 출력한다.

출력은 항상 `ranked` / `excluded` / `abstained`의 세 목록이다. `excluded`에는 배제 사유를,
`abstained`에는 버전 관리된 기계 판독 가능 사유와 순위 자격을 얻기 위해 필요한 다음 증거를
기록한다. 과학적 실패와 지식 부족을 하나의 상태로 합치지 않는다.

### 단계별 입출력

1. **타깃 선정** — 입력: 병원균 프로테옴 + 대비 집합 프로테옴.
   HMM·BLAST·구조 기반 검색으로 상동체를 스캔해 대비 집합에 없고 대상에만 있는 효소를 찾는다.
   출력: 타깃 후보 순위 + 특이성 근거
2. **후보 생성/스크리닝** — 입력: 타깃. 메커니즘 적합성 판정, 도킹·친화도 예측.
   출력: 물질 후보 순위 + 예측값 + 불확실성
3. **성능 예측** — 입력: 후보 + 사용 맥락. 오프타깃 활성, 예상 성능 범위,
   필요한 대조군과 반복 수. 출력: 습식 실험 설계 제안
4. **습식 인계와 회수** — 상위 후보를 합성·시험으로 넘기고 결과를 받아 모델을 보정

## 4. 3층 구조 (핵심 아키텍처)

| 층 | 내용 |
|---|---|
| **플랫폼** (범용 엔진) | 타깃 스캔·상동체 분석, 구조/도킹 예측 인터페이스, **목적 함수 라이브러리와 조합기**, 증거 사다리 구조, 불확실성·대조군 통계, 벤치마크 하네스, 사람 검증 절차 |
| **도메인 팩** (지식·데이터) | 병원균 게놈·프로테옴 소스, 화학 라이브러리, 대비 집합 레퍼런스 프로테옴, 어세이·증거 어휘, 엔터티 해소 규칙. **팩은 "무엇을 아는가"를 정의하지 "무엇을 원하는가"를 정의하지 않는다** |
| **사용자 질의** (실행 시점) | **기능 목적** — 팩도 플랫폼도 아니다 |

> **폐기된 설계**: "기능 목적을 도메인 팩이 고정한다"는 구조는 잘못이다.
> 기능마다 새 팩이 필요해지고 다기능 물질은 특수 팩이 또 필요해져
> 범용 리서치 툴이 될 수 없다.

### 목적 함수는 1개부터 N개까지 연속 지원

단일 프로브 설계와 다목적 분자 설계는 **다른 모드가 아니라 목적 함수 개수의 차이**다.
진단용 단일 타깃 선택성 최적화는 목적 함수가 하나인 특수 경우이고,
코팅이면서 방제 효과를 갖는 물질은 여럿인 경우다. 둘 사이에 구조적 단절이 없어야 하며
사용자가 목적을 추가·제거하며 탐색할 수 있어야 한다.

제공 목적 함수 예: 대상 병원균 결합·활성, 비표적 회피, 검출 가능성, 억제·사멸 활성,
표면 부착·지속성, 합성 가능성, 안정성. 사용자가 조합하고 가중치·제약을 지정한다.

### 목적 함수 조합기 의미론

필수 플랫폼 제약과 사용자 하드 제약을 먼저 논리곱(AND)으로 평가한다. 하나라도 `FAIL`이면
`EXCLUDED`, 하나라도 `UNKNOWN`이면 자격 미해결인 `ABSTAINED`다. 통과한 후보만 각 목적의
버전 관리된 `[0, 1]` 유틸리티를 ppm 정수 척도(`[0, 1_000_000]`)로 정규화한 뒤 정규화 가중
산술평균으로 복합 점수를 계산해 순위화한다. Pareto 전선은 진단·정보 표시용일 뿐 최종 순위를
결정하지 않는다. 활성 목적 값이 누락되면 후보는 `ABSTAINED`이며, 후보별로 가중치를 재분배하지
않는다.

질의 편집은 기존 상태를 덮어쓰지 않고 불변 `UserQueryRevision`을 생성한다. 합성가능성은 모든
질의에 플랫폼 하드 제약으로 항상 주입된다. 환경 노출형 application type에는 작물 약해,
토양·유익 미생물 영향, 취급자 노출의 3개 안전 스크린도 자동 주입된다. 사용자는 이 플랫폼
제약을 제거·비활성화·가중 축소할 수 없고 더 엄격하게 만들 수만 있다.

### 선택성도 질의로 표현된다

넓게 작용할지 좁게 작용할지는 **목적 함수와 대비 집합의 지정 문제**다.
진단은 대상 하나에 좁게, 방제는 대상 집합에 넓게 그러나 작물·토양 미생물·인간에는
좁게 지정하면 된다. 플랫폼은 어느 쪽도 강제하지 않는다.

### 입력의 개방성

고정된 병원균 목록이나 작물 목록을 하드코딩하지 않는다.
팩은 데이터 접근 경로와 어휘를 제공할 뿐 **대상 범위를 제한하지 않는다.**

### 데이터 소스 정책

이 정책은 특정 도메인 팩을 선택하는 기준이 아니라 모든 팩에 적용되는 플랫폼 수준의
소스 허용·보류 정책이다.

- **필수 소스**: NCBI AMRFinderPlus, NCBI RefSeq/GenBank/Pathogen Detection, UniProtKB.
- **라이선스 게이트가 있는 선택 소스**: CARD/RGI. 고정된(pinned) 라이선스 문구가 상업적
  사용을 제한하므로 단순히 "open database"로 표시해서는 안 된다. 제품에서 사용하려면 별도의
  라이선스 확보와 법률 검토를 통과해야 한다.
- **보류 소스**: BRENDA, ChEMBL, PubChem, ZINC. 첫 팩에 필요한 필드와 각 소스의 재배포·상업적
  이용 권리가 확인될 때까지 팩에 포함하지 않는다.

모든 소스 접근은 `docs/design-contracts-v1.md` D5의 불변 `SourceRecord`를 provenance 앵커로
삼는다. 가변 `latest` API는 반드시 스냅샷하며, 검색 시각(`retrieved_at`)과 콘텐츠 해시가 실질
버전이다. 라이선스 결정이 `UNKNOWN` 또는 `DENIED`이면 재배포와 팩 활성화를 차단한다.

첫 팩의 구체적 대상은 여전히 별도 결정이며(14장), 이 정책은 첫 팩을 선택하거나 그 미결정을
해소하지 않는다.

## 5. 핵심 원칙

### P1. 산출물은 물질이 아니라 실험 우선순위다

도킹 점수는 결합상수도 억제농도도 아니며 진단 민감도는 더더욱 아니다.
물리적으로 타당하지 않은 포즈 문제와 서열 유사도 누출 문제가 문헌으로 지적되어 있다.
따라서 출력은 "이 물질이 작동한다"는 주장이 아니라
**"이 순서로 실험할 가치가 있고 근거는 이것이다"**라는 우선순위와 근거다.
상용화 수준 이상이라는 품질 기준의 실질은 **여기서 과장된 주장을 하지 않는 것**이다.

### P2. 계산 예측은 증거 사다리의 어떤 등급도 아니다

예측은 실측이 아니므로 사다리 아래의 별도 계층이다.
데이터 모델에서 명시적으로 구분한다. **예측값이 증거로 오인되는 것이 이 분야의
대표적 실패 모드다.**

### P3. 예측과 실측의 짝 보존은 필수 요구사항이다

모든 습식 데이터는 6개 증거 등급 중 하나의 경험적 `AssayObservation`으로 저장된다.
`Measurement`는 예측-검증 서브타입으로 정확히 하나의 불변·endpoint 호환 예측을 참조해야 한다.
진정한 선행 예측이 없는 탐색·인제스트 관측은 명시적으로 비짝으로 남고 예측 적중률·보정 통계에서
제외된다. 플랫폼은 소급 예측을 날조하지 않는다.

관측 조건과 대조군·반복은 `AssayCondition`에 명시한다. 외부 관측과 문헌의 출처는 불변 artifact에
고정된 `SourceRecord`로 추적하고, 출처 span과 entailment를 포함한 해석적 주장은 `Claim`으로
분리해 경험적 관측이나 증거 등급으로 오인되지 않게 한다.

### P4. 합성 경로를 제시할 수 없는 후보는 순위에 올리지 않는다

만들 수 없는 것을 우선순위에 올리는 것은 산출물이 아니라 잡음이다.

## 6. 증거 사다리 — 기록과 자동 보정의 상한이 다르다

증거 등급: 정제 효소 → 용해물 → 전체 분리주 → 스파이크된 매트릭스 → 후향 현장 → 전향 현장

- **기록은 전 등급.** 상단을 기록하지 못하면 이 물질이 어디까지 검증됐는지 시스템이
  모르게 되고 개발 진행 상태 추적 도구로서 실패한다
- **자동 모델 보정은 정제 효소·용해물까지.** 그 위 등급은 매트릭스 효과·샘플링·보관·
  조작·오염 같은 교란 변수가 많아, 도킹 모델 파라미터 보정에 직접 먹이면
  **분자 수준 예측이 시스템 수준 잡음을 학습**한다
- 상위 등급 결과가 하위 예측과 어긋나면 모델 파라미터 문제가 아니라 가설·맥락의
  문제일 가능성이 크므로 `HumanInterpretationSignal`을 만들고 자동 보정에는 쓰지 않는다

자동 보정 자격은 사용자가 설정하는 값이 아니라 다음 규칙으로만 파생한다.

```text
eligible = tier in {PURIFIED_ENZYME, LYSATE}
  AND qc_status == PASS
  AND pair_relation == DIRECT_ESTIMAND
  AND prediction.origin == PLATFORM_COMPUTATION
  AND pairing_design in {PROSPECTIVE_LOCKED, RETROSPECTIVE_BLINDED}
  AND benchmark_split_role not in {VALIDATION, TEST}
```

그 밖의 짝도 기록할 수 있지만 자동 보정에는 들어가지 않는다.

**평가 지표는 목적에 따라 선택된다**: 진단=검출한계·정량한계·민감도·특이도 /
방제=억제 농도·방제 효과·지속성 / 작물 보호=약해 없음·보호 지속 기간 /
코팅=부착성·내구성·환경 안정성.
사다리의 **단계 구조는 목적과 무관하게 유지**하되 각 단계의 측정 항목을 목적이 결정한다.

## 7. 자율 리서치 엔진의 역할 — 권위 등급이 다르다

| 역할 | 내용 | 산출물의 지위 |
|---|---|---|
| (a) 도메인 팩 구축 | 논문·DB 인제스트 → 팩 지식 생성·갱신 | 사람 검증 통과분만 팩에 반영 |
| (b) 가설 생성 | 유망 스캐폴드·타깃 가설로 탐색 공간을 좁힘 | **계산이 검증할 후보이지 증거가 아님** |
| (c) 결과 해석 보조 | 예측-실측 불일치 시 사람 해석 보조 | 제안이지 결정이 아님. **자동 모델 보정 경로에 어떤 경우에도 들어가지 않음** |

**관통 불변식**: Council의 산출물은 어느 경우에도 증거가 아니다.
문헌 근거가 있는 주장과 Council의 추론을 표시상 구분하며,
후자를 전자로 승격하려면 사람 검증을 거친다.

## 8. 계산 백엔드 — 오케스트레이터

플랫폼은 계산 오케스트레이터이고 실제 계산은 외부 도구를 어댑터로 호출한다.
**자체 도킹·스코어링 엔진을 갖는 것은 목표가 아니다.**

근거 셋:
1. 별개 연구 영역이라 직접 구현하면 항상 뒤처지고 유지 부담만 커진다
2. **검증 부담이 이중**이 된다. 파이프라인이 유용한지 증명하기 전에
   우리 계산 엔진이 옳은지부터 증명해야 한다
3. **가치 주장이 흐려진다.** 이 제품의 주장은 도킹 점수를 더 잘 낸다가 아니라
   **어떤 계산을 어떤 순서로 조합해 실험 우선순위를 더 잘 낸다**는 것이다

**어댑터 요구사항**:
- 호출마다 불변 replay manifest를 저장한다. manifest에는 어댑터·도구 build identity,
  executable SHA-256, container digest, 전체 정준 파라미터, 요청 seed와 seed 처리 방식,
  환경 fingerprint, 입력·출력 hash, 호출 당시 limitation profile snapshot이 포함된다.
- 예측은 content-addressed 불변 버전이다. 도구 교체·업그레이드는 새 `predictor_signature`와
  `recomputes` 링크를 가진 새 prediction revision을 만들며, 기존 예측·짝·이력을 수정하지 않는다.
- 순위를 생산하는 모든 어댑터는 R1 replay capsule(재호출 레시피)을 제공하고, 어댑터별 R2
  conformance profile을 통과해야 한다. byte-exact 재현은 결정론적 도구에만 요구하며,
  비결정론적 도구는 사전 선언된 허용오차와 하류 결정 불변식으로 판정한다.
- 모델·build를 고정할 수 없는 원격 서비스는 R0이며 rankable prediction을 생산할 수 없다.
- **도구별 알려진 한계를 메타데이터로 표시** — 소비자가 모르면 점수를 과신한다.

### 재현성 수준의 전체 맥락

위에서 채택한 계약은 R1 replay capsule과 R2 conformance profile이다. 전체 재현성 사다리는
다음과 같으며, 상위 수준을 하위 수준의 계산 계약과 혼동하지 않는다.

- **R0 Traceable**: 누가 무엇을 어떤 source/version으로 실행했는지 추적할 수 있다.
- **R1 Replayable**: 같은 code/container/seed/input으로 실행을 재생할 수 있다.
- **R2 Computationally reproducible**: 사전 선언된 허용오차 안에서 결과와 결론이 일치한다.
- **R3 Independently replicated**: 독립 운영자가 독립 환경에서 같은 계산 결과와 결론을 재현한다.
- **R4 Experimentally reproduced**: 독립 실험실이 해당 현상·어세이 결과를 재현한다.
- **R5 Clinically validated**: 전향적 코호트와 규제·임상 검증을 통과한다.

플랫폼의 dry-lab 목표는 **R1-R2**다. 문헌에서 가져온 실험 결과는 원 출판물이 가진 증거
등급을 결코 넘지 않으며, 플랫폼의 계산 재현성이 그 결과를 더 높은 증거 등급으로 승격하지 않는다.

**예외**: 목적 함수 조합기와 최종 순위 산정 로직은 자체 구현이다. 플랫폼의 본체다.

## 9. 성공 판정 — 절대 임계값 없음, 대조 비교로만

**세 갈래 대조**: ① 이 시뮬레이터의 계산 파이프라인 ② 범용 프런티어 LLM의 문헌 기반 추천
③ 단순 베이스라인(서열 유사도만 또는 무작위).
세 번째가 반드시 있어야 한다 — 없으면 둘 다 무작위보다 못한 경우를 알아채지 못한다.

**공정한 비교**: 범용 LLM은 도킹 계산을 못 하므로 같은 작업을 겨루는 것이 아니다.
산출물 수준에서 — 어느 쪽 상위 후보가 습식에서 더 자주 유효한지를 본다.

**지표 4개**:
1. 상위 N개 농축도 (예산이 유한하므로 전체 정확도가 아니라 상위 순위 정밀도)
2. 배제 성능 (헛된 합성·시험을 줄이는 것이 직접적 가치)
3. **보정 품질** (확신 80%라 했을 때 실제로 그 비율로 맞았는가.
   틀리더라도 얼마나 틀릴지 정직하게 말하는 시스템은 쓸 수 있지만
   근거 없이 확신하는 시스템은 쓸 수 없다)
4. 예산 대비 유효 후보 수

보정은 `(predictor_signature, endpoint_definition_hash, evidence_tier,
assay_condition_family_hash, pairing_design)`으로 층화한다. 각 stratum의 지표는 표본 수 `n`과
`predictor_signature`를 함께 보고한다. 전체 지표는 stratum별 지표의 사전 고정 가중
macro-aggregate로만 계산하며 임의의 micro-pooling을 하지 않는다. 서로 다른 predictor version의
자료는 사전등록된 bridge study가 동등성을 입증하고 `VersionEquivalenceGroup`으로 명시된 뒤에만
함께 묶을 수 있다.

## 10. 최소 성공 시나리오 — 2단계

한 덩어리로 두면 습식 1건으로 성능을 주장하게 되므로 나눈다.

**M1 — 루프 완결**: 팩 1개·타깃 1개·목적 1개로 스크리닝 → 상위 후보 →
습식 1건 검증 → 예측-실측 짝 기록.
**증명하는 것은 성능이 아니라 배관이다.** 데이터 소스에서 계산·순위 산정을 거쳐
실험·기록까지 끊기지 않는다는 사실. **이 단계에서 성능 주장은 하지 않는다.**

**M2 — 판정 가능**: 회고적 벤치마크가 **누출 방지 분할** 위에서 구성되고
세 갈래 대조가 실행되어 결과가 나오는 상태. **이때 비로소 유능한지 말할 수 있다.**
이후 전향적 예측(예측을 먼저 고정한 뒤 실험)으로 넘어간다.

**첫 도메인 팩의 구체적 대상은 별도 결정**이다(연구 우선순위·사업 맥락 사안이며
플랫폼 설계에 영향을 주지 않는다). 단 **선정 기준은 확정**한다:
① 공개 게놈·프로테옴 데이터 충분
② **알려진 사례가 있어 회고적 벤치마크를 구성할 수 있을 것** — 없으면 M2에 영원히 도달 못 함
③ 대비 집합 레퍼런스 확보 가능
④ 습식 검증의 현실성

## 11. 수락기준

| ID | 수락기준 | verification_method |
|---|---|---|
| AC-01 | 목적 1개와 N개가 동일한 조합기 경로를 통과한다. 하드 제약은 AND로 먼저 평가되어 FAIL=`EXCLUDED`, UNKNOWN=`ABSTAINED`가 되고, 적격 후보는 버전 관리된 `[0,1]` 유틸리티의 ppm 정규화 가중 산술평균으로 순위화된다. 결측 목적값에는 가중치를 재분배하지 않고 Pareto 전선은 정보용이다. 목적·가중치·제약 편집은 불변 `UserQueryRevision`을 만든다 | `automated_test` |
| AC-02 | 도메인 팩이 데이터 소스·어휘·대비 집합 레퍼런스만 정의하고 기능 목적을 고정하지 않는다. 고정된 병원균·작물 목록이 코드에 하드코딩되지 않는다 | `automated_test` + `manual_review` |
| AC-03 | 계산 예측이 증거 사다리와 분리되고 모든 습식 데이터가 `AssayObservation`으로 저장된다. 예측-검증 `Measurement`는 정확히 하나의 불변·endpoint 호환 예측을 참조하며, 비짝 관측은 소급 예측 없이 적중률·보정 통계에서 제외된다 | `automated_test` |
| AC-04 | 자동 보정 자격이 tier∈{PURIFIED_ENZYME, LYSATE}, QC PASS, DIRECT_ESTIMAND, PLATFORM_COMPUTATION, pairing∈{PROSPECTIVE_LOCKED, RETROSPECTIVE_BLINDED}, split∉{VALIDATION, TEST}의 논리곱으로 파생되고 사용자 설정이 불가하다. 상위 등급 불일치는 `HumanInterpretationSignal`로 표면화된다 | `automated_test` |
| AC-05 | 모든 adapter invocation이 build·실행 파일·container·전체 파라미터·seed 처리·환경·입출력 hash·한계 snapshot의 불변 manifest를 남긴다. 순위 어댑터는 R1 capsule과 R2 profile을 제공하며 byte-exact는 결정론적 도구에만 적용하고, R0 원격 서비스는 rankable 예측을 만들지 못한다. 업그레이드는 새 `predictor_signature`와 `recomputes` 링크의 content-addressed prediction revision을 만들며 이력을 수정하지 않는다 | `automated_test` |
| AC-06 | 합성 경로를 제시할 수 없는 후보가 순위에서 배제된다 | `automated_test` |
| AC-07 | 합성가능성 제약은 항상 주입되고, 환경 노출형 application type에는 안전성 배제 스크린 3종(작물 약해, 토양·유익 미생물 영향, 취급자 노출)이 자동 주입된다. 사용자는 이를 제거·완화할 수 없고 강화만 할 수 있다 | `automated_test` |
| AC-08 | 벤치마크 하네스가 제품 기능으로 내장되어 누출 방지 분할, 세 갈래 대조, 보정 평가, 예측 사전 고정을 수행한다 | `automated_test` + `artifact_inspection` |
| AC-09 | M1 루프 완결: 팩 1개·타깃 1개·목적 1개로 스크리닝부터 습식 1건 예측-실측 짝 기록까지 관통한다 | `build_or_deploy_check` + `artifact_inspection` |
| AC-10 | 로컬 서버가 API와 기존 React UI를 제공하고 단일 Docker image와 `docker-compose`로 배포되며, 기본 bind 주소는 `127.0.0.1`이다 | `build_or_deploy_check` + `manual_review` |

**공통 증거 요구 4속성**: `target_commit`, 불변 `evidence_ref`, `verified_by`, `verified_at`.

## 12. 비목표

- **완전 자유 de novo 설계** — 초기 범위 밖. 스크리닝 → 알려진 스캐폴드의 제약된 변형까지가
  초기 범위이며, 어느 단계든 합성 가능성 필터가 필수
- **구조 예측 직접 구현** — 어댑터로 수용. 출처·모델 버전·신뢰도 지표 기록 필수
  (예측 구조와 실험적 구조를 구분하지 않으면 하류 도킹 결과의 신뢰도를 알 수 없다)
- **자체 도킹·스코어링 엔진**
- **규제 제출용 독성·위해성 평가** — 단 **초기 스크리닝의 배제 필터는 범위 안**이다.
  방제제·코팅제는 작물에 살포·도포되어 노출량과 대상이 진단 프로브와 근본적으로 다르다.
  인간 상동체 회피 스캔은 **선택성 목적이지 안전성 보증이 아니며** 산출물에 명시해야 한다
- **습식 실험 실행 관리·장비 제어** — 결과 기록까지가 책임 (→ Nipo가 담당)
- **서열·구조 데이터의 1차 생산** — 외부 데이터 소비만
- **클라우드·외부 호스팅(Supabase, AWS 포함)** — 단일 사용자 로컬 제품이며 file ledger가
  authority store다. DB 이전은 load test가 필요성을 입증한 뒤에만 검토할 미래 결정이다
- **Tauri 셸 유지보수·제거** — 이번 제품 명세 개정과 구현 범위 밖
- 판매용 상용 기능

**패널 설계**(여러 단일 선택적 물질의 조합으로 판별)는 비목표로 못 박지 않고
후속 확장 후보로 남긴다.

## 13. 포트폴리오 내 위치

```
   Mucha (건식 계산)                      Nipo (권위·증거·재현성)
타깃 선정 → 후보 순위화 → 예측  ──►  액션플랜 → 승인 → 실행 → 기록 → 검토
   산출물: 실험 우선순위          ◄──        산출물: 검증된 증거
                   (실측이 예측-실측 짝을 완성)
```

**Mucha가 비목표로 선언한 것이 Nipo의 핵심 역량이다.** 두 프로젝트는 도메인이 같고
계층이 다르다. 통합은 코드 합치기가 아니라 **루프 닫기**다.

> ### ⚠️ 독립 진행 원칙 (2026-08-01 사용자 확정)
>
> **Mucha와 Nipo는 현 단계에서 완전히 별개의 프로젝트로 진행한다.**
> 이 장의 역할 분담 서술은 **나중에 문을 닫지 않기 위한 참고**이지,
> 지금 수행할 공동 작업이 아니다.
>
> - 두 프로젝트를 조율하는 작업(공동 어휘집 병합, 공유 계약 문서 작성,
>   상대 프로젝트의 결정 대기)을 **지금 시작하지 않는다**
> - 이 프로젝트의 도메인 팩·일정·우선순위는 **독자적으로 결정한다**
> - 아래 계약 불변식 4개는 **공동 산출물이 아니라 이 프로젝트의 설계 제약**이다.
>   "나중에 이어붙일 수 있게 문을 열어 둔다"는 뜻이며, 지금 상대와 맞추는 작업은 아니다
> - 조율은 통합 트리거가 실제로 발동한 뒤에 시작한다

**지금 정해야 하는 계약 불변식 4개** (고치면 재수집이 필요한 것들):
① 식별자 정합성 ② 예측의 불변 참조 가능성(내용 해시) ③ 증거 등급 어휘 공유
④ 권위 경계 교차 적용. 필드 스키마·전송 형식·트리거·오류 처리는 루프 후로 미룬다.
계약 문서는 어느 프로젝트도 아닌 **포트폴리오 계층**에 둔다.

## 14. 미결정 사항

1. 첫 도메인 팩의 구체적 대상 (선정 기준은 확정, 대상은 별도 결정)
2. Mucha ↔ Nipo 통합 트리거의 구체 조건
3. 방법론 지식(도구 적합성, 벤치마크 함정)의 소유 — OntologyLab 담당이나
   현 단계는 각자 진행하며 중복 감수, 루프 가동 후 재검토

## 15. 관련 문서와 추적

- 인터뷰: `interview_20260801_060542` (제품 요구사항, 최종 ambiguity 0.171)
- 인터뷰: `interview_20260801_013438` (P0 recovery 요구사항, ambiguity 0.08)
- Seed: `seed_3dc497ab4be9` (부록 A의 embedded seed는 승인된 개정 seed로 추후 교체하며,
  이번 개정에서는 원문을 그대로 둔다)
- 개정 Seed: `seed_4ebb6abfbc6c` (`docs/ouroboros-seed-amendment-20260801.yaml`)
- 설계 계약: `docs/design-contracts-v1.md`
- 거버넌스 개정: `docs/governance-amendment-20260801.md`
- 정정 원문: `MUNI/Ouroboros/documentation-governance/mucha-domain-correction-20260801.json`
- 근거 리서치: `.omo/ulw-research/20260729-230445/` (phase-0, SYNTHESIS 등)
- 포트폴리오: `MUNI/Ouroboros/documentation-governance/PRODUCT_DEFINITIONS_DRAFT.md`

**P0 상태 주의**: Scientific Control Plane 계획이 5회 부트스트랩 시도에서 모두 실패했고
6차는 승인되지 않았다. 실패 원인은 전부 control plane 자기 명세의 결함이었다.
recovery 요구사항은 `interview_20260801_013438`에서 별도 확정했으며,
이 제품 명세가 그 범위 판단의 잣대가 된다 — **증거 엄격성은 과학 계층에 유지하고
하네스·부트스트랩 계층에서 축소**한다.

## 커밋 지침 — 경로를 명시해서 스테이징할 것

이 문서와 `docs/ouroboros-seed.yaml`은 2026-08-01에 생성된 **미추적 신규 파일**이다.
Git 명령은 실행하지 않았으므로 커밋 여부는 이 프로젝트 세션에서 결정한다.

**반드시 경로를 명시해서 스테이징한다:**

```bash
git add docs/PRODUCT_SPEC.md docs/ouroboros-seed.yaml
```

**`git add -A`, `git add .`, `git add docs/`를 쓰지 않는다.**
현재 이 저장소의 작업트리 상태는 41개 수정, 4개 미추적이며, **`docs/` 안에만 다른 미커밋 변경이 15개** 있다 — 기존 문서 14개 수정 + 미추적 1개.
일괄 스테이징하면 소유자와 완료 상태가 확인되지 않은 기존 변경까지 함께 커밋되어,
2026-08-01에 확정한 귀속·서명 게이트를 건너뛰게 된다.

기존 미커밋 변경의 처리 절차는 별도로 확정되어 있다 — 귀속 3등급
(ledger 지목 / 증거 2개 수렴 추론 / ownership-unknown), 등급별 허용 행위,
동일 세션 묶음 일괄 서명과 개별 서명 예외. 상세는
`MUNI/Ouroboros/documentation-governance/SESSION_HANDOFF.md` 참조.

---

## 부록 A — Ouroboros Seed

```yaml
goal: Build Mucha Science — a domain-universal research platform for crop protection
  and pathogen-response substance discovery that orchestrates external computational
  tools to produce uncertainty-calibrated, evidence-graded experimental priority rankings
  for candidate substances, with built-in benchmarking against frontier LLMs and baselines
  to prove the system's practical superiority.
task_type: code
brownfield_context:
  project_type: brownfield
  context_references:
  - path: /Users/hyunjun/Documents/MUNI/muni-lab
    role: primary
    summary: Mucha Science codebase with implemented autonomous research engine (document
      ingest, multi-persona Council deliberation, human verification, knowledge accumulation)
      in a Tauri desktop app; simulator components not yet implemented
  existing_patterns:
  - Source document folder (human-owned) and wiki folder (LLM-owned) separation
  - Document ingest → ontology extraction → 5W1H insight extraction → multi-persona
    Council deliberation → human verification pipeline
  - Tauri desktop app shell with local web UI
  - Internal module name muchanipo maintained for compatibility
  existing_dependencies:
  - Tauri (desktop app framework)
  - Existing ingest and Council deliberation infrastructure
  - Existing human verification workflow
constraints:
- Output is experimental priorities with ranked evidence and uncertainty — never substance
  efficacy claims
- Computational predictions are never evidence grades; all evidence ladder tiers are
  wet-lab measurements only
- Auto-calibration feedback limited to purified-enzyme and lysate tiers; higher-tier
  discrepancies surface as human-interpretation signals, never auto-adjust model parameters
- Platform is computation orchestrator — no self-built docking, scoring, or structure-prediction
  engines; external tools via adapters only
- Unsynthesizable candidates excluded from all rankings — synthesizability filter
  is mandatory
- Council (multi-persona deliberation) output is never evidence; must be visually
  distinguished from literature-backed claims and requires human verification to upgrade
- Free de novo molecular generation is out of initial scope; library screening plus
  constrained scaffold variants only
- Wet-lab execution, equipment control, regulatory submission documents, and formal
  toxicity/safety assessment are out of scope
- Local desktop app (Tauri); commercial-grade robustness, data integrity, reproducibility,
  failure handling, and UX — but no multi-tenancy or billing
- Internal module name remains muchanipo for compatibility; product name is Mucha
  Science
- Domain pack supplies data and vocabulary but never fixes functional purpose; functional
  objectives are user-query-time parameters
- Every external tool invocation records tool name, version, parameters, and random
  seed; tool upgrades preserve historical prediction-measurement pair validity
acceptance_criteria:
- description: End-to-end candidate ranking pipeline — given a target proteome, contrast-set
    proteomes, and one or more objective functions, the platform orchestrates external
    adapters (homology scan, docking, affinity, molecular descriptors) to produce
    a ranked list of substance candidates with per-candidate selectivity scores, calibrated
    uncertainty estimates, synthesizability verdicts, and provenance traces linking
    every score to its tool version and parameters
  semantic_ac_key: ac_34dc0d5ca389057b
  verify_command: python -m pytest tests/test_pipeline_e2e.py -q
- description: Evidence ladder with prediction-measurement pairing — wet-lab results
    are recorded at any evidence tier (purified enzyme through field trial) each linked
    to the originating computational prediction; auto-calibration ingests only purified-enzyme
    and lysate results while higher-tier discrepancies are surfaced as human-interpretation
    alerts; prediction hit-rate statistics are computable from accumulated pairs
  semantic_ac_key: ac_fdadc89d4cdacfb4
  verify_command: python -m pytest tests/test_evidence_ladder.py -q
- description: Built-in benchmark harness — retrospective benchmarks run on literature-known
    success/failure pairs with leak-proof sequence-and-structure-similarity splits,
    executing three-way comparison (platform pipeline vs frontier-LLM recommendation
    vs simple baseline) and reporting top-N enrichment, exclusion performance, calibration
    quality, and budget-normalized effective candidate yield
  semantic_ac_key: ac_550394487287fff1
  verify_command: python -m pytest tests/test_benchmark_harness.py -q
- description: Autonomous research engine integrated as knowledge, hypothesis, and
    interpretation layer — document ingest, multi-persona Council deliberation, and
    human verification feed validated knowledge into domain packs, generate prioritized
    hypotheses for simulation, and produce interpretive commentary on results, with
    all Council outputs tagged as non-evidence and requiring human approval for status
    changes
  semantic_ac_key: ac_5932aff18561d43c
  verify_command: python -m pytest tests/test_research_engine_integration.py -q
- description: Domain pack and multi-objective function composition — domain packs
    load pathogen proteomes, chemical libraries, contrast-set references, assay vocabulary,
    and entity-resolution rules without fixing functional purpose; the objective-function
    library supports combining 1-to-N objectives (binding activity, selectivity, detection,
    inhibition, surface adhesion, stability, synthesizability) with user-specified
    weights and constraints at query time; safety-screening exclusion filters auto-activate
    for application types involving environmental exposure
  semantic_ac_key: ac_92aa9274fd140d36
  verify_command: python -m pytest tests/test_domain_pack_objectives.py -q
- description: Adapter reproducibility and limitation transparency contract — every
    computation adapter call persists tool identity, version, full parameters, and
    random seed sufficient for exact reproduction; upgrading or replacing a tool creates
    new prediction versions without invalidating historical prediction-measurement
    pairs; each adapter exposes known-limitation metadata (e.g. physically implausible
    pose rates, similarity-leakage inflation) consumable by downstream ranking and
    UI
  semantic_ac_key: ac_2e8e025b478c5c98
  verify_command: python -m pytest tests/test_adapter_contract.py -q
ontology_schema:
  name: SubstanceDiscoveryGraph
  description: Domain model for a universal crop-protection substance discovery platform
    encompassing proteins, candidate substances, computational predictions, wet-lab
    evidence, objective functions, domain packs, and benchmark evaluations
  fields:
  - name: ProteinRecord
    type: object
    description: Target or contrast protein with sequence hash, taxonomy, strain,
      allele/lineage, functional annotation, and structure references (source, model
      version, confidence)
    required: true
  - name: SubstanceCandidate
    type: object
    description: Probe or active substance with structural identifier (SMILES/InChI),
      scaffold class, mechanism, physicochemical descriptors, synthesizability verdict,
      and synthesis route reference
    required: true
  - name: Prediction
    type: object
    description: Computational prediction with tool name, version, parameters, random
      seed, input references, scored result, calibrated uncertainty, and known-limitation
      flags — explicitly not an evidence tier
    required: true
  - name: Measurement
    type: object
    description: Wet-lab result with evidence tier (purified enzyme
    required: true
  - name: EvidenceTier
    type: string
    description: Enumerated level in the evidence ladder — all tiers are empirical
      measurements; computational predictions sit below the ladder
    required: true
  - name: ObjectiveFunction
    type: object
    description: Named scoring function (binding affinity, selectivity against contrast
      set, detection limit, inhibition concentration, surface adhesion, stability,
      synthesizability) with type, parameters, and composability metadata
    required: true
  - name: DomainPack
    type: object
    description: Loadable knowledge module with data-source adapters, reference proteome
      sets, chemical library references, assay vocabulary, entity-resolution rules,
      and evidence-tier measurement definitions
    required: true
  - name: UserQuery
    type: object
    description: Runtime specification of target proteome(s), contrast set(s), selected
      objective functions with weights/constraints, and functional purpose
    required: true
  - name: BenchmarkRun
    type: object
    description: Evaluation record with split method (leak-proof), three-arm results
      (pipeline, frontier LLM, baseline), top-N enrichment, exclusion rate, calibration
      curve, and budget-normalized yield
    required: true
  - name: AdapterInvocation
    type: object
    description: Immutable log entry for one external tool call with tool ID, version,
      full parameters, seed, input hashes, output hashes, wall time, and limitation
      annotations
    required: true
  - name: CouncilDeliberation
    type: object
    description: Multi-persona discussion record with participating personas, literature
      citations, generated hypotheses, interpretive commentary, and non-evidence status
      flag requiring human verification for upgrade
    required: true
evaluation_principles:
- name: Epistemic Honesty
  description: Predictions are never presented as evidence; all outputs explicitly
    state their epistemic status and known limitations; confidence intervals are calibrated
    against actual hit rates
  weight: 0.3
- name: Experimental Utility
  description: Ranked outputs are directly actionable as wet-lab experiment plans
    with synthesizable candidates, required controls, and replicate counts
  weight: 0.25
- name: Reproducibility
  description: Every computation is fully reproducible from recorded tool versions,
    parameters, seeds, and input hashes; no implicit state
  weight: 0.2
- name: Provenance Integrity
  description: Every score, prediction, and evidence record traces back to its data
    sources, tool chain, and human verification decisions without gaps
  weight: 0.15
- name: Benchmark Rigor
  description: Evaluations use leak-proof splits, include baselines, and never conflate
    prediction confidence with empirical validation
  weight: 0.1
exit_conditions:
- name: Loop Completion
  description: End-to-end pipeline from data source ingestion through computation
    orchestration to wet-lab result recording operates without breakage for one domain
    pack, one target, and one objective
  criteria: At least one prediction-measurement pair is recorded with full provenance
    and correct evidence-tier assignment
- name: Judgment Capability
  description: Retrospective benchmark harness produces three-way comparison results
    on a literature-derived dataset
  criteria: Leak-proof split is verified, all three arms (pipeline, frontier LLM,
    baseline) return scored candidate lists, and top-N enrichment and calibration
    metrics are computed
- name: Evidence Fidelity
  description: Evidence ladder enforces tier-based handling rules and prediction-measurement
    pairing invariant
  criteria: Auto-calibration accepts only purified-enzyme and lysate data; higher-tier
    results are flagged for human interpretation; no prediction is stored without
    epistemic-status marking
- name: Council Governance
  description: Research engine outputs are integrated but never auto-promoted to evidence
    status
  criteria: Council deliberations are recorded with non-evidence tags; upgrade to
    pack knowledge requires logged human verification
metadata:
  seed_id: seed_3dc497ab4be9
  version: 1.0.0
  created_at: '2026-08-01T07:05:10.280330Z'
  ambiguity_score: 0.171
  interview_id: interview_20260801_060542
  parent_seed_id: null
  generation_mode: normal
  degraded: false
  unresolved_slots: []
  recovery_reason: null```

### 부록 A-2 — 개정 Seed (2026-08-01)

이 부록은 원본을 대체하지 않는 개정 계보를 기록한다:
`interview_20260801_060542` → 개정 인터뷰 `interview_20260801_140713`,
원본 `seed_3dc497ab4be9` → 개정 `seed_4ebb6abfbc6c`.

- `docs/ouroboros-seed-amendment-20260801.yaml` — SHA-256 `c2fea11c897520a27b00151005c3b2ff9db1d81ffbe86745567f8e58b31fc6b9`
- `docs/design-contracts-v1.md` — SHA-256 `4cb8f96a743e748ac621fd3fbf336a2ddf3cf5cada6f925b05bb8135865dce4b`

원본 Seed의 잘린 `Measurement` description은 개정 Seed의 D2 evidence-model 규칙으로
대체된다. 원본 Seed 파일과 이 부록에 embedded된 원본 YAML은 변경하지 않는다.

개정 내용 요약:
1. 조합기 의미론을 하드 제약 우선, ppm 정규화 가중 산술평균, Pareto 표시 전용으로 확정한다.
2. 경험적 `AssayObservation`과 예측-검증 `Measurement`를 분리하고 불변 1:1 예측 참조를 적용한다.
3. 재현성·예측 버전 규칙과 층화된 보정·버전 풀링 정책을 고정한다.
4. 인식론 상태와 후보 처분을 분리하고 기권 사유와 필요한 다음 증거를 기록한다.
5. `SourceRecord`·`AssayCondition`·`Claim`을 추가하고 로컬 서버 웹앱, 단일 Docker image와 `docker-compose`, 로컬 file ledger 권위를 전달 형식으로 확정한다.
