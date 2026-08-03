# Mucha Science Research Harness Architecture 설명

> 이 문서는 Mucha Science Research Harness 아키텍처 그림을 이해하기 쉽게 풀어쓴 초안입니다.
> 수정할 부분은 이 파일에 직접 메모하거나, 섹션별로 코멘트를 달아 업데이트합니다.

---

## 한 줄 요약

Mucha Science Research Harness는 **AI들이 마음대로 연구하는 구조**가 아니라, **하네스가 AI들을 단계별로 통제하고, 증거와 검증을 통과한 결과만 다음 단계로 넘기는 구조**입니다.

그림은 크게 세 영역으로 봅니다.

```text
왼쪽: 지금 어느 단계인가?               = Stage Gates
가운데: 그 단계에서 어떤 AI/adapter를 쓰나? = Adapter Registry
오른쪽: 그 결과가 믿을 만한지 무엇으로 증명하나? = Evidence Layer
```

---

## 1. 왼쪽: Stage Gates

왼쪽 파란 영역은 **작업 순서**입니다.

여기서 중요한 점은 agent가 알아서 다음 단계로 뛰는 것이 아니라, **하네스가 단계 문을 하나씩 열어준다**는 것입니다.

---

### 1. Idea Dump

현준이가 “이런 걸 만들고 싶어”라고 말한 raw idea를 잡는 단계입니다.

이 단계에서는 연구를 많이 하면 안 됩니다.

해야 할 일은 다음 정도입니다.

- raw idea 포획
- 배경 context 분리
- 제약 조건 기록
- 아직 모르는 점 표시
- 다음 단계로 넘길 handoff 생성

즉, 이 단계는 답을 내는 곳이 아니라 **아이디어를 안전하게 받는 곳**입니다.

---

### 2. Deep Interview

질문을 통해 연구 범위를 확정하는 단계입니다.

여기서 정해야 하는 것은 다음과 같습니다.

- 무엇을 조사할 것인가
- 누구를 위한 조사인가
- 어떤 결정을 돕기 위한 조사인가
- 어떤 출처를 믿을 것인가
- 무엇은 하지 않을 것인가
- 어떤 결과물이 필요한가
- 어떤 패턴은 거부할 것인가

이 단계가 중요한 이유는, 범위가 정해지지 않으면 agent들이 계속 옆길로 퍼지기 때문입니다.

예를 들어 “research 해줘”만 있으면 agent는 다음처럼 확장할 수 있습니다.

```text
공식 문서 조사
→ 로컬 repo 검색
→ 예전 repo 문맥 참조
→ 구현 제안
→ 리뷰 요청
→ 반복 실행
```

Deep Interview는 이런 확장을 막기 위해 **scope contract**를 만드는 단계입니다.

---

### 3. Deep Research Max

실제 조사 단계입니다.

하지만 여기서도 그냥 “research 해줘”가 아닙니다.

반드시 다음이 명시되어야 합니다.

```yaml
stage_id: deep_research_max
adapter_id: codex.omx.researcher
budget:
  turns_max: 8
  wall_clock_minutes: 25
stop_conditions:
  - versioned_sources_found
  - conflict_checked
```

즉, 누가 조사할지, 어느 단계에서 실행되는지, 얼마나 실행할지, 언제 멈출지를 정해야 합니다.

이 구조가 있어야 다음 문제를 막을 수 있습니다.

- Codex autoresearch가 자동으로 오래 도는 문제
- Kimi background task가 여러 개 생기는 문제
- Claude deep research가 내부 fanout을 마음대로 여는 문제
- local repo 조사와 외부 web research가 섞이는 문제
- 오래된 repo/context를 최신으로 착각하는 문제

---

### 4. Plannotator / HITL

사람이 중간에서 검토하는 단계입니다.

AI가 조사해온 결과를 보고 다음 중 하나를 결정합니다.

```text
approve
scoped changes
block
```

즉, AI 결과가 그럴듯해도 바로 다음 단계로 넘기지 않습니다.

현준이나 Plannotator가 다음을 확인합니다.

- 조사 범위가 맞는가
- 출처가 충분한가
- 주장과 근거가 연결되어 있는가
- 잘못된 repo/context가 섞이지 않았는가
- 다음 단계로 보내도 되는가

---

### 5-8. Ontology → Persona → Council → Report

이후 단계는 조사 결과를 제품화하는 구간입니다.

흐름은 다음과 같습니다.

```text
Ontology Extraction
→ Persona Generation
→ LLM Council
→ Final HTML/YAML Report
```

각 단계의 역할은 다음과 같습니다.

#### Ontology Extraction

조사 결과에서 개념 구조를 뽑습니다.

예:

- entities
- relations
- attributes
- uncertainty
- source_refs
- confidence

#### Persona Generation

조사 결과에 근거한 persona pool을 만듭니다.

예:

- persona_id
- role
- grounding_refs
- admission_status

#### LLM Council

persona 또는 council이 결과를 비판하고 종합합니다.

예:

