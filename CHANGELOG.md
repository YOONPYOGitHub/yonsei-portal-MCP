# Changelog

이 프로젝트의 주요 변경 사항을 기록합니다. 형식은
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)을 따르며,
버전 체계는 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

### Changed
- 공개 좌석 도구의 `in_use`, `remaining`, `usage_pct`를 미확인 `null`로 변경. API 필드와 홈페이지 표시의 의미 충돌을 확인해 `raw_use`, `raw_total_minus_use`, `semantics_verified=false`, `scope`로 한계를 명시. 소비자는 숫자 산술·정렬 전에 미확인 상태를 처리해야 함.
- 알 수 없는 좌석 필터를 정상 빈 집계 대신 오류로 반환. `/빈자리` 프리셋은 로그인 열람실 현황을 사용하며 원문 수치를 잔여석으로 추정하지 않음.
- README의 33개 도구 표를 분야별 기본 펼침으로 구성하고 사용 가이드·실제 대화 캡처 연결. 과거 PC석 답변은 의미 검증 실패 사례로 구분.

### Fixed
- LearnUs 이미지 전용 공지에 이미지 수·미추출 안내를 반환. 본문 준비를 기다리고 본문 구조가 없는 화면을 페이지 전체 텍스트로 대체하지 않음.
- ERP 셸이 늦게 준비될 때 로그인 폼만 기다리던 경합 수정. 최초 프로필 간헐 실패는 재검증에서 재현되지 않았으나 원인 확정으로 간주하지 않음.
- 수동 공개 좌석 검사도 미확인 점유·빈 집계 계약을 따르도록 수정.

### Added
- LearnUs 핵심 필드 원문 대조, 새 MCP 프로세스별 프로필 첫 호출·시간표 후 호출과 재시도 없는 프로필 원문 대조 검사.

## [0.5.0b1] - 2026-09-30

첫 공개 베타의 소스 변경 내역입니다. PyPI 게시와 GitHub Release는 별도입니다.
현재 계약·검증 근거·미완료 범위는 [DESIGN.md](DESIGN.md)를 따릅니다.
공개 API는 [docs/TOOLS.md](docs/TOOLS.md), 사용자 실행은 [README.md](README.md), 개발·릴리스 절차는 [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)를 참고하세요.

### Changed
- 버전을 `0.5.0b1`로 정리하고 MCP 의존성을 `>=1.27.2,<2`로 제한. 잠금 환경은 SDK 1.27.2를 유지하며 새 wheel 설치에서는 별도 SDK 핀이 필요하지 않음.
- **로그인 저장 변경:** 계정·시스템별 쿠키 경로 사용. 기존 공용 쿠키는 자동 이관하지 않아 최초 재인증 필요. 실행 중 설정 변경은 서버 재시작 요구.
- **설정 우선순위 변경:** 명시적 환경변수가 설정 파일보다 우선. 실접속 비활성화를 설정 파일이 덮어쓰지 않음.
- **프로필 기본값 변경:** 이름·학번 제외. `include_pii=True`로만 포함.
- **실험 옵션 철회:** 미검증 도서관 이력의 날짜·페이지와 과거강좌 page 입력을 공개 스키마에서 제거. 오래된 입력은 무시하지 않고 거절. 내부 합성 테스트는 지원 완료 근거가 아님.
- 공개 도서 검색에 `campus`/`search_field`/`offset`, 전체 건수·원문 필터 검증·연속조회 메타데이터 추가. 기존 `query`/`page`/`limit`과 전체 캠퍼스 기본값은 유지. 검색 자료 ID·상세 지원 여부, 소장처·복본의 정규화 캠퍼스 제공.
- `get_grades` 연도·학기 필터와 누적 요약 범위 구분. `get_exam_schedule` 중간/기말 선택 제공.
- `get_notice`에 공개 도서관 본문 조회 추가. 이미지 내용은 제외하며 출처·이미지 수 안내.
- 공개 도구 수 15개에서 33개로 확장. 오프라인 계약 테스트와 선택적 라이브 테스트를 분리.
- 프리셋의 마감 종류·주말·좌석·실패 해석을 현행 계약에 맞춤.
- 사용자 온보딩·클라이언트 연결·33개 API 계약·개발/릴리스 가이드 제공.

