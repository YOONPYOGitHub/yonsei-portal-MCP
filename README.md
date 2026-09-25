# Yonsei Portal MCP

연세대학교 **포털 학사행정(ERP)·LearnUs(LMS)·도서관** 데이터를 LLM이 조회할 수 있게
해주는 **읽기 전용 MCP 서버**입니다. 인증이 필요한 화면은 Playwright(Chromium),
공개 도서 검색·공지·좌석 집계는 HTTP로 읽어 구조화된 JSON을 제공합니다.

이 문서는 현재 소스의 사용법입니다. 설계·검증 범위·개발 백로그는 [DESIGN.md](DESIGN.md),
미출시/버전별 변경은 [CHANGELOG.md](CHANGELOG.md)를 참고하세요. 현재 소스와 배포 패키지의 기능은 다를 수 있습니다.

> ⚠️ 본 서버는 **조회(read-only)** 전용입니다. 과제 제출·성적 변경 등 쓰기 작업은 하지 않습니다.
> 자격 증명은 학교 로그인에 사용하고 세션 쿠키는 로컬에 저장합니다.
> 조회 결과의 학사정보는 사용하는 MCP 클라이언트/LLM에 전달됩니다.

## 제공 도구

| 도구 | 로그인 | 설명 |
| --- | --- | --- |
| `get_lms_courses` | 🔒 | 수강 중인 강좌 목록 (학수번호, 교수, 진도율, 출석 URL 포함) |
| `get_lms_deadlines` | 🔒 | 다가오는 과제/활동 마감일 (LearnUs 달력 '예정된 할 일') |
| `get_lms_notices` | 🔒 | 공지사항 (`scope`: `all` / `course` / `platform`) |
| `search_notices` | 🔒 | 공지 통합 검색 (키워드 AND 매칭, `scope`/`limit`) |
| `get_notice` | 🔒/🔓 | LearnUs 또는 도서관 공지 본문 텍스트. 도서관은 로그인 불필요, 이미지 내용은 제외 |
| `get_lms_attendance` | 🔒 | 특정 강좌의 주차별 출석/학습 현황 (`course_id` 필요) |
| `get_lms_course_materials` | 🔒 | 특정 강좌의 주차별 학습활동/자료 목록 (`course_id` 필요) |
| `get_lms_assignments` | 🔒 | 특정 강좌의 실제 제출 과제(`assign`) 목록·주차·링크. 제출 상태/마감시각은 제외 |
| `get_lms_assignment_status` | 🔒 | 과제 한 건의 제출 여부·채점 상태·마감·최종 수정시각(제출물 내용 제외) |
| `get_lms_course_history` | 🔒 | 본인 과거강좌조회 화면의 연도·학기별 강좌 목록 |
| `get_lms_gradebook` | 🔒 | 강좌별 LMS 성적부의 항목·가중치·표시 점수. ERP 확정 성적과 별개, 피드백 기본 제외 |
| `get_lms_boards` | 🔒 | 강좌별 게시판 목록·표시 게시물 수·최근 갱신 원문 |
| `get_lms_board_posts` | 🔒 | 게시판 첫 페이지의 글 제목·날짜·링크. 작성자·본문·링크 없는 글 제목 제외 |
| `get_lms_overview` | 🔒 | 강좌 + 마감일 + 최근 강좌 공지 종합 요약 |
| `get_my_loans` | 🔒 | 도서관 개인 대출현황 (반납예정일·연장횟수 등) |
| `get_my_reservations` | 🔒 | 본인 **도서 예약** 목록·예약순위·도착 통보일·상태. 좌석/시설 예약은 제외 |
| `get_my_loan_history` | 🔒 | 이전 대출 기록·실제 반납일. 현재 표시 페이지와 원문 날짜 필터 범위만 조회 |
| `get_my_reservation_history` | 🔒 | 이전 도서 예약 이력·과거 상태. 현재 표시 페이지만 조회, 현재 예약과 별개 |
| `export_calendar_ics` | 🔒* | 마감일·반납예정일을 iCalendar(.ics)로 내보내기 |
| `export_timetable_ics` | 🔒 | 사용자가 확인한 기간·교시 시각·제외일로 주간 반복 시간표 ICS 생성 |
| `get_academic_calendar` | 🔓 | 공식 홈페이지의 현재 표시 학기 학사일정. 월별 원문 날짜·제목과 출처 |
| `get_library_seats` | 🔓 | 도서관 좌석 집계 (건물군 × 좌석유형, **브라우저 불필요**) |
| `get_library_seat_rooms` | 🔒 | 중앙도서관 **열람실별** 실시간 좌석현황 |
| `search_library_books` | 🔓 | 소장자료 검색·서지정보·표시된 대출 상태 (`query`, `page`, `limit`), 브라우저 불필요 |
| `get_library_book_detail` | 🔓 | 검색 결과의 복본별 등록번호·청구기호·소장처·도서상태·반납예정일, 브라우저 불필요 |
| `get_library_notices` | 🔓 | 도서관 일반공지 첫 페이지(상단 고정 공지 포함), 브라우저 불필요 |
| `get_student_profile` | 🔒 | 학사행정(ERP) 학생 본인 프로필·학기·학점 요약 |
| `get_my_timetable` | 🔒 | 학사행정(ERP) 수강신청내역 기반 본인 시간표 (요일·교시 파싱) |
| `get_my_schedule` | 🔒 | 오늘부터 1~90일의 마감·도서 반납일과 주간 시간표. 시험 조회 선택 가능 |
| `get_grades` | 🔒 | 성적 이력과 연도·학기 필터. 누적 GPA/취득학점은 별도 범위 표시 |
| `search_courses` | 🔒 | ERP 수강편람 교과목명 검색. 연도·학기·캠퍼스 선택 및 결과 잘림 여부 포함 |
| `get_exam_schedule` | 🔒 | ERP 현재 학기·중간/기말 선택 조회. 조회기간 미등록과 시험 없음을 구분 |
| `get_scholarship_history` | 🔒 | 본인 장학수혜내역. 학번·내부 ID 제외, 장학금 신청 공고는 아님 |

