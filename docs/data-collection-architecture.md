# Mucha Science 데이터 수집 아키텍처

Mucha Science는 LLM 한 번의 답변을 곧바로 “근거”로 취급하지 않는다. 한 연구 실행은 세 가지 독립 수집 경로를 사용하고, 모든 결과를 공통 evidence 계약으로 정규화한 뒤 반증 검색과 준비도 판정을 거친다.

## 1. 세 가지 수집 경로

### Provider-native citation search

Anthropic과 Gemini가 제공하는 검색 도구를 API로 호출한다. 응답 본문이 아니라 provider가 반환한 citation/grounding 메타데이터에 연결된 HTTP(S) URL만 받는다. 인용이 없는 모델 문장, 로컬 CLI 자유 텍스트, 사용자정보가 포함된 URL은 버린다.

구현: `src/research/provider_grounded_search.py`

### Academic APIs

사용자가 활성화한 출처만 정해진 순서로 호출한다.

1. OpenAlex
2. Crossref
3. Semantic Scholar
4. PubMed
5. arXiv
6. CORE
7. Unpaywall

각 출처의 결과는 `success`, `empty`, `failed` 중 하나의 독립 시도로 기록한다. 일부 출처가 실패해도 다른 출처 결과는 유지하며, 실패를 “검색 결과 없음”으로 바꾸지 않는다.

구현: `src/research/academic/sync_search.py`, `src/research/academic/`

### Run-owned skill artifacts

분석 스킬이 만든 JSONL 산출물은 현재 `app_run_id`와 generation의 `staging` 디렉토리 아래에 있을 때만 읽는다. 스킬 이름·버전·입력 및 출력 SHA-256·출처 URL을 검증하고 크기와 레코드 수를 제한한다. 스킬 산출물은 파생 자료이므로 기본 출처 등급 C이며, 독립 원문을 대신하지 않는다.

구현: `src/research/skill_artifacts.py`

## 2. 병합과 검증

수집된 후보에는 출처 종류, 정규 URL, DOI/PMID 등 식별자, 제목, 초록, provenance가 붙는다. canonical identity로 중복을 제거하고 출처 품질을 보존한 뒤 다음 순서로 처리한다.

1. 검색 후보 정규화와 안전한 locator 검증
2. 출처 등급 및 관련성 계산
3. 주장과 근거의 `supports_claim`, `refutes_claim`, `mixed`, `inconclusive` 관계 유지
4. 핵심 주장마다 최대 한 번의 제한된 반증 검색
5. 새 출처·새 주장·새 모순이 없는 완료 배치인지 판정
6. 미평가 주장, 출처 실패, 모순, 예산 소진이 있으면 `needs_review` 또는 `incomplete`로 보류

RRF 병합은 `k=60`을 유지한다. 모델 confidence의 평균이나 문자열 유사도만으로 과학적 사실을 확정하지 않는다.

핵심 구현: `src/research/runner.py`, `src/research/citation_resolver.py`, `src/research/refutation_loop.py`, `src/research/source_decision_ledger.py`, `src/research/readiness.py`

## 3. 자격증명과 실행 소유권

- 웹 설정의 provider/API 키는 `sessionStorage`에만 둔다.
- 런타임은 허용 목록의 변수만 현재 실행 child process에 전달한다.
- 스킬 산출물과 최종 보고서는 `<MUCHANIPO_HOME>/runs/<app_run_id>/generation-<N>/`에 귀속된다.
- 실행 중에는 `staging/`만 쓰고, 성공한 활성 generation만 원자적으로 `final/`로 승격한다.
- 취소된 generation의 늦은 완료 이벤트와 산출물은 채택하지 않는다.
- browser-facing 오류에는 원문 예외·키·URL 자격증명을 넣지 않는다.

## 4. 현재 지원 경계

Springer, Elsevier, OASIS, 임의 커스텀 connector는 아직 실행 가능한 출처가 아니다. Unpaywall은 contact email이 필요하고, OpenAlex 등 공개 API는 rate limit으로 부분 실패할 수 있다. 이 경우 UI와 보고서에 출처별 실패를 그대로 남기며, 다른 출처의 성공과 합쳐 “전체 성공”으로 숨기지 않는다.