### Added
- Ubuntu/Python 3.10·3.11·3.12 GitHub Actions CI. 읽기 전용 권한으로 오프라인 회귀와 sdist/wheel 빌드, 독립 환경의 설치·무인증 stdio 기동 검사 수행. 학교·LLM 비밀정보와 라이브 테스트 제외.
- 배포 메타데이터·SDK 버전·모듈·인증서·진입점·33개 도구 등록을 확인하는 패키지 검사 4개. 로컬에서 Python 버전별 오프라인 733개와 새 wheel 검사 4개 통과.
- LearnUs: `get_lms_assignments`, `get_lms_assignment_status`, `get_lms_course_history`, `get_lms_gradebook`, `get_lms_boards`, `get_lms_board_posts`. 제출물/게시판 본문 제외, 성적 피드백 opt-in.
- ERP: `search_courses`, `get_exam_schedule`, `get_scholarship_history`. 수강편람 연도·학기·캠퍼스 필터 및 200건 상한/잘림 표시.
- 도서관: `get_my_reservations`, `get_my_loan_history`, `get_my_reservation_history`, `search_library_books`, `get_library_book_detail`, `get_library_notices`. 이력은 기본 표시 결과만 공개 지원.
- 일정: `get_my_schedule`, `get_academic_calendar`, `export_timetable_ics`. 반복 시간표는 사용자 확인 기간·교시 시각·제외일을 사용하며 자동 학기/교시 발견이 아님.
- LearnUs 한국어 URL/DOM 검증, 원문 연도·학기 조건 확인, 게시판·성적·과제·좌석·이력의 원문 대조와 오류 회귀 테스트.
- Gemini 하니스 및 Azure v1 Responses 어댑터. Azure 응답 저장 비활성화와 추론·도구 메시지 재전송 지원.

### Fixed
- 도서 검색의 로컬 `limit` 이후 바로 다음 페이지로 넘어갈 때 자료가 누락되는 문제를 `next_request`로 방지. 전체 자료 수와 복본 수, 원문 출력 제한(`source_limited`), 100페이지 상한과 수집 완료를 구분. 브라우저/MCP 6개 검색 조합과 실제 LLM 전체 목록·판본 상세·복본 집계 대조를 추가.
- LearnUs 오류/로딩 화면을 빈 결과로 반환하던 문제. 실측 빈 달력·출석 리다이렉트 지원, 지연 자료·중첩 제출물/피드백 표·숫자 날짜 처리 보강.
- ERP 성적 데이터셋 역매핑 및 시간표 소수 학점·미지원 교시 표현 처리. 누락/손상 데이터를 정상 0건으로 숨기지 않음.
- 열람실 합계 행 중복 집계 수정과 원문/배정 가능 잔여석 분리. `좌석배정`/`FULL` 등 운영 상태 및 원문 합계 대조.
- 브라우저 시작 실패·재인증·종료 시 자원 정리와 재시도 전체 잠금 유지.
- 마감 ICS의 동일 시작/종료 제거, 날짜만 있는 값의 자정 추정 방지, UTC 타임스탬프·URI 인코딩 수정.
- LLM 인자 JSON·완료 상태 검사, 필터 누락·빈 결과의 거짓 통과 방지, 민감 입력/대화의 실패 진단 노출 억제. 시나리오는 실패를 종료 코드에 반영하나 데모·덤프 CLI의 0은 성공 증명이 아님.

이전 버전 항목은 당시 릴리스 기록입니다. 아래 `override=True`나 기존 쿠키 경로 설명을 현재 설정으로 사용하지 마세요.

## [0.4.0] - 2026-06-01

### Added
- `get_lms_course_materials` — 특정 강좌의 주차별 학습활동/자료 목록(동영상/강의자료
  파일/과제/게시판)을 LearnUs 강좌 페이지에서 읽어오는 도구. 시험 범위에 맞춰
  실제 강의 콘텐츠를 근거로 답하도록(예: 학습 체크리스트) 모델을 지원.
- LLM 통합 테스트 하니스(`tests/llm/`): 실제 LLM이 MCP 도구를 스스로 선택·호출해
  답변하는지 검증. 다중 제공자 추상화(`azure-openai`/`openai`/`anthropic`),
  실제 MCP 서버에 stdio로 붙는 라이브 시나리오·데모.