> 🔒 = 연세포털/도서관 로그인 필요 · 🔓 = 로그인 불필요

> \*`export_calendar_ics(include_loans=False)` 로 두면 도서관 로그인 없이 LMS 마감일만 내보냅니다.
> `get_library_seats` 는 공개 JSON(`/seat/info`)을 쓰는 무로그인·무브라우저 도구입니다.

총 33개 도구입니다. `search_library_books`는 검색어 1~200자, 페이지 1~100,
페이지당 최대 10건을 반환하며 `count`는 전체 검색 건수가 아닌 반환 건수입니다.
도서 검색·공지 목록은 5분, 공지 본문은 30분 캐시이며 대출 상태는 실제 이용 전에 원문에서 재확인하세요.
`get_lms_assignments`는 강의자료 캐시를 재사용하며 동영상·퀴즈를 과제로 오인하지 않습니다.
`get_notice`는 반환된 URL의 사이트를 검증해 LearnUs/도서관 경로로 분기합니다.
도서관 공지의 `image_count`가 있으면 이미지 속 표·안내는 추출되지 않았으므로 원문을 확인하세요.

`get_lms_gradebook(course_id, include_feedback=False)`는 현재/과거 강좌의 LMS 표시
성적을 읽습니다. `kind=category|item|total`을 구분하며 소계/총계를 항목과 중복 합산하지
않습니다. `grade_raw`의 `-`·숨김·빈 값은 0점이 아닙니다. 피드백은 명시적으로 요청할 때만
포함하며 HTML 내부 사용자 ID는 반환하지 않습니다. ERP 확정 성적은 `get_grades`로 조회하세요.

