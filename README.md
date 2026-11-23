# MEDiTIP 뉴스레터 독립형 MVP (v0.1)

## 실제 구현 범위

- 별도 AI 없이 실행되는 **공개 RSS/목록 메타데이터 수집 어댑터**, 원본·변경 버전·실행 상태를 저장하는 SQLite
- 기존 892호 메일을 기반으로 한 HTML 템플릿 재사용 (로고·배너는 재연결 대기 표시)
- **동적 TOP 뉴스 건수**, 섹션별 목록, 수록 여부·순위·제목·요약을 수정하고 SQLite에 저장하는 로컬 웹 UI
- 규칙 기반 1차 추천(명시적으로 AI와 구분), 외부 ChatGPT가 분석한 JSON 제안 가져오기
- 이전 2차 테스트(7건) JSON으로 검증 가능한 재현용 샘플
- 발송 기능 **없음**. 원본 뉴스레터의 개인정보·개인화 추적링크는 포함하지 않음.

## Windows 실행

Python 3.10 이상 설치 후, 폴더에서 `start_windows.cmd` 실행. 설치가 끝나면 브라우저에 **http://127.0.0.1:8765/** 를 연다. 명령행으로 직접 하려면:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py init
.\.venv\Scripts\python.exe main.py seed-demo
.\.venv\Scripts\python.exe main.py serve
```

샘플 대신 새 회차를 만들 수 있다:

```powershell
.\.venv\Scripts\python.exe main.py edition w2026-48 --start 2026-11-23 --end 2026-11-29 --target 4
.\.venv\Scripts\python.exe main.py prepare w2026-48
.\.venv\Scripts\python.exe main.py serve --edition w2026-48
```

## 출처 수집 실행

`config/sources.yaml`에서 각 사이트·섹션·RSS 후보를 관리한다. `config/editorial.yaml`에서 섹션별 규칙 점수와 관심 키워드를 변경하고 `prepare`로 점수를 갱신한다. 기존 담당자 선택은 덮어쓰지 않는다. **수집 전 해당 사이트 이용조건과 접근 가능성을 확인**한다. 다음은 실제 시도하는 명령이며 테스트 환경에서는 외부 DNS 연결이 제한돼 실행 성공하지 못했다.

```powershell
.\.venv\Scripts\python.exe main.py collect --source press --method rss --start 2026-11-16 --end 2026-11-22
.\.venv\Scripts\python.exe main.py collect --source press --method board --start 2026-11-16 --end 2026-11-22 --max-pages 3
.\.venv\Scripts\python.exe main.py prepare w2026-48
```

RSS는 **신규 후보 발견**, 공개 목록은 **부분 수집**만 구현한 상태이며, 8개 식약처 게시판의 페이지네이션/목록 구조는 실제 사이트에서 실증하지 않았으므로 자동으로 `complete` 처리하지 않는다. 언론사도 첫 페이지 링크 메타데이터를 대상으로 하며 기사 원문 대량 수집은 하지 않는다.

**미구현 / 추가 실증 필요:** 의약품안전나라 최초·변경승인과 치료목적 사용승인의 모든 이벤트 공식 API/엑셀 커버리지, 의약품 주간 허가 데이터 표, 각 게시판 완전성 검사, 원문 첨부 파싱, 다이렉트센드 발송, ChatGPT 개인 계정의 로컬 DB 자동 직접 호출. 관련 사이트별 수집 전략은 `config/sources.yaml` 및 앞서 작성된 별도 설계 문서를 참고한다.

## 승인정보 CSV 가져오기 (수동 파일 경로)

공식 조회/엑셀 자료를 담당자가 CSV UTF-8 또는 CP949로 저장한 경우 다음을 사용할 수 있다. 데이터의 원본성과 누락 여부는 **별도 검증**해야 한다. 5개 임상시험 필드는 요청한 형태로 HTML 표에 들어간다.

```powershell
.\.venv\Scripts\python.exe main.py import-approval-csv .\approvals.csv --kind clinical
.\.venv\Scripts\python.exe main.py prepare demo-2026-11-16-22
.\.venv\Scripts\python.exe main.py export-html demo-2026-11-16-22
```

`--kind`는 `clinical`, `treatment`, `drug` 중 선택한다. 변경승인 여부 등 CSV의 개별 이벤트는 별도 레코드로 저장하되, 자동 공식 사이트 다운로드를 구현했다는 뜻은 아니다.

## GPT 추천 작업 (API 키 없이)

```powershell
.\.venv\Scripts\python.exe main.py export-ai demo-2026-11-16-22
```

`output/candidates_demo-2026-11-16-22.json`를 ChatGPT Work에 전달해 **근거에 맞는 분류와 요약 제안**을 요청하고, 다음 형식으로 JSON을 저장한다. 원본 데이터나 사용자 선택 결과는 이 과정에서 덮어쓰지 않는다.

```json
{
  "items": [
    {"id": "기존 레코드 ID", "section": "mfds.regulations", "summary": "확인된 사실만 요약", "score": 85, "reason": "의약품 규제 업데이트", "recommended": true}
  ]
}
```

```powershell
.\.venv\Scripts\python.exe main.py import-ai demo-2026-11-16-22 .\ai_review.json
```

수집된 전체 자료는 `data/newsletter.db`에 저장되며, GPT 제안의 점수는 사용자 편집을 대체하지 않는다. HTML은 로컬 웹 화면에서 받거나 다음과 같이 생성한다.

```powershell
.\.venv\Scripts\python.exe main.py export-html demo-2026-11-16-22
```

## 운영 유의사항

- SQLite DB 파일을 Git에 커밋하지 않는다.
- 로컬 서버는 `127.0.0.1`에만 바인딩되며, 상태 수정 요청에는 세션 토큰이 필요하다. 인터넷에 서버를 직접 공개하지 않는다.
- 자동 예약은 **Windows 작업 스케줄러에 수집 명령을 등록하는 방식**을 권고하며, 이 패키지는 스케줄을 자동 생성하지 않는다.
- 샘플 7건은 2026-11-16~22의 **일부 테스트 자료**다. 실제 전체 수집이나 원문 재검증을 뜻하지 않는다.
- TOP 선택과 식약처 상세 포함은 별도다. 원본 892호의 회사/임상/의약품 허가 영역은 정보가 없을 때 미수집을 숨기지 않도록 설계해야 하며 이 MVP에서는 임상 영역을 미연동으로 표시한다.