- 대화 데모 러너(`tests/llm/demo.py`): 인터랙티브 채팅 모드(`--chat`),
  제공자 선택(`--provider`). 라이브 실행은 `RUN_LIVE_LLM=1` 안전 게이트로 보호.
- `pyproject.toml` 선택 의존성 그룹 `llm`(openai/anthropic/pytest)과
  pytest 설정(`testpaths`, `asyncio_mode`, `llm`/`live` 마커).
- `.env.example` 에 LLM 제공자 설정 섹션 추가(Azure OpenAI keyless/APIM 자동 판별 안내).

### Changed
- 도구 수 14개 → 15개(`get_lms_course_materials` 추가).
- LLM 하니스를 라이브 전용으로 정리: stub 제공자·mock fixtures·인메모리 세션을
  제거하고 실제 포털 로그인 + 실제 LLM 호출만 남김(모두 `RUN_LIVE_LLM=1` 필요).
- `config.py`가 `load_dotenv(override=True)`를 사용해 `.env`를 단일 진실 소스로
  삼음(셸에 남은 stale 환경변수가 `.env`를 덮어쓰지 않도록).
- `.env.example` placeholder 표기를 `<your-...>` 스타일로 통일.

## [0.3.0] - 2026-05-31

### Added
- 학사행정(ERP, underwood1) 도구 3종:
  - `get_student_profile` — 학생 본인 프로필·학기·학점 요약.
  - `get_my_timetable` — 수강신청내역 기반 본인 시간표(요일·교시 파싱 포함).
  - `get_grades` — 전체 성적 이력(신입생 등 이력 없을 시 정상 빈 구조 + 안내).
- ERP 전용 SSO 세션(`ErpSession`)과 `erp.json` 쿠키 저장소.
- WebSquare 그리드 헤드리스 미렌더 대응: 좌측메뉴 클릭 후 `*.do` 응답 JSON을
  `page.on("response")`로 캡처하는 ERP 스크레이퍼(`scrapers/erp.py`).
- `search_notices` — LearnUs 공지 키워드 통합 검색 도구(제목/강좌/유형 AND 매칭,
  `scope`/`limit` 지원).
- 슬래시 명령 프리셋 7종(`.github/prompts/*.prompt.md`)과 README 등록 가이드
  (`/오늘할일`·`/이번주마감`·`/내시간표`·`/내성적`·`/공지검색`·`/빈자리`·`/일정내보내기`).

### Changed
- 도구 수 10개 → 14개.

## [0.2.0] - 2026-05-31

### Added
- `export_calendar_ics` — LearnUs 과제 마감일과 도서 반납예정일을
  iCalendar(.ics)로 내보내는 도구. 의존성 없는 RFC 5545 생성기(`ics.py`).
- `get_library_seats` — **로그인 불필요** 도서관 좌석 집계 도구
  (`/seat/info` httpx 경로, 브라우저 미사용). 건물군 × 좌석유형 단위.
- `get_library_seat_rooms` — **로그인 기반** 열람실별 실시간 좌석현황 도구
  (`/relation/seat`, `table.seatTbl`).
- 경량 HTTP 경로용 공용 클라이언트(`httpclient.py`)와 서버 누락 중간 인증서
  보완을 위한 Sectigo OV 중간 CA 동봉(`_certs/`).
- 패키징 메타데이터(라이선스/분류자/URL)와 `LICENSE`(MIT), `CHANGELOG.md`.

### Changed
- 의존성에 `httpx`, `certifi` 추가.
- 도구 수 6개 → 10개.

## [0.1.0] - 2026-05-30

### Added
- LearnUs(LMS) 조회 도구 6종: `get_lms_courses`, `get_lms_deadlines`,
  `get_lms_notices`, `get_notice`, `get_lms_attendance`, `get_lms_overview`.
- `get_my_loans` — 도서관 개인 대출현황(로그인) 도구.
- Playwright 기반 인증 세션 계층(`session.py`), TTL 캐시(`cache.py`),
  오류 코드 체계(`errors.py`).

[0.3.0]: https://github.com/YOONPYOGitHub/yonsei-portal-MCP/releases/tag/v0.3.0
[0.2.0]: https://github.com/YOONPYOGitHub/yonsei-portal-MCP/releases/tag/v0.2.0
[0.1.0]: https://github.com/YOONPYOGitHub/yonsei-portal-MCP/releases/tag/v0.1.0