`get_library_book_detail(catalog_id)`에는 검색 결과 URL 끝의 `CATTOT`+숫자 ID를
전달합니다. 현재 검증한 이 형식만 지원하며 예약 버튼은 실행하지 않습니다.
빈 `due_date_raw`는 반납예정일이 표시되지 않았다는 뜻입니다.
`get_my_loan_history()`·`get_my_reservation_history()`는 `scope=displayed_page`이며
`count`는 전체 이력 건수가 아닙니다. **두 도구는 인자 없이 기본 표시 결과만 조회합니다.**
날짜·페이지 입력은 실데이터 검증을 마치지 못해 공개 MCP 스키마에서 제거했습니다.
오래된 클라이언트가 `start_date`/`end_date`/`page`를 보내면 기본 조회로 바꾸지 않고
명시적으로 거절합니다. `total`, `has_next`, `next_page`는 확인 가능한 경우만 반환하므로
누락을 0/false로 해석하지 마세요. `date_filters_raw`의 빈 값은 전체 기간을 뜻하지 않습니다.
날짜 검색 버튼은 요청값을 정상 전송했지만, 원본 HTML에는 날짜값이 없고 결과도 0건이라
필터 적용 여부를 판별할 수 없었습니다. 날짜가 비었다는 이유만으로 서버 결함이라고 단정하지
않습니다. 실측 이력은 대출 0건·예약 1건이며 2페이지 링크가 없어 후속 페이지는 미검증입니다.
내부 날짜·페이지 처리 코드와 합성 테스트는 후속 검증용이며 지원 완료 기능이 아닙니다.
성적부·복본·이력은 5분 캐시이고 출처·수집시각을 반환합니다. 성적부 캐시는 계정·강좌·피드백
옵션별, 공개 이력 조회는 계정별로 분리합니다. 대출/예약 이력 자체도 개인정보입니다.

LearnUs 조회는 `lang=ko`를 명시하고 실제 한국어 DOM을 확인합니다. 영문 화면에서 조회를
시작해도 한글로 수집하며 출력 번역 기능을 추가한 것은 아닙니다.
`get_lms_boards(course_id)`에서 받은 `board_id`를 `get_lms_board_posts(board_id)`에
전달합니다. 공통 메뉴가 아니라 강좌 게시판 표만 읽으며, `unlinked_count`는 접근 링크가
없어 제외한 행 수입니다. 이를 글 없음으로 해석하지 마세요. 글 목록은 첫 표시 페이지만
수집하고 `has_pagination=true`이면 나머지는 미수집입니다. 게시판 본문·작성자·첨부파일은
반환하지 않습니다. 두 도구는 계정과 ID별 5분 캐시입니다.

**좌석 수 해석에 주의하세요.** `get_library_seat_rooms`의 `available`은 화면 표시
잔여석이고 `assignable_available`은 배정불가 열람실을 제외한 합계입니다.
`source_totals_match`로 개별 행과 원문 합계 일치를 확인하고 `fetched_at`을 함께 보세요.
60초 캐시이며 원천 시스템의 갱신시각이나 실제 착석 가능성을 보장하지 않습니다.
공개 집계(`get_library_seats`)와 열람실 시스템은 범위·갱신 상태가 달라 합치지 않습니다.
운영 중 `좌석배정`/`배정가능`과 `FULL`/`배정불가` 표시를 구분합니다.

수강편람 검색은 `keyword` 2~100자, `limit` 1~50이며 선택 인자는 `year`,
`term_code`(10/11/20/21), `campus_code`입니다. s1/s3/s7은 신촌 학부/대학원/의료원,
s2/s4/s8은 미래 학부/대학원/의료원입니다. 생략하면 화면 기본값을 사용합니다.
화면·요청 조건·응답 행을 대조합니다. `fetched_count`는 학교 응답 건수,
`matching_count`는 그 안의 필터 일치 건수입니다. 학교 응답 상한은 200건이며
`truncated=true`이면 0건이라도 해당 조건의 과목이 없다고 단정할 수 없습니다.
키워드를 좁혀 다시 검색하세요.
시험일정은 `exam_type=default|midterm|final`로 구분하며 실제 선택된 라벨을 반환합니다.
과거강좌 화면은 전체 연도 조회 시 현재 강좌를 포함할 수 있으며 연도·학기 필터를 지원합니다.
`get_lms_course_history(year, semester)`는 원문에서 선택된 조건과 행의 연도·학기 일치를
검증한 표시 결과입니다(`scope=displayed_result`, `filters_verified=true`). 페이지 번호를
받지 않습니다. 전체 조회 10건과 학기별 합집합 10건이 일치했고 숨겨진 페이지 제어도
없었지만, 이것은 전체 학교 이력의 완전성 증명이 아닙니다. 현재 강좌 6개 중 비교과 2개는
과거강좌 화면에 없었습니다. 이 수치는 검증 시점의 예시이며 계정·시점에 따라 달라집니다.
`pagination_supported=false`, `has_next=null`은 페이지 이동 미지원/다음 결과 미확정을
뜻합니다. 호환용 응답 `page=1`은 입력 인자나 전체 수집 완료 표시가 아닙니다.