- critique_trace
- disagreement
- chair_synthesis
- revise_or_noop_decision

#### Final HTML/YAML Report

최종 산출물을 만듭니다.

예:

- html_report
- yaml_report
- evidence_manifest
- readiness_verdict

---

## 2. 가운데: Adapter Registry

가운데 초록 영역은 단순한 AI 도구 목록이 아닙니다.

이 영역은 **역할이 제한된 adapter 목록**입니다.

하네스는 Claude, Codex, Kimi, OpenCode, Grok, Gemini를 다음처럼 보지 않습니다.

```text
Claude = 아무 연구나 잘하는 AI
Codex = 알아서 autoresearch 해주는 AI
Kimi = 큰 컨텍스트 AI
OpenCode = 구현해주는 AI
```

대신 이렇게 봅니다.

```text
Claude가 지금 맡을 수 있는 역할은 무엇인가?
Codex가 이 stage에서 써도 되는가?
Kimi는 budget 안에서만 움직이는가?
OpenCode는 지금 파일을 만져도 되는 단계인가?
Grok/Gemini는 review gate로만 쓰이는가?
```

---

### interview_scope_adapter

질문하고 범위를 잡는 역할입니다.

예:

```text
Claude/OMC deep interview
```

주요 목적:

- scope contract 생성
- ambiguity 감소
- non-goals 확정
- source policy 확정

---

### source_forward_engine_adapter

공식 문서, web source, versioned source를 찾는 역할입니다.

예:

```text
Codex/Kimi/Grok docs + web
```

주요 목적:

- 공식 문서 확인
- 버전 있는 자료 찾기
- conflict 확인
- source ledger 생성

---

### deep_synthesis_engine_adapter

여러 자료를 종합해서 큰 그림을 만드는 역할입니다.

예:

```text
Claude deep research / synthesis
```

주요 목적:

- 여러 source 통합
- claim 구조화
- research narrative 생성
- gap 정리

---

### local_corpus_adapter

외부 웹이 아니라 로컬 repo/docs 안에서만 찾는 역할입니다.

예:

```text
/Users/hyunjun/muchanipo-p5int 안의 문서, 테스트, 코드만 검색
```

이 adapter가 중요한 이유는 **외부 최신 자료 조사**와 **로컬 repo 문맥 조사**를 섞지 않기 위해서입니다.

---

### evidence_qa_gate

증거가 맞는지 검증하는 역할입니다.

예:

```text
OpenCode / Grok / Gemini가 claim 검토
```

주요 목적:

- 주장과 근거 연결 확인
- 출처 누락 확인
- unsupported claim 찾기
- stale context 감지

---

### persona_or_council_review

persona나 council이 비판/반론하는 역할입니다.

예:

```text
Nemotron-KR persona
LLM council
chair synthesis
```

주요 목적:

- persona 기반 critique
- disagreement 도출
- chair synthesis 작성
- revise/noop 판단

---

### artifact_writer / iteration_loop

최종 HTML/YAML을 쓰거나, 명시된 budget 안에서 반복 개선하는 역할입니다.

중요한 점은 **iteration_loop도 기본 금지**라는 것입니다.

반복 실행은 반드시 예산이 있어야 합니다.

예:

```yaml
iteration_loop:
  enabled: true
  max_rounds: 2
  wall_clock_minutes: 20
```

---

## 3. 오른쪽: Executable Evidence Layer

오른쪽 보라 영역은 **그 결과를 믿어도 되는지 확인하는 층**입니다.

AI가 “조사했습니다”, “검증했습니다”라고 말하는 것만으로는 부족합니다.

하네스는 실제로 다음을 요구합니다.

- 실행 명세
- raw output
- provenance
- source ledger
- execution log
- state values
- check results
- evidence manifest

---

### Run Envelope

실행 전에 필요한 실행 봉투입니다.

예:

```yaml
stage_id: deep_research_max
adapter_id: codex.omx.researcher
repo_root: /Users/hyunjun/muchanipo-p5int
budget:
  turns_max: 8
  wall_clock_minutes: 25
stop_conditions:
  - versioned_sources_found
  - conflict_checked
```

Run Envelope는 다음을 정합니다.

- 어느 stage인가
- 어떤 adapter인가
- 어느 repo/context인가
- 얼마나 실행할 것인가
- 언제 멈출 것인가

---

### Raw Output + Provenance

AI의 최종 요약만 저장하면 안 됩니다.

필요한 것은 다음입니다.

```text
raw_output_path
source ledger
manifest
provenance
```

즉, 최종 주장이 어디서 나왔는지 남겨야 합니다.

---

### Harness-owned Checks

하네스가 직접 검증하는 단계입니다.

예:

```yaml
check_id: repo_root_check
kind: command
target: git rev-parse --show-toplevel
assertion: equals
expected: /Users/hyunjun/muchanipo-p5int
```

이 구조가 있으면 agent가 말로 “맞습니다”라고 하는 것이 아니라, 하네스가 직접 command/test/state assertion으로 확인할 수 있습니다.

