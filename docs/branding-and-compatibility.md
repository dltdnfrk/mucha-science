# Mucha Science 브랜드와 호환성 경계

## 공개 브랜드

사용자가 보는 제품명은 **Mucha Science**로 통일한다.

- macOS 앱 번들: `Mucha Science.app`
- Tauri 제품명과 창 제목: `Mucha Science`
- 데스크톱 번들 식별자: `ai.mucha.science`
- 화면, 설치 안내, 제품 문서에서 사용하는 이름: `Mucha Science`

새로운 사용자 화면이나 제품 설명에 레거시 이름을 추가하지 않는다.

## 유지하는 호환성 네임스페이스

기존 설치와 자동화를 깨뜨릴 수 있는 아래 식별자는 당장 바꾸지 않는다.

- Python 배포판과 모듈: `muchanipo`
- CLI와 웹 실행 명령: `muchanipo`, `muchanipo-web`
- 환경 변수: `MUCHANIPO_*`, `VITE_MUCHANIPO_*`
- 브라우저 저장 키와 이벤트 별칭: `muchanipo:*`, `onMuchanipoEvent`
- scientific sidecar 바이너리와 프로토콜: `muchanipo-service`,
  `muchanipo.scientific-sidecar.v1`
- 소스 디렉터리와 Rust crate/bin 이름: `app/muchanipo-tauri`,
  `muchanipo-tauri`
- 레거시 네이티브 프로토타입 모듈 경로: `app/Muchanipo`
- 기존 런타임 설정·데이터 디렉터리:
  `~/Library/Application Support/ai.muchanipo.app/muchanipo`

이 이름들은 사용자에게 표시할 브랜드가 아니라 안정적인 내부 API다. 별도의 데이터
마이그레이션과 하위 호환 릴리스가 준비되기 전에는 제거하거나 묵시적으로 변경하지 않는다.

## 설치 마이그레이션

새 빌드는 `Mucha Science.app`으로 생성된다. 설치 스크립트는 새 번들을 검증해
`/Applications/Mucha Science.app`에 복사한 뒤 기존
`/Applications/Muchanipo.app` 번들만 제거한다. 사용자 설정과 연구 산출물은
레거시 호환성 디렉터리에 그대로 남는다.
