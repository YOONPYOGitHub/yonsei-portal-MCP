# Changelog

이 프로젝트의 주요 변경 사항을 기록합니다. 형식은
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)을 따르며,
버전 체계는 [Semantic Versioning](https://semver.org/lang/ko/)을 따릅니다.

## [Unreleased]

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