이번 wrong repo 문제도 이 gate가 있으면 막을 수 있습니다.

예:

```text
expected: /Users/hyunjun/muchanipo-p5int
actual:   /Users/hyunjun/Documents/muchanipo
result:   BLOCKED
```

---

### Evidence Matrix

claim과 근거를 연결한 표입니다.

예:

```yaml
claim: "Codex autoresearch must not trigger from bare research keyword"
evidence_refs:
  - config/research_harness_registry.yaml
  - docs/research-harness/6-stage-cli-roles.md
confidence: high
gaps: []
```

즉, 최종 보고서의 중요한 말은 모두 다음 중 하나로 분류되어야 합니다.

- 근거 있음
- 근거 부족
- 충돌 있음
- 아직 단서일 뿐임

---

### Decision Gate

최종 판단 단계입니다.

가능한 결과는 다음입니다.

```text
PASS
BLOCKED
UNVERIFIED_LEAD
```

의미는 다음과 같습니다.

- `PASS`: 증거가 있고 검증을 통과함
- `BLOCKED`: 필수 조건이 빠졌거나 검증 실패
- `UNVERIFIED_LEAD`: 흥미로운 단서지만 아직 사실로 승격 금지

AI가 자신 있게 말해도 근거가 없으면 `UNVERIFIED_LEAD`로 남겨야 합니다.

---

### Final Artifacts

마지막 산출물입니다.

예:

```text
HTML report
YAML report
evidence manifest
readiness verdict
```

사람이 보는 예쁜 보고서와, 시스템이 다시 읽을 수 있는 YAML이 같이 나오는 구조입니다.

---

## 4. Core Rule

그림 위쪽 노란 박스의 핵심 규칙입니다.

```text
Harness chooses adapters by stage;
adapter never chooses product flow.
```

뜻은 다음과 같습니다.

**AI가 “제가 보기엔 다음엔 이걸 해야 합니다” 하고 제품 흐름을 바꾸면 안 되고, 하네스가 지금 단계에 맞는 adapter만 호출해야 합니다.**

---

### 잘못된 방식

```text
현준: 이거 조사해줘
Codex: autoresearch 시작
→ local repo 뒤짐
→ 예전 repo 문맥 참조
→ Tauri/React/Swift 리뷰
```

이 방식은 adapter가 product flow를 결정한 것입니다.

---

### 올바른 방식

```yaml
stage_id: deep_research_max
adapter_id: codex.omx.researcher
repo_root: /Users/hyunjun/muchanipo-p5int
context_freshness: latest_only
budget:
  turns_max: 8
  wall_clock_minutes: 25
stop_conditions:
  - versioned_sources_found
  - conflict_checked
```

이 방식은 하네스가 먼저 울타리를 치고, adapter는 그 안에서만 움직입니다.

---

## 5. Freshness / Repo Guard

그림 아래 빨간 박스는 보강 포인트입니다.

```text
verify repo root + latest task context before invoking any adapter
```

즉, adapter 실행 전에 반드시 다음을 확인해야 합니다.

```bash
pwd
git rev-parse --show-toplevel
git status --short
```

기대값은 다음입니다.

```text
/Users/hyunjun/muchanipo-p5int
```

만약 실제값이 다음처럼 나오면 즉시 중단해야 합니다.

```text
/Users/hyunjun/Documents/muchanipo
```

이 guard가 있으면 오래된 repo/context가 다시 끼어드는 것을 막을 수 있습니다.

---

## 6. 비유

이 구조는 회사로 비유하면 다음과 같습니다.

```text
왼쪽 Stage Gate      = 프로젝트 매니저
가운데 Adapter Registry = 전문가 명단
오른쪽 Evidence Layer   = 감사/검수팀
```

프로젝트 매니저가 말합니다.

```text
지금은 조사 단계야.
Codex는 공식 문서만 찾아.
Claude는 종합만 해.
OpenCode는 아직 파일 만지지 마.
Kimi는 budget 안에서만 보조해.
```

그 다음 감사/검수팀이 확인합니다.

```text
근거 있어?
로그 있어?
raw output 있어?
repo 경로 맞아?
검증 command 통과했어?
```

다 통과해야 최종 보고서가 나옵니다.

---

## 7. 이 그림에서 기억할 핵심

이 그림에서 하나만 기억하면 됩니다.

**왼쪽이 AI에게 “지금 할 일”을 정하고, 가운데가 “쓸 수 있는 역할”을 제한하고, 오른쪽이 “진짜 믿어도 되는 결과인지”를 검증합니다.**

그래서 Mucha Science Research Harness는 단순히 AI 여러 개를 붙이는 시스템이 아닙니다.

**AI가 멋대로 퍼지지 못하게 하고, 근거 있는 결과만 다음 단계로 넘기는 연구 실행 엔진**입니다.

---

## 8. 수정 메모

현준이가 수정하고 싶은 부분을 아래에 적으면 됩니다.

```markdown
## 수정 요청

-
-
-
```
