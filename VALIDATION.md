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

## v0.5 기사 검토 UI·출력 및 회차 데이터 회귀 검증

- `PYTHONPATH=. python -m pytest -q tests` → **38개 통과** (로컬 소스, 테스트용 SQLite).
- `PYTHONPATH=. python tests/browser_review_workbench.py` → 208건 모의 기사(언론 171/식약처 37) 탭, 2페이지 13건 다중 선택, 수록·상세 편집, 데스크톱/모바일 통과.
- `PYTHONPATH=. python tests/browser_collection_smoke.py` → 수집 UI 토글 및 0건·에러 로그 모의 테스트 통과.
- `PYTHONPATH=. python tests/browser_workspace_smoke.py` → 기존 170건 화면 전환/분류 필터 테스트 통과.
- `PYTHONPATH=. python tests/browser_smoke.py` → 7건 역사적 fixture로 한 건의 명시적 TOP 설정, 모바일/데스크톱 통과.
- `node --check` → 편집기 JavaScript 구문 검사 통과.
- 포함: 회차별 수집 이력 분리, 날짜 미확인 전역 편입 방지 및 이번 회차 출처 기반 편입, GPT JSON 회차/해시 확인, 선택 수록, 승인 전 제안 비출력, 식약처 섹션 간 중복 표시 제거, 독자용 미리보기.
- 미검증: 실제 Windows DB 208건, 식약처/언론 외부 네트워크, GPT 유료 API 실호출, 실제 이메일 클라이언트/운영 발송.

## v0.6 — 추천 그룹 CRUD 및 반응형 상세 편집
- `python -m pytest -q`: **33개 통과** (로컬 구성; `tests/test_review_groups_v06.py` 4개 신규 테스트 포함).
- `python tests/browser_review_workbench.py`: 208건 모의 기사 대기열/일괄 수록/원문·GPT 제안 분리, 974px·390px 슬라이드 상세 편집 패널, 설정 그룹 추가·수정·삭제 및 재분류 호출 확인.
- `node --check editor.js`: 편집 UI JavaScript 문법 통과(로컬 추출 파일).
- 새 SQLite 그룹 설정은 신규 DB와 재시작 시뮬레이션으로 테스트. 기존 수동 수록·섹션 변경 보존 검사.
- 미검증: 사용자의 Windows DB 실수집 208건, OpenAI API 실호출, 브라우저→실제 HTTP 서버의 전체 UI E2E, 이메일 클라이언트 Outlook 렌더링.

## v0.7 검증

- `PYTHONPATH=. pytest -q`: 자동 테스트 42개 통과 (기존 33개 + 신규 9개).
- `.env`: 프로젝트 루트 로딩·운영체제 환경변수 우선·Git 무시 규칙 확인. 실제 OpenAI 계정 실호출은 미실행.
- 도서관: SQLite에서 확정/초안 분리, 31개 회차 모의 12개씩 페이지 이동, 상태·제목 검색, 확정본 스냅샷 불변, HTML/다운로드 API, 활성 회차 불변성 확인.
- 기사: 긴 링크 텍스트의 본문 혼입 방지, 구조화 제목·날짜 우선, 제목 미검증 자동 추천 배제, 원본 링크 텍스트 보존, 중복 링크 품질 우선 선택 확인.
- 브라우저: 데스크톱 도서관·검색·팝업·기사 카드 전환·이전/다음·상세 패널, 모바일 배치 모의 테스트 확인. 기존 수집·기사 검토·회차 전환·170/208건 회귀 화면 테스트 유지.
- 실제 운영 Windows DB의 원본 기사 검증, 사이트별 누락/원문 재확인, Outlook 등 메일 클라이언트 테스트와 OpenAI API 비용/품질 검증은 미실행.

## v0.8: Outlook 뉴스카드형 템플릿 선택
- 로컬 조합본에서 `python -m pytest -q`: 기존 42개 + 신규 템플릿/HTTP 4개, 총 46개 통과.
- `classic` 기본값을 유지한 기존 892호 렌더링, 신규 템플릿 2의 HTML 테이블·인라인 스타일, 회차별 선택 저장, 미리보기·다운로드·확정 스냅샷 및 확정 후 변경 차단 검증.
- 크로미움 `page.set_content()`으로 샘플 이메일 HTML 정적 렌더링 확인. 실제 Outlook 데스크톱 앱 및 이메일 발송 테스트는 수행하지 않음.


## v0.9 검증 상태
- TOP 출력 제한(두 템플릿), 순서 변경, 확정 스냅샷, 반복 저장/편집 보존 회귀 테스트를 `tests/test_workflow_v09.py`에 추가했다.
- 이 변경의 pytest 및 실제 브라우저 검증은 아직 실행하지 않았다. 이전 버전의 통과 기록을 v0.9 결과로 간주하지 않는다.
- 사용자 Windows DB의 기존 중복 데이터는 접근하지 못해 미검증이며 자동 삭제하지 않았다.

## v0.11 verification scope
- `tests/test_template_v011.py`: company selection and ordering, repeat CSV events, period exclusion, two template outputs, approval slots, embedded MVP image hash, configured contact, frozen HTML.
- `tests/browser_template_v011.py`: live localhost application through Playwright, company registration/selection, TOP preview, CSV upload, brand and publication settings, confirmation immutability.
- Existing collection smoke now opens advanced settings before changing RSS; browser suite runs all files and reports combined failure status.
- MVP banner file bytes checked against Git blob SHA `321c4b39bee0bf01dbec2539d7bef91064fe379a`. Actual Windows Outlook and live external data completeness remain outside automated verification.
- The CI run associated with the final PR head is authoritative; this section lists coverage, not a test pass claim.

