# MVP v0.1 확인 기록 (2026-11-23)

## 직접 실행하여 확인한 것
- `python main.py init`, `seed-demo`: SQLite 생성 및 **이전 2차 테스트 7건** 가져오기 성공
- `python main.py export-html demo-2026-11-16-22`: 892호 기반 HTML 생성 성공
- `python main.py export-ai demo-2026-11-16-22`: 외부 ChatGPT 가공 입력 JSON 생성 성공
- `pytest tests/test_mvp.py`: 11개 통과. TOP 2건/6건/0건, 필수 상세 분리, 사용자 요약 우선, 날짜 파서, RSS/목록 파서, 변경 버전, 임상 CSV 표, XSS 텍스트 이스케이프 포함
- 실제 로컬 HTTP 서버 API: GET 200, 잘못된 편집 토큰 403, 올바른 토큰으로 편집 설정 저장 성공, HTML 다운로드 200
- Chromium 화면: 가상 API로 렌더링한 편집기 화면 7건/기본 4건/체크 변경 및 데스크톱·모바일 화면 확인. **브라우저가 실제 localhost 접속을 차단하여 UI→SQLite 전체 브라우저 E2E는 미실행**
- 892호 HTML 렌더링 스크린샷: 7개 목록 링크와 가변 TOP 4개 표시 확인

## 실제 실패 / 아직 미검증
- 식약처 RSS 실수집: 이 실행 컨테이너에서 DNS 조회 실패. 수집기는 `failed`로 기록했고 **수집 0건이라고 단정하지 않았음**.
- 식약처 8개 게시판, 언론사 5곳 전수 수집: 실증 미완료; 보드/목록 어댑터는 `partial`로만 기록하도록 설계됨
- 의약품안전나라 공식 API 및 엑셀 자동 다운로드: 미구현. 사용자 제공 CSV 가져오기만 테스트함
- 실제 회사 홍보물/로고·배너 재연결, 회사정보 확인, DirectSend 클라이언트 테스트: 미진행
- ChatGPT 개인 계정 AI 자동 호출: 미구현. JSON 내보내기/가져오기 연계만 구현

이번 결과물은 **실행 가능한 로컬 MVP**이지, 뉴스레터 자동 수집·발행 시스템 전체의 운영 검증 완료본이 아니다.

## v0.2 수집 버튼 보완 — 로컬 검증
- `python -m pytest -q`: 14개 통과 (기존 11 + 신규 3).
- 오프라인 수집 대체 함수로 서버의 사이트 목록 API, 수집 작업 시작, 상태 조회, SQLite 수집 이력, 회차 자동 추천, HTML 다운로드를 검증함. **실제 공식 사이트 접속 검증이 아님**.
- 잘못된 토큰, 지정되지 않은 출처, 회차 기간 불일치, 언론사 이용조건 미확인을 API에서 거부하는 것을 확인함.
- `node --check`로 인라인 편집 화면 스크립트 문법 확인.
- `python tests/browser_collection_smoke.py`: Chromium의 네트워크 없는 화면 테스트에서 7개 후보, 식약처 8개 선택, 수집 버튼, 부분 수집 상태, 데스크톱·모바일 렌더링 확인. 가짜 수집 API를 사용한 화면 검증임.
- 이 실행 환경에서 Chromium의 `localhost` 접속이 `ERR_BLOCKED_BY_ADMINISTRATOR`로 차단되어 **실제 브라우저→실제 서버→SQLite의 완전한 E2E는 수행하지 못함**. 로컬 HTTP API 자체는 별도 테스트함.
- 외부 DNS가 차단되어 식약처·언론사의 실제 수집 성공 및 누락률은 여전히 **미검증**.

## v0.2.1 HTTP 400 오류 안내 보완 — 로컬 검증
- 실제 사용자가 보고한 `/api/collect` 400 스크린샷만으로 정확한 거부 조건을 특정할 수 없으므로 서버 응답의 오류 본문을 확인해야 함.
- 회차 기간 불일치, 선택한 전체 식약처의 RSS 미지원 게시판 포함, 언론사 이용조건 미확인, 범위 밖 페이지 수를 웹 화면에서 **사전 안내**하고 요청하지 않음.
- 서버의 회차 기간 불일치 오류에 입력/회차 날짜를 함께 명시함.
- 수집 거부 메시지가 `/api/collection` 주기 조회(1.8초)에 덮어써지지 않게 유지함.
- `python -m pytest -q`: 14개 통과.
- `python tests/browser_collection_smoke.py`: 가상 API에서 기간 불일치와 RSS 미지원 선택은 POST 없이 안내됨, 주기 조회 후에도 오류가 유지됨, 유효한 요청은 정상 진행됨.
- `node --check`: 편집 UI 인라인 JS 문법 통과.
- 실제 Windows 사용 환경에서 오류가 해소되었는지 및 외부 사이트 수집 자체의 성공 여부는 아직 미확인.

## v0.3 식약처 기간 수집 및 RSS 교차검증 (오프라인 검증)

