# MUNI simulator integration contract v1

이 문서는 Mucha ↔ Nipo 통합을 위한 로컬 계약 문서다. 문체와 기준은 `docs/PRODUCT_SPEC.md`의 포트폴리오 서술을 따른다.

## 1. Seed 계보

- `interview_20260802_004736` → `seed_984cb6855063`
- 이 seed는 ambiguity `0.507`에서 `2 - Generate Seed anyway (force)`로 생성됐다.
- 기준값은 goal `0.58` / constraint `0.62` / success_criteria `0.25`였다.
- 0.2 임계값을 넘었기 때문에, 미해결을 이유로 보류하지 않고 seed를 생성한 것이 맞다.
- 이유: 이번 계약은 실제 사용자 답변이 이미 4라운드에 걸쳐 수렴했으며, 남은 불명확성은 “생성 여부”가 아니라 “brownfield 보정과 성공 기준 해석”에 있었다. 따라서 seed를 더 미루기보다, 계약 문서에서 경계와 불변식을 명시하는 쪽이 정합적이었다.

## 2. brownfield 보정 기록

이 seed의 프로젝트 프레이밍은 greenfield 스타일이지만 사실과 다르다. **Mucha-science는 이미 플랫폼 스켈레톤과 M1 루프를 가지고 있고**, **Nipo-science는 이미 권위 체인을 가지고 있다**.

- Mucha-science HEAD `faa2e1a`에는 다음이 이미 있다: `platform_contracts`, `evidence_ladder`, `tools_ext`, `objectives`, `packs_loader`, `benchmark`, `research_integration`, `webserver`, `web/ui`, `Docker`, `scripts/m1_loop.py`.
- Nipo-science에는 이미 `Project → Session → ActionPlan → Run → Execution → ArtifactVersion → Review → Export` 권위 사슬이 있다.

따라서 구현자는 새로 시작하는 것이 아니라 **이 자산들 위에** 계약을 얹어야 한다. from scratch로 재해석하면 이미 존재하는 루프와 권위 기록을 깨뜨린다.

## 3. 성공 기준 보정

인터뷰 3라운드의 성공 정의는 명확했다: **“실제 유기화합물이 발견되고 real world wet lab 검증에서 실제 효과가 확인되는 것”**이다. 즉 wet-lab은 종착점이 아니라 실제 효과를 확인하는 필수 단계다.

seed가 wet-lab을 handoff target으로만 둔 것은 성공 기준을 축소한 것이 아니라, 라운드 4에서 **첫 validation target을 하드코딩하지 않기로 결정한 결과**다. 따라서 numeric success criteria가 “상위 100개 중 N개”처럼 비어 보이는 것은 정보 누락이 아니다. 그 값은 아직 정해지지 않았고, 정해지지 않기로 한 것이 맞다. 그 때문에 `success_criteria_clarity`가 `0.25`로 낮게 남았다.

## 4. 계약 불변식 4개

1. **식별자 정합성**
   - WetLabHandoff v4는 저장소 조회용 persisted 참조와 exported 내용에서 재계산하는 경계 값을 분리한다. `handoff.review_ref`와 `handoff.candidate_set_ref`는 실제 MUNI store 레코드를 가리키고 파일명도 persisted review ID에서 파생한다. `boundary.review_id`는 review projection, `boundary.candidate_set_id`는 candidate-set projection, `boundary.evidence_digest`는 전체 provenance/lineage projection을 각각 결속하며, handoff ID는 persisted review ref, artifact paths, disclaimer와 evidence digest를 결속한다.
   - 이 범위는 문서 전체의 blanket tamper-evidence가 아니다. persisted 조회 ID는 교차 동일성으로만 검사되고, 알 수 없는 최상위 추가 필드는 어떤 digest에도 포함되지 않는다. 수신자는 validator 검증 후 전달 JSON 전체 바이트 hash도 별도로 고정해야 한다.
   - 모든 digest는 키가 없는 정합성 digest다. 문서 보유자는 내용을 바꾸고 공개 알고리즘으로 전체 사슬을 재계산해 자기정합적인 문서를 만들 수 있으므로, validator 성공은 보유 바이트의 내부 정합성만 뜻하고 출처·작성자 진위는 뜻하지 않는다. 전체 바이트 hash 고정은 수신 시점 이후의 변경만 막는다.
   - Markdown 쌍(`handoff-*.md`)은 어떤 digest에도 들어가지 않고 validator가 검사하지 않는다. JSON과 어긋난 Markdown은 VALID 판정과 함께 사람을 오도할 수 있으므로 JSON이 정본이다. 계약이 필드 집합을 정의하는 중첩 블록은 닫힌 스키마이며 validator는 선언되지 않은 필드를 거부하고, 후보 item의 평면 필드가 해시된 `candidate_content`의 거울 투영과 같음을 검사한다.
   - 깨지면: Project/Session/Run/ArtifactVersion/Review 사이 추적이 끊기고, Mucha ↔ Nipo 사이 참조가 서로 다른 대상을 가리키거나 결속된 경계 내용을 검출하지 못한다.