과제 상세는 과제 링크의 숫자 `id`를 `assignment_id`로 전달합니다(강좌 ID 아님).
제출 여부와 채점 여부는 독립적입니다. `submission_status=unknown`은 미제출이 아닙니다.
`due`가 없으면 `due_raw`를 확인하며, `overdue_marker`는 화면의 마감경과 표시이지
지각 제출 판정이 아닙니다. 현재 계정의 과거 과제에서 원문과 대조했습니다.

`get_grades(year=2026, term_code="10")`처럼 필터할 수 있습니다. `10/11/20/21`은
1학기/여름/2학기/겨울입니다. `summary_scope=all_terms`인 GPA·취득학점은 누적 값입니다.

`get_my_schedule(days=7, include_loans=True, include_exams=False)`는 KST 오늘부터
기간 내 마감·반납일을 `events`에, 날짜 미상 항목을 `undated_items`에 둡니다.
`weekly_timetable`은 주간 패턴이며 실제 수업일·교시 시각을 추정하지 않습니다.
시험을 포함하면 중간·기말 원문 조회를 `exams`에 별도로 두며 기간 필터는 적용하지 않습니다.
개별 도구 캐시를 재사용하므로 `generated_at`은 원천 데이터 갱신시각이 아닙니다.

### 공식 학사일정과 반복 시간표

