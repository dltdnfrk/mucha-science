# nipo handoff package

이 디렉터리는 MUNI simulator의 건식 산출물을 미래의 **nipo-rooted 세션**에 안전하게 넘기기 위한 자기완결 전달 패키지다.

MUNI 포트폴리오 경계 규칙상 한 프로젝트에 rooted된 세션은 다른 프로젝트의 파일을 수정하지 않는다. 따라서 이 작업은 `nipo-science`에 계약이나 코드를 쓰지 않고, nipo 세션이 나중에 소비할 계약·실제 픽스처·독립 validator를 `muni-lab/handoff/nipo/`에 둔다. 두 코드베이스를 합치는 패키지가 아니다.

## nipo 세션의 소비 순서

1. `CONTRACT.md`를 읽고 `ActionPlan` 생성 시점의 결속 규칙과 권위 경계를 확인한다.
2. 반입할 JSON을 수정하지 않은 상태에서 `validate_handoff.py`로 검증한다. 실패하면 ActionPlan을 만들지 않고 모든 필드 오류를 원 송신 측에 돌려준다.
3. 검증된 JSON 전체 바이트의 SHA-256을 계산하고 `handoff.handoff_id`와 함께 외부 handoff 참조로 고정한다.
4. `candidate_set.items[].candidate_content_hash`를 각 ActionPlan 대상의 불변 prediction/candidate 참조로 고정한다.
5. 후보의 점수·처분·근거는 planning basis로만 보존한다. MUNI 후보에 evidence tier를 부여하지 않는다.
6. 사람이 공유 증거 등급 어휘에서 목표 습식 등급을 선택하고 nipo 권위 surface에서 ActionPlan을 생성한 뒤 별도로 승인한다. MUNI review는 nipo approval을 대신하지 않는다.
7. 이후 `Run → Execution → ArtifactVersion → Review → Export`를 nipo 권위 사슬대로 진행한다. kernel이나 MUNI가 이 레코드를 변이하게 하지 않는다.

## validator 실행

저장소 루트에서:

```sh
.venv/bin/python handoff/nipo/validate_handoff.py \
  handoff/nipo/fixtures/handoff-muni_review_7f61a32458b8c6bd4c2700e810287dbd.json
```

성공하면 `VALID <path>`를 출력하고 종료 코드 0을 반환한다. malformed JSON, 필수 필드 누락, 타입·식별자·참조 불일치, 계약 블록에 선언되지 않은 필드, 평면 후보 필드와 해시된 `candidate_content`의 불일치, `finished_at`이 `started_at`보다 빠른 실행 시각 역전, 비어 있는 provenance/lineage, 면책문 삭제·변경, 효능 주장 어휘가 있으면 필드별 오류를 출력하고 0이 아닌 코드로 종료한다.

validator는 Python 표준 라이브러리만 사용하고 `src/`를 import하지 않는다. 따라서 `muni-lab`이 import 경로에 없는 작업 디렉터리에서도 절대 경로로 실행할 수 있다.

`fixtures/`의 JSON과 Markdown 쌍은 `src/muni/handoff.py`를 합성 `cropA`/`pathogenX` Study에 대해 collection → diagnostic discovery → approved review → `create_handoff` 순서로 실제 실행해 생성했다. JSON은 손으로 작성하지 않았다.