2. **예측의 불변 참조(content hash)**
   - 깨지면: 같은 예측이 나중에 다른 내용으로 보이게 되어, 검증과 회고가 재현 불가능해진다.
3. **증거 등급 어휘 공유**
   - 깨지면: Mucha의 예측과 Nipo의 증거가 같은 말로 다른 뜻을 갖게 되어, “무엇이 관측이고 무엇이 추론인지”가 섞인다.
4. **권위 경계 교차 적용**
   - 깨지면: Nipo kernel이 권위 레코드를 변이하거나, Mucha prediction이 증거 tier로 승격되어 권위 체계가 붕괴한다.

## 5. 명명과 범위

- 통합된 thing의 이름은 **MUNI simulator**다.
- 범위는 **Mucha ↔ Nipo only**다.
- **OntologyLab은 별도 프로젝트**로 둔다.
- 배포는 **local-only single user**이며 SaaS가 아니다.
- 리포지토리는 **서로 별도 유지**하고, **local shell + shared contract package**로만 연결한다.
- 즉, monorepo merge는 하지 않는다.

## 6. Known limitations

현재 MUNI simulator가 제공하는 수집 데이터, 진단 후보, compound 후보와 dry-lab 점수는 합성 데이터다. 실제 chemical source adapter는 라이선스 결정을 내리지 못해 상태가 `UNKNOWN`인 `DEFERRED` 항목이며, 따라서 현재 실행에서는 `SKIPPED`된다. 또한 현 계획은 첫 실제 crop/pathogen validation target에 결속하는 것을 명시적으로 금지하므로, 합성 label을 실제 유기화합물 또는 실제 표적의 증거로 해석할 수 없다.

seed의 "multiple actual organic compounds" 조항을 실제로 만족하려면 후보 계약에 canonical structure(예: 정본 구조 표현과 그 내용 hash) 또는 pinned chemical registry reference를 담는 불변 compound identity가 추가되어야 한다. 동시에 라이선스가 확정된 실제 compound source를 활성화하고 그 identity와 provenance를 수집부터 review와 handoff까지 보존해야 한다.

현재 생성되는 어떤 artifact도 compound efficacy, crop protection, pathogen control 또는 wet-lab 성과를 주장하지 않는다. 점수와 순위는 합성 dry-lab 우선순위일 뿐이며, 효능 판단에는 별도의 실제 표적 선택, nipo 권위 사슬의 승인된 실험, 관측 artifact와 review가 필요하다.

운영 통합 상태도 제한 사항이다. 현재 MUNI simulator 실행은 Mucha 쪽에서만 이루어진다. Mucha+Nipo의 운영 통합은 구현되어 있지 않으며, 존재하는 것은 미래의 nipo-rooted 세션을 위한 전달 패키지(`handoff/nipo/` 아래의 계약 문서, 독립 validator, producer가 생성한 정본 fixture)뿐이다. MUNI boundary rule은 이 세션이 `nipo-science` 저장소를 수정하는 것을 금지하므로, nipo 쪽 결속 구현은 그 미래 세션의 몫으로 남는다. 이 문서와 전달 패키지의 어떤 부분도 달성된 통합으로 읽어서는 안 된다.

## 7. 포트폴리오 계층 승격 절차

이 문서는 현재 편의상 `mucha-science/docs/`에 있다. 하지만 계약 문서는 포트폴리오 계층(`MUNI/Ouroboros/documentation-governance`)에 있어야 한다.

사용자가 승격할 정확한 절차는 다음과 같다.

1. 이 파일을 검토해 최종 문안으로 확정한다.
2. `MUNI/Ouroboros/documentation-governance/` 아래의 포트폴리오 문서 트리에 동일 내용을 복사한다.
3. 포트폴리오 레이어의 문서 식별자와 링크를 갱신한다.
4. 이 저장소의 문서와 포트폴리오 문서가 같은 계약 내용을 가리키는지 확인한다.
5. 그 다음에만 계약을 상위 레이어의 정본으로 취급한다.

이 세션은 **MUNI boundary rule** 때문에 의도적으로 `MUNI/Ouroboros/` 디렉터리에 쓰지 않았다. 해당 경계는 계약 문서의 포트폴리오 승격을 사용자 주도 절차로 남기기 위한 것이다.