`get_academic_calendar()`는 [공식 학사일정](https://www.yonsei.ac.kr/sc/373/subview.do)의
현재 표시 학기를 조회합니다(30분 캐시). 월 경계 항목은 여러 월에 중복될 수 있어
`date_raw`를 원문으로 보존합니다. `display_year/month`는 표시 구간이며 모든 항목의
시작 날짜를 의미하지 않습니다. 개인별 시험·학과 일정을 대체하지 않습니다.

`export_timetable_ics(start_date, end_date, period_times, exclude_dates=None)`는 별도
시간표 내보내기입니다. 날짜는 YYYY-MM-DD, 교시 시각은 KST의 HH:MM으로 받습니다.
`period_times` 형식 예시는 `{"2":{"start":"10:00","end":"10:50"}}`입니다.
**이 시각은 형식 예시이지 확인된 학교 공통 교시표가 아닙니다.** 실제 시간표에 있는
모든 교시의 확인된 시각과 기간이 필요합니다. 모르는 값은 질문하고 추정하지 않습니다.
교시별 주간 반복 이벤트를 생성하며 `exclude_dates`의 날짜를 제외합니다. 공휴일·휴강을
자동 판정하지 않습니다. 해석 불가능한 시간표나 누락된 교시는 부분 내보내기 대신 오류로
처리합니다. 원천 교시·학기 날짜의 자동 발견은 아직 미지원입니다.

> 학사행정(ERP) 도구(`get_student_profile`·`get_my_timetable`·`get_grades`)는
> `underwood1.yonsei.ac.kr` SSO 로그인 후 cpr/eXBuilder 화면의 조회 JSON 응답을 캡처합니다.
> 신입생 등 성적 이력이 없는 계정은 `get_grades` 가 정상적으로 빈 구조를 반환합니다.

## 설치

[uv](https://docs.astral.sh/uv/) 로 의존성과 가상환경을 관리합니다. uv가 없다면:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # Linux/macOS
# Windows(PowerShell): irm https://astral.sh/uv/install.ps1 | iex
```

```bash
# 1) 의존성 동기화 (.venv 자동 생성 + uv.lock)
uv sync

# 2) Chromium 브라우저 다운로드 (최초 1회)
uv run playwright install chromium
```

### 패키지로 설치 (pip / uvx)

아래는 게시된 패키지 설치 방식입니다. 현재 저장소의 `Unreleased` 기능이 PyPI에 게시됐다는
뜻은 아닙니다. 이 문서의 최신 기능을 사용하려면 위 소스 설치 방식을 사용하세요.

```bash
pip install yonsei-portal-mcp
playwright install chromium          # 로그인 도구를 쓰려면 필요
# 또는 격리 실행:
uvx --from yonsei-portal-mcp yonsei-portal-mcp
```

> ⚠️ 로그인 기반 도구(LMS·대출현황·열람실 좌석)는 Playwright Chromium이 필요합니다
> (`playwright install chromium`). 무로그인 `get_library_seats` 만 쓴다면 브라우저
> 없이도 동작합니다.

공개 도서 검색과 도서관 공지도 로그인·Chromium 없이 사용할 수 있습니다.

## 자격 증명 설정

`.env.example` 을 복사해 `.env` 를 만들고 연세포털 학번/비밀번호를 입력합니다.
(`.env` 는 `.gitignore` 로 보호됩니다.)

```bash
cp .env.example .env
```

```dotenv
YONSEI_ID=학번
YONSEI_PASSWORD=비밀번호
# 최초 1회 또는 2단계 인증/보안문자가 필요하면 true 로 두고 직접 로그인하세요.
YONSEI_HEADED=true
YONSEI_STORAGE_STATE=.session/storage_state.json
```

`YONSEI_STORAGE_STATE`는 쿠키 저장의 기준 경로입니다. 실제로는 계정 ID의 SHA-256
해시와 시스템별 하위 디렉터리를 사용합니다. 위 설정의 LearnUs 쿠키는
`.session/<account-hash>/learnus/storage_state.json`, 도서관과 ERP는 각각
`.session/<account-hash>/library/library.json`, `.session/<account-hash>/erp/erp.json`에 저장됩니다.
해시는 암호화가 아니며 쿠키 파일 자체는 민감정보입니다. 기존 공용 쿠키는 자동 이관하거나
재사용하지 않으므로 업데이트 후 최초 한 번은 다시 로그인합니다. 기존 파일은 삭제하지 않습니다.
실행 중 로그인 설정을 바꾸면 캐시·세션 재사용을 차단하므로 MCP 서버를 재시작하세요.
(`YONSEI_HEADED=false` 로 무인 실행 가능)

**명시한 환경변수가 설정 파일보다 우선합니다.** 설정 파일은 아직 설정되지 않은 값만
채웁니다. 따라서 `RUN_LIVE_LLM=0` 또는 `RUN_LIVE_PORTAL=0`을 지정하면 설정 파일의
값으로 다시 켜지지 않습니다. 다른 값을 적용하려면 해당 환경변수를 수정하거나 해제하세요.

## 실행 / 테스트

```bash
# 서버 직접 실행 (stdio)
uv run yonsei-portal-mcp
# 또는
uv run python -m yonsei_portal_mcp
```

MCP Inspector로 도구를 직접 호출해 응답을 확인할 수 있습니다:

```bash
npx @modelcontextprotocol/inspector uv run yonsei-portal-mcp
```

최초 로그인 시 `YONSEI_HEADED=true` 로 두면 브라우저 창이 떠서 2단계 인증을
직접 처리할 수 있고, 이후 세션이 저장됩니다.

## LLM 통합 테스트 / 대화 데모

실제 LLM이 이 MCP 서버의 도구를 **스스로 선택·호출**해 한국어로 답하는지
확인할 수 있는 하니스가 `tests/llm/` 에 있습니다. 통합 검증은
**실제 연세포털에 로그인해 실데이터로** 실행하며 provider 계약 단위 테스트는
네트워크 없이 실행합니다. 추가 의존성은 선택
그룹으로 분리되어 있습니다:

```bash
uv sync --extra llm     # openai / anthropic / pytest 등 테스트 전용 의존성
```

LLM 제공자는 `.env` 의 `LLM_PROVIDER` 로 고릅니다
(`azure-openai` | `openai` | `anthropic` | `gemini`). 각 제공자 설정 키는
`.env.example` 의 주석을 참고하세요. Azure OpenAI는 **keyless(APIM)** 와
**AOAI 키** 두 방식을 입력한 키에 따라 자동 판별합니다
(`AZURE_OPENAI_API_KEY` 가 비어 있으면 APIM 구독키로 대체).

글로벌 API는 OpenAI GPT, Anthropic Claude, Google Gemini를 지원합니다.
각 서비스의 API 키가 별도로 필요하며 Azure/APIM 키나 Claude Desktop 구독으로
다른 서비스의 API를 호출할 수는 없습니다. 글로벌 서비스 이용 시 학사정보의
국외 처리 및 서비스별 데이터 정책을 확인하세요.

Azure는 `AZURE_OPENAI_API_VERSION=v1`이면 `/openai/v1/responses`를 사용합니다.
GPT-5.6의 추론과 도구 호출을 함께 지원하며 `store=False`로 응답 저장을 끕니다.
날짜형 API 버전은 기존 Chat Completions 경로를 유지합니다. 모델 배포 버전
(`2026-07-09`)과 API 버전(`v1`)은 서로 다른 설정입니다.
Luna(nano급)보다 상위인 Terra(mini급)를 선택한 기준은
[OpenAI 공식 모델 설명](https://developers.openai.com/api/docs/models/gpt-5.6-terra)입니다.

공식 연동 문서: [Gemini OpenAI 호환 API](https://ai.google.dev/gemini-api/docs/openai),
[Claude API 모델](https://platform.claude.com/docs/en/about-claude/models/overview),
[Azure v1 API](https://learn.microsoft.com/en-us/azure/ai-foundry/openai/api-version-lifecycle).

> ⚠️ 라이브 하니스(데모/시나리오/live pytest)는 **실제 포털 로그인 + 본인 학사정보를
> 클라우드 LLM으로 전송**합니다. 해당 실행에 `RUN_LIVE_LLM=1`을 명시해야 합니다.
> 셸에서 지정한 `0`은 설정 파일보다 우선하며, 포털 전용 검사는 별도 `RUN_LIVE_PORTAL` 게이트를 사용합니다.

### 대화 데모 (`tests/llm/demo.py`)

```bash
# 한 번에 질문 1개
RUN_LIVE_LLM=1 uv run python -m tests.llm.demo "이번 학기 시간표 알려줘"

# 인터랙티브 채팅(계속 타이핑; 빈 줄 또는 exit 로 종료)
RUN_LIVE_LLM=1 uv run python -m tests.llm.demo --chat

# 제공자 강제 지정
RUN_LIVE_LLM=1 uv run python -m tests.llm.demo --provider azure-openai --chat
RUN_LIVE_LLM=1 uv run python -m tests.llm.demo --provider openai --chat
RUN_LIVE_LLM=1 uv run python -m tests.llm.demo --provider anthropic --chat
RUN_LIVE_LLM=1 uv run python -m tests.llm.demo --provider gemini --chat
```

### 시나리오 일괄 검증 (`tests/llm/scenarios.py`)

```bash
# 33개 한국어 질의를 실제 포털에 붙여 도구 선택을 채점
RUN_LIVE_LLM=1 uv run python -m tests.llm.scenarios
```

### pytest

```bash
# 오프라인 회귀 테스트 (provider 계약, ICS, 신규 읽기 도구)
PYTHON_DOTENV_DISABLED=1 RUN_LIVE_LLM=0 RUN_LIVE_PORTAL=0 uv run pytest -m "not live" -q

# 전체 33개 MCP 도구 실접속 및 도서관/학사 원문 대조 (LLM API 키 불필요)
RUN_LIVE_PORTAL=1 RUN_LIVE_LLM=0 uv run pytest tests/test_live_tools.py -q --tb=no --show-capture=no

# 실제 포털+LLM E2E 테스트 (RUN_LIVE_LLM=1 미설정 시 skip)
RUN_LIVE_LLM=1 uv run pytest tests/llm -q --tb=no --show-capture=no
```

기본 `pytest`는 `test_*.py`만 수집하므로 수동 `smoke*.py`는 실행하지 않습니다.
라이브 도구 테스트는 응답 원문 대신 도구 이름·성공 여부만 출력합니다.
LLM 대화 데모/시나리오 러너는 답변 원문을 출력하므로 로그 공유에 주의하세요.
[tests/llm/dump_tools.py](tests/llm/dump_tools.py)는 인자와 도구 응답 원문도 출력합니다.
자동 검증의 비식별 진단과 다르므로 개인정보가 포함된 덤프를 공유하지 마세요.
LLM 도구 선택은 실행마다 달라질 수 있습니다. 특정 강좌를 확인할 때는 강좌 ID를
명시하고, 도구 자체의 회귀 검증에는 전체 도구 스모크 테스트를 사용하세요.
시나리오는 기대 도구뿐 아니라 MCP `isError`, 호출 예외, 최종 답변 유무와 턴 제한도
검사합니다. 조회 실패를 설명하는 답변이 생성됐다는 이유만으로 PASS 처리하지 않습니다.
출석·강의자료·열람실 시나리오는 강좌 목록이나 공개 집계만 호출해서 통과할 수 없습니다.
성적·수강편람 필터와 기말시험 선택은 호출 인자까지 검증합니다. 성적 필터 실접속 검사는
필터 없는 원본의 일치 행 전체와 비교하므로 빈 결과로 데이터가 사라져도 통과하지 않습니다.
깨진 JSON 인자와 JSON 객체가 아닌 인자는 실행하지 않으며, 토큰 제한 등으로 중단된
LLM 답변은 정상 완료로 취급하지 않습니다. 실패 진단과 객체 표현은 대화 원문을 제외합니다.

조회 실패와 정상적인 빈 결과를 구분합니다. LearnUs 마감·출석·자료는 최종 경로/강좌 ID와
표시 구조 준비를 검사하고, ERP 시간표는 명시적인 빈 데이터셋만 0건으로 처리합니다.
구조를 확인할 수 없는 강좌는 자료 없음으로 단정하지 않습니다. 범위/격주 등 미지원 강의시간은
`time_raw`로 보존하고 `slots=[]`로 반환하므로 수업 없음으로 해석하면 안 됩니다.
학점은 소수 값을 보존하며 누락·잘못된 값을 임의로 0으로 합산하지 않습니다.
마감 ICS는 순간 이벤트의 `DTEND`를 생략하고, 시각 없는 날짜를 자정으로 추정하지 않습니다.

## 구현 상태와 남은 범위

현재 공개 도구는 33개이며 웹사이트의 모든 메뉴가 구현된 것은 아닙니다.
도서관 이력 날짜·페이지 옵션은 실검증 미완료로 공개 입력에서 제외했습니다.
게시판 본문·후속 페이지, 강의계획서, 시설 개인 예약내역, 신청가능 장학금 등도 별도 미완료 작업입니다.
검증 날짜·표본·한계와 재개 조건은 [DESIGN.md](DESIGN.md)에서 관리합니다.

## 클라이언트 등록

### Claude Desktop (`claude_desktop_config.json`)

Claude Desktop은 자체 Claude 모델로 MCP 도구를 호출합니다. `.env`의
`LLM_PROVIDER`는 저장소 테스트/데모용이며 Desktop의 모델을 바꾸지 않습니다.

```json
{
  "mcpServers": {
    "yonsei-portal": {
      "command": "python",
      "args": ["-m", "yonsei_portal_mcp"],
      "cwd": "/절대/경로/yonsei-portal-MCP",
      "env": { "YONSEI_HEADED": "false" }
    }
  }
}
```

> 가상환경을 쓴다면 `command` 를 해당 venv의 `python` 절대 경로로 지정하세요.

### VS Code (`.vscode/mcp.json` 또는 사용자 설정)

```json
{
  "servers": {
    "yonsei-portal": {
      "type": "stdio",
      "command": "python",
      "args": ["-m", "yonsei_portal_mcp"],
      "cwd": "/절대/경로/yonsei-portal-MCP"
    }
  }
}
```

## 슬래시 명령 프리셋 가이드

자주 쓰는 질의를 매번 길게 입력하지 않도록, MCP 도구를 묶어 호출하는 **프리셋
프롬프트**를 슬래시 명령으로 등록해두면 편리합니다. 아래는 권장 프리셋 7종과
각 클라이언트(VS Code / Claude Desktop) 등록 방법입니다.

### 권장 프리셋 7종

| 슬래시 명령 | 의도 | 호출 도구 |
| --- | --- | --- |
| `/오늘할일` | 마감 종류 구분 + 최근 강좌 공지 정리 | `get_lms_overview` |
| `/이번주마감` | 오늘부터 7일의 마감, 날짜 미상 항목 별도 | `get_my_schedule` |
| `/내시간표` | 이번 학기 시간표(요일·교시·강의실) | `get_my_timetable` |
| `/내성적` | 전체 성적 이력 요약 | `get_grades` |
| `/공지검색` | 키워드로 공지 통합 검색 | `search_notices` |
| `/빈자리` | 도서관 실시간 좌석 현황 | `get_library_seats` |
| `/일정내보내기` | 마감일·반납예정일 .ics 생성 | `export_calendar_ics` |

### VS Code (`.github/prompts/*.prompt.md`)

워크스페이스에 프롬프트 파일을 만들면 Copilot Chat에서 `/오늘할일` 처럼
호출됩니다. 본 저장소의 `.github/prompts/` 에 7종 프리셋이 이미 포함되어 있습니다.
예) `.github/prompts/오늘할일.prompt.md`:

```markdown
---
mode: agent
description: 다가오는 마감과 최근 강좌 공지를 종류별로 정리합니다.
---
`get_lms_overview` 도구를 호출해서 다가오는 마감을 가까운 순으로 정리하고
최근 강좌 공지의 중요한 항목을 3줄 이내로 요약해줘.
kind의 assignment는 제출 과제/활동, progress는 강의 진도, completion은 수료 마감으로 구분해줘.
날짜를 확인할 수 없으면 추정하지 말고 원문을 남겨줘. 조회 오류를 할 일 없음으로 안내하지 마.
```

예) `.github/prompts/공지검색.prompt.md` (인자 사용):

```markdown
---
mode: agent
description: 키워드로 LearnUs 공지를 통합 검색합니다.
---
`search_notices` 도구를 `query="${input:키워드}"`, `scope="all"` 로 호출하고,
결과를 제목·강좌·날짜 표로 정리해줘. 검색 범위는 LearnUs이며 학교 전체 통합 검색이라고 부르지 마.
정상 빈 결과와 조회 오류를 구분하고 날짜가 없으면 추정하지 마.
```

### Claude Desktop (프로젝트 / 커스텀 지침)

Claude Desktop은 별도 슬래시 명령 파일은 없지만, **프로젝트 지침**이나 저장된
프롬프트에 아래처럼 매핑을 적어두면 같은 효과를 냅니다:

```text
- "오늘 할 일" 또는 "/오늘할일" → get_lms_overview 호출 후 마감 임박순 정리
- "내 시간표" → get_my_timetable 호출 후 요일×교시 표로 출력
- "공지 검색 <키워드>" → search_notices(query=<키워드>, scope="all")
- "도서관 빈자리" → get_library_seats 호출
```

> 프리셋은 **도구를 어떻게 조합/표현할지**만 안내합니다. 실제 데이터 조회·인증은
> 서버가 담당하므로, 프롬프트에는 학번/비밀번호 같은 비밀값을 넣지 마세요.

## 동작 방식

1. `https://ys.learnus.org/` 접속 → 이미 로그인되어 있으면 통과.
2. "연세포털 로그인"(`a.btn-sso`) 클릭 → 연세 통합인증 SSO 폼으로 이동.
3. `#loginId` / `#loginPasswd` 입력 후 페이지의 `fSubmitSSOLoginForm()` 호출.
4. LearnUs로 리다이렉트되면 각 페이지를 `page.evaluate()` 로 스크래핑.

## 보안 메모

- 비밀번호는 로그에 남기지 않으며 도구 응답에도 포함되지 않습니다.
- `.env`, `.session/`, `storage_state.json` 은 git에서 제외됩니다.
- 프로필은 기본적으로 이름·학번을 제외합니다. 사용자가 명시적으로 요청하면
  `get_student_profile(include_pii=True)`로 포함할 수 있습니다. 성적·대출·출석 등
  개인 데이터 자체는 연결한 LLM에 전달될 수 있습니다.
- 재인증/시작 실패/정상 서버 종료에서 브라우저와 드라이버를 정리합니다.
  재시도와 종료는 세션 잠금으로 직렬화하며 일반 예외 원문을 응답에 노출하지 않습니다.
- 공개 검색·공지 도구는 학교 자격 증명을 사용하지 않고, 공지 작성자를 반환하지 않습니다.

## 한계 / 알려진 사항

- 최초 로그인이나 2단계 인증/보안문자 발생 시 `YONSEI_HEADED=true` 로 직접 처리 필요.
- LearnUs 주간 강의시간표 그리드는 비어 있는 경우가 많아 MVP에서 제외했습니다.
- 사이트 DOM 변경 시 스크래퍼 셀렉터 갱신이 필요할 수 있습니다.