## v0.12 validation
- 2026-11-16~22 의약품안전나라 공개 GET 날짜 검색 화면 확인: 임상시험 34, 치료목적 4, 품목허가공고 23건. 임상시험 및 품목허가 2페이지 순번 11 확인. 이 숫자는 조회 화면 총 건수이며 품목허가의 취소/취하 건은 허가 수록 수와 다를 수 있다.
- `fixtures/approval_*_20261116_page1.html`: 공식 공개 페이지의 날짜 입력, 총 건수, 목록 표를 추출한 최소 회귀 자료(전체 페이지/완전 수집 데이터 아님).
- `tests/test_approval_live_v012.py`: 실제 공개 페이지 구조, 날짜 확인, 페이지 순번, 건수 불일치, 저장 반복 및 수집 방식 혼합 방지.
- `tests/browser_template_v011.py`: 실제 localhost UI, 모의 공식 데이터 응답, 드롭존, 현재 페이지/카드 선택, 확정 회차 잠금, 샘플 연락처, HD 이미지, 변경된 브랜드 설정 및 확정 HTML 보존.
- 상단 Git blob SHA `30db07ef86f7f63b471e4b9f85171cabf6c3acd1`, 하단 `70153575f3eec5dc73261ecd89be0dc5bed40171`; 원본 크롭 이미지와 일치 확인.
- UI CSS 참고: IBM Carbon Design System Forms, Checkbox, File uploader; 로컬 CSS로 구현. 실사용 Windows 네트워크 및 Outlook 데이터 URI 호환성은 별도 검증 대상.

## v0.13 source quality verification
- MedicalTimes observed public markup: article.newsList_cont, .headLine, .newsList_cont_date, detail .viewTitle_wrap #NewsTitle and .date_info span with 발행날짜 label. Example article ID 1172075, publication date 2026-11-23; this date is outside the 2026-11-16~22 edition period.
- Tests model observed DOM with synthetic body content; verify missing fields, noisy legacy metadata, duplicate sidebars, explicit dates, version retention, stale AI proposal invalidation, human decisions and frozen HTML/snapshot preservation. Browser integration uses a mocked article metadata response, not live access from Windows.
- Footer table rows and image position are tested in Chromium; actual Outlook rendering remains unverified.

## v0.14 maintenance and Windows packaging
- Editor markup and JavaScript separated: `editor.html`, `assets/editor.js`, `assets/editor.css`; no frontend build or package manager required. Existing browser fixtures compose the same source with `meditip/ui_assets.py`; HTTP integration uses the actual static asset route. Token remains in HTML only.
- Browser integration checks company ordering synchronizes with queue, site preferences survive reload without retaining media-rights acknowledgement, all approval types execute independently (mocked partial failure and CSV conflict), and stable template IDs.
- Windows package workflow builds a one-file x64 executable using PyInstaller, then launches with Python removed from PATH and a synthetic external .env. Smoke checks startup, editor assets, local data creation, preview, and no secret in settings response. Artifact contains executable, example env, and manual, not the real database or API key. Actual target PC security policy, live API calls and Outlook are not covered.

## v0.14 original link resolution
- Official public GET form and result checked for 2026-11-20: clinical ST2/searchKeyword=SRP-9001; treatment prductName=티쎈트릭(RO554-1267), applyEntpName=서울대학교병원; drug sItemName=프레비미스미니정(레테르모비르)20밀리그램, sEntpName=한국엠에스디(주). Each observed result showed 1 record with matching date and product. This is evidence of supported query parameters, not a guarantee for every record.
- `source_links.py` centralizes URL generation. Unit and browser tests cover direct URL priority, search fallback, URL encoding, same output in both templates, unchanged stored identities, and prior frozen HTML behavior. Live external results may change after publication.

## v0.14 managed user files
- ManagedFiles validates directory containment, normalizes names and uses content-derived versions with atomic writes. Exact bytes of imported CSV and JSON are kept, legacy brand images are copied from the DB, and explicit exports are mirrored to persistent files without changing the browser download flow.
- Unit tests cover path escape rejection, filename collisions, repeat content and version retention. HTTP/browser tests cover original import bytes, duplicate export behavior, actual folder path and confirmed HTML. Windows package smoke checks folders and an actual HTML export under external --data-dir, not the temporary executable extraction folder.
- DB remains the authoritative editorial/brand state. Files are retained copies; historical imports that were never stored cannot be reconstructed. A failed import can leave its input file in the archive. No automatic cleanup or migration of arbitrary old files.

## v0.14 operator polish
- Resolve rank row flex/grid conflict and normalize spacing, buttons, status chip and file drop geometry. Browser test checks actual computed styles, rather than only presence of DOM nodes.
- Default contacts are independently persisted in newsletter_branding, with regression coverage for unchanged active publishing settings and reopen. Explorer uses explicit executable; actual visible Explorer window in end user's desktop session is not verified by headless CI. Copy path fallback provided.
- Edition creation client-side input validation and inline response message; screenshot alone does not identify the specific historical HTTP 400 cause. Preview sandbox is intentionally retained; browser console's blocked-script message does not establish a functional defect.