- 공인 규칙 변경 없이 `srchFr`/`srchTo`/`page` 요청 구성, 동일 게시판·seq 중복 식별, 이전 기간 제외를 확인.
- RSS와 게시판의 부분 교집합 비교: RSS에만 존재하는 ID 차이를 명시하며 `complete` 자동 판정 없음.
- RSS 실패 시 게시판 원본 데이터 보존, 미설정 RSS는 `not_configured` 상태 유지.
- 수집 테스트는 FakeSession으로 만든 고정 HTML/RSS에서 실시. **실제 MFDS 서버 요청 및 8개 게시판 완전성 검증 미수행**.
- 신규 테스트 4개와 기존 17개: 총 **21개 통과** (`python -m pytest -q`).

## v0.3: 언론기사 추천·분류·일괄 편집 검증

- 수정 로컬 소스에서 `python -m pytest -q tests/test_mvp.py tests/test_collection_ui.py tests/test_editorial_bulk.py tests/test_editorial_http.py`: **20개 통과**. 이후 브랜치에 추가된 `tests/test_mfds_collect.py`는 이 실행에서 미포함.
- 분야 분류 5개 예시, GLP-1 시장 분류 오류 발견·수정·재검증; 추천 일괄 처리 및 수동 선택/분류 보호, SQLite 마이그레이션, GPT JSON 가져오기 API까지 검증.
- 170건 오프라인 브라우저 모의 데이터로 5분야 집계·필터·추천 일괄 선택 작동 확인. 실제 로컬 HTTP 브라우저 이동은 실행 환경 차단, 별도 HTTP API 검증 수행.
- 사용자 Windows DB의 실제 170건과 실사이트 원문·수집 완전성은 검증하지 않음.


## v0.4 작업 검증 (2026-11-23)

- 로컬 수정본 기반 `python -m pytest -q tests/test_issue_workflow.py tests/test_http_workflow.py tests/test_mvp.py tests/test_editorial_bulk.py tests/test_collection_ui.py tests/test_editorial_http.py tests/test_previous_fixes.py`: **30개 통과**. 앞선 브랜치의 기존 MFDS 수집 테스트(`tests/test_mfds_collect.py`)는 해당 로컬 실행에 포함되지 않아 브랜치 전체 통과 판정은 아님.
- 서버 실 HTTP 테스트: 주차/회차 조회, 선택·확정, 확정 후 편집 거부, 원본 JSON, final HTML, 같은 주차 다른 ID 회차 생성.
- 단위 테스트: ISO 경계, 수록 기사 없을 때 확정 거부, 서로 다른 회차번호의 독립 확정, 확정 HTML 불변 및 SHA 검증, API 미설정 동작, OpenAI Responses API **모의 응답** 검증.
- 기존 중복 URL 출력 방지와 미분류 기사 수록 보완에 대한 모의 회귀 테스트 3개 통과. SQLite 기존 원본과 수동 편집 보존.
- Chromium 단독 모의 브라우저: 170건 중 한 페이지 12건 표시, 분야 필터, 메뉴 전환, 환경설정, 미리보기 영역, 모바일·데스크톱 렌더링. 수집 화면 모의 테스트도 통과. JS 문법 `node --check` 통과.
- 실제 Chromium → localhost 페이지 이동은 실행 환경 관리자 정책으로 차단되어 HTTP와 브라우저 모의 테스트로 나눠 수행. OpenAI 실호출, 사용자 Windows DB의 170건 정확도, 전체 MFDS/언론 사이트 수집 완전성, 이메일 클라이언트 발송 품질은 **미검증**.

## 수집 화면 사용성 개선 v0.4.1
- `python -m pytest -q`: 기존 백엔드 자동 테스트 30건 통과 (로컬 개발 환경).
- `tests/browser_collection_smoke.py`: 회차 선택 숨김, 기간·ID·제목·생성 버튼 통합, 식약처/언론 토글, 부분 수집 상세 로그 숨김, 0건·HTTP 오류 표시, 스크롤 CSS 확인 (모의 fetch).
- `tests/browser_workspace_smoke.py`: 170건 모의 데이터, 12건 페이징, 업무 화면 이동, 주요 UI JS 오류 없음.
- `tests/browser_smoke.py`: 별도 임시 SQLite·로컬 서버 기동 후 7건 기사 TOP 편집 조작 확인.
- 실제 Windows 데이터·외부 사이트 접속은 이 UI 변경 검증에 사용하지 않음.
## v0.5 관련 검토·검증
- 로컬 수정본에서 38개 pytest 통과 (기존+신규). 208건 모의 기사 기준 추천/추가 검토/그 외/수록 목록, 13건 다중 페이지 선택 UI 조작, 모바일 렌더링 검증.
- 식약처 중복 링크, 확정 스냅샷, 회차별 수집 이력, 원본 날짜 미확인, 명시적 GPT 적용/편집 보존을 재현 데이터로 검사.
- GitHub에서는 기존 최신 MFDS RSS 교차검증 코드를 덮어쓰지 않고 관련 수집 인자만 확장하여 반영.
- 사용자 Windows 데이터와 실제 외부 수집·발송은 검증 대상에 미포함.
