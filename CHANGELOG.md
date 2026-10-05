# Changelog

이 프로젝트의 주요 변경 사항을 기록합니다. 형식은
[Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/)을 따르며,
Python 패키지 버전은 [PEP 440](https://peps.python.org/pep-0440/)의 베타 표기(`0.6.0b1`)를 사용합니다.

## [0.6.0b2] - 2026-10-05

- 수강편람의 원본 조회 조건과 실제 수신 행 범위를 분리해 불일치·미확인·명시 필터 제외를 표시.
- 강의자료를 강좌 구역과 활동 소속에 한정하고 동일 명시 ID의 복제본을 한 번만 집계; 충돌은 오류 처리.
- 안전 거절(`refused`)과 핵심 기록/전체 내보내기 검증을 구분하고 기존 버전 1 아카이브 검증 호환 유지.
- 질문 Markdown/JSONL 동기화 회귀 검사, live 실행 마커 설명, 고정 버전 Ruff 정적 오류 CI 추가.
- 실제 시설 후속 질문에서 확인된 `past` 시간대 표시를 보존해 파싱 실패를 수정하고, 사용/과거 표시를 독립적으로 반환.
- 검색 후속 질문이 선행 검색 응답을 근거로 인용할 수 있도록 평가 계약을 보완.
- 답변 검토에서 반복된 ICS 설명 누락을 줄이도록 실제 MCP 도구 설명에 진도·수료 마감, UTC 단일 시점, 종일 반납일과 일회성 가져오기 범위를 명시. ICS 생성 동작은 유지.
- 신규 MCP 도구·학교 쓰기 동작은 추가하지 않음. 실제 답변/근거는 비공개로 누적 관리.

- 제공자 factory·LLM 로더·공개 예제의 설정 키가 함께 일치하는 정적 회귀 검사를 추가하고 Windows 검증 문구를 정리.
- 38개 도구의 기능별 질문 152개와 기대 동작·제한·개인정보 범위를 공개 데이터셋으로 문서화. 실제 개인 답변·도구 응답은 공개하지 않음.
- 비공개 실행별 호출/답변·근거 해시·상태·재사용 표시와 봉인 체크포인트/아카이브 검증 보조 도구 추가. 새 외부 LLM 호출이나 자동 정기 실행 기능은 아님.

## [0.6.0b1] - 2026-10-05

- 학교 설정 `.env`와 선택적 LLM 하네스 설정 `.env.llm`을 분리. 명시적 LLM 실행 허용 시에만 후자를 읽으며 일반 MCP는 `.env`만 사용. 기존 단일 `.env`와 실행 환경변수 우선순위 유지.
- 예제에 대표 MCP 클라이언트, `LLM_PROVIDER`의 네 지원값과 제공자별 필수/선택 항목·보안·실행 허용 규칙을 명시.

소스 베타의 변경 기록입니다. PyPI 게시·GitHub Release 생성이나 원격 CI 성공을 의미하지 않습니다.

### 공개 공지
- `list_notice_sources`, `get_university_notices`, `get_university_notice` 추가. 로그인·브라우저 없이 등록된 `university`(대학 공지), `graduate`(일반대학원 교내공지), `ai_graduate`(인공지능융합대학원 공지)를 구분해 조회. 임의 URL·다른 대학원 탐색은 지원하지 않음.
- 목록은 서버 page 1~1000, 현재 페이지 출력 limit 1~100(기본 10). 잘린 결과는 `same_page_request`로 먼저 확장한 뒤 `next_request` 사용. `has_next=null`을 마지막 페이지로 오인하지 않으며 고정글 반복·`complete_history=false`로 수집 범위를 명시.
- 본문 식별자·출처·수집시각과 허용된 첨부 링크 제공. 첨부 다운로드·이미지 OCR·전체 이력 완전성 보장은 제외.

### LearnUs 게시판
- `get_lms_board_posts`에 기본 page 1, 범위 1~100 추가. 활성 페이지·연속된 다음 링크 검증과 `next_request`·페이지 상한 표시 제공. 기존 board_id 단독 호출 유지.
- `search_lms_board_posts` 추가. 선택 게시판 첫 페이지부터 제목만 검색하며 기본 3·최대 10페이지, 기본 limit 20·최대 50. 고정글 ID 중복 제거와 검색 페이지·일치 수·잘림·후속 페이지 정보를 제공. 작성자·본문·숨김/링크 없는 글은 검색하지 않음.
- 기존 `get_lms_notices`·`search_notices`는 홈에 표시된 공지 범위를 유지. 선택 본문은 `get_notice`로 별도 조회.
- 공개 도구 **38개**: LearnUs 15·도서관 10·ERP 6·일정 4·공개 공지 3. 기존 도구 이름을 유지하며 업데이트 후 클라이언트의 `tools/list`를 갱신해야 함.

### 설치 진단
- `yonsei-portal-mcp doctor` 및 모듈 진입점의 doctor 추가. 설치·패키지 버전·Chromium 실행 파일과 실제 무인증 stdio 초기화/목록 검사. 기본 MCP 실행 명령은 변경하지 않음.
- 기본 진단은 `.env` 내용·쿠키를 읽거나 로그인·포털·외부 LLM을 호출하지 않음. `--env-file`로 명시한 파일의 자격 증명 존재 여부·출처만 출력하고 비밀값은 출력하지 않음. `--browser`는 임시·격리 Chromium의 빈 페이지 시작만 확인.
- `--json`, 검사별 `--timeout`, 종료 코드 0(필수 로컬 점검 성공)/1(필수 점검 실패)/2(인자·지정 설정 오류). 자격 증명·Chromium은 기본 선택 사항이며 성공이 실제 로그인이나 보안 감사 통과를 뜻하지 않음.

### CI와 보안 자동화
- 기존 Linux/Python 3.10·3.11·3.12, macOS/Python 3.11에 네이티브 Windows/Python 3.11을 더해 5개 조합 구성. OS별 Chromium·wheel Python 경로와 이식 가능한 pytest 설정 파일 사용. 네이티브 Windows의 오프라인 회귀·빌드·독립 wheel 설치를 실제 CI에서 확인. 학교 계정 로그인·NTFS ACL 검증은 별도 범위.
- 별도 Security workflow를 push·PR·주간·수동 실행으로 구성. 잠금 런타임 의존성의 pip-audit와 전체 Git 이력·현재 공개 트리의 비식별 Gitleaks 검사. 읽기 전용 권한·고정된 도구/Action 버전·보고서 비업로드 유지. 구성만으로 실제 CI 통과를 주장하지 않음.
- macOS·Linux·WSL·Windows 설치 안내와 진단·공지 계약 갱신. 기존 문서의 언어·문체 및 영어 법적 원문을 유지하도록 기여 원칙 정리. 실제 검증 범위는 [검증 기록](docs/VALIDATION.md)에서 별도로 관리.

## [0.5.0b2] - 2026-10-04

소스 베타의 변경 기록입니다. PyPI 게시나 GitHub Release 생성을 의미하지 않습니다.

### 보안
- 로그인 전에 학교 HTTPS 출처와 자격 증명 폼의 제출 대상을 검증. 정상 호스트 문자열이 포함된 유사 주소나 예상하지 못한 출처를 거절하고 정상 연세대 SSO는 유지.
- 로컬 쿠키에 비공개 POSIX 권한·심볼릭 링크 및 안전하지 않은 상태 거절·원자적 저장을 적용. Windows는 사용자별 비공개 ACL도 필요하며 설정 객체의 repr에서 비밀 필드를 제외.
- 보안 감사를 거친 런타임 의존성으로 갱신하고 MCP 1.30.0 사용. 요구 범위는 MCP >=1.28.1,<2, anyio >=4.14.2,<5. CI에는 API 키나 학교 자격 증명이 필요하지 않음.
- 애플리케이션과 SDK 설정 로더에 dotenv 비활성 설정을 적용하고 자격 증명 없는 테스트 환경을 분리.
- 공지 URL 쿼리 키·ERP 응답 출처를 제한하고, ERP 학기별 성적 응답은 허용된 필드만 반환.

### 호환성과 안정성
- 모든 MCP 도구에서 미등록 인자·잘못된 입력 형식을 거절. 필터 오타로 조회 범위가 조용히 넓어지지 않으며 잘못된 범위·ID는 인증 전에 거절.
- 출석 표의 중복·실제 키 충돌, 셀 수 불일치, 확인된 데이터 행이 없는 상태를 명시적 오류로 처리. 정상적인 빈 열 제목은 위치 기반 colN 키로 유지.
- 동일 키의 진행 중 캐시 요청을 합치고 완료 항목 수를 제한. 취소·실패 격리와 clear 동작을 보존하며 종합 조회와 개별 도구의 캐시는 계속 독립적으로 유지.
- 34개 도구 이름 유지. 업데이트 후 클라이언트의 tools/list 갱신 필요. 입력 검증 강화와 학기별 성적 필드 최소화는 의도한 동작 변경임.

### 공개 저장소 정리
- 일반 학교·MCP 설정과 선택적 개발용 LLM 예제를 분리. Hermes 연결, 보안 신고, 기여, 제3자 권리 범위 안내 추가.
- MIT 라이선스와 작성자 표기를 유지하고 SPDX 메타데이터·라이선스 파일 패키징 추가. 학교 콘텐츠·상표·개인정보는 프로젝트의 MIT 허가 범위에 포함되지 않음.
- 자격 증명 없이 사용하는 dev 선택 의존성과 회귀 테스트 추가. 기존 Linux/Python 구성에 macOS 오프라인 CI 추가.
- 개인 로컬 에이전트 보고서, 환경 설정 변형 파일, 빌드·테스트 산출물을 Git에서 제외. 신규 읽기 전용 기능은 개발 후보이며 구현된 지원으로 표시하지 않음.

### Changed
- 공개 좌석 도구를 익명 Chromium의 홈페이지 표 조회로 변경. `total/in_use/remaining`은 실제 셀 값, `display_verified=true`, `scope=homepage_display`. 0행과 합계 모순을 보존하고 최상위 합계는 표시 행 합산임을 명시. 로그인은 불필요하지만 Chromium이 필요하며 기존 `raw_use/raw_total_minus_use` 공개 반환은 제거.
- 알 수 없는 좌석 필터를 정상 빈 집계 대신 오류로 반환. `/빈자리` 프리셋은 로그인 열람실 현황을 사용하며 원문 수치를 잔여석으로 추정하지 않음.
- README의 34개 도구 표를 분야별 기본 펼침으로 구성하고 사용 가이드·실제 대화 캡처 연결. 과거 PC석 답변은 의미 검증 실패 사례로 구분.

### Fixed
- LearnUs 이미지 전용 공지에 이미지 수·미추출 안내를 반환. 본문 준비를 기다리고 본문 구조가 없는 화면을 페이지 전체 텍스트로 대체하지 않음.
- ERP 셸이 늦게 준비될 때 로그인 폼만 기다리던 경합 수정. 최초 프로필 간헐 실패는 재검증에서 재현되지 않았으나 원인 확정으로 간주하지 않음.
- 수동 공개 좌석 검사도 홈페이지의 표시값·0행·원문 합계 모순 계약을 따르도록 수정.
- 프로필·학기 데이터셋의 누락/손상을 빈 프로필·이력으로 반환하지 않고 오류로 구분.

### Added
- `get_library_facility_status`: 실제 HTTPS 444번 포트의 시설 UI에서 날짜·도서관·그룹·시설·사용시간을 선택해 목록·선택 불가 상태·시간표를 조회. 예약자 정보와 변경 작업 제외. 포트 없는 443 주소로 인한 잘못된 접근 불가 판단을 정정.
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
