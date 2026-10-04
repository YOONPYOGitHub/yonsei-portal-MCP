# Yonsei Portal MCP

연세대학교 LearnUs·학사행정(ERP)·도서관 정보를 MCP 클라이언트에서 조회하는 **개인용 읽기 전용 서버**입니다.
현재 강좌, 마감, 출석, 성적, 시간표, 게시판, 도서·좌석·세미나룸 현황과 학사일정을 34개 도구로 제공합니다.
인증 조회와 홈페이지 좌석 표는 Playwright Chromium, 나머지 공개 조회는 HTTP를 사용합니다. 웹 UI나 원격 HTTP MCP 서비스가 아니라 **로컬 stdio 프로세스**입니다.

[사용 가이드·실제 캡처](docs/USAGE.md) · [질문 예시](#이렇게-물어보세요) · [전체 기능 34개](#지원-기능-전체-목록) · [설치](#빠른-시작) · [클라이언트 연결](#클라이언트-연결) · [API 참조](docs/TOOLS.md)

**본인에게 허용된 계정을 위한 비공식·로컬·읽기 전용 연세대 MCP입니다.**
LLM은 연결한 클라이언트에서 제공하므로 이 서버에 별도 LLM API 키를 설정할 필요가 없습니다.
Python 3.10 이상과 uv가 필요하며, 로그인 조회에는 Playwright Chromium도 필요합니다.
[보안 정책](SECURITY.md), [기여 안내](CONTRIBUTING.md),
[라이선스·제3자 고지](THIRD_PARTY_NOTICES.md)를 확인하세요.
MIT 라이선스는 학교 콘텐츠·상표·개인정보에 대한 이용 권한을 부여하지 않습니다.

> 이 프로젝트는 학교의 공식 서비스가 아닙니다. 본인에게 허용된 계정·조회 범위에서 사용하고 학교 이용 정책을 확인하세요.
> 로그인 자격 증명은 학교 인증에 사용하며, 조회 결과는 연결한 MCP 클라이언트와 그 LLM에 전달될 수 있습니다.
> 읽기 전용은 개인정보가 없다는 뜻이 아닙니다. 과제 제출·예약·취소·대출 연장·수강신청·결제는 지원하지 않습니다.

## 이렇게 물어보세요

MCP 연결 후 사용하는 클라이언트의 대화창에 입력할 수 있는 예시입니다. 질문에 맞는 자료를 도구로 조회하고, 요약·비교는 연결한 LLM이 수행합니다.

실제 질문 → 도구 호출 → 답변 캡처와 결과 해석은 [사용 가이드](docs/USAGE.md)에서 확인하세요.

| 하고 싶은 일 | 질문 예시 | 학교 로그인 | 관련 기능 |
| --- | --- | --- | --- |
| 책 찾기·대출 상태 확인 | 신촌 도서관에 위키드 한국어 소설이 있는지, 복본별로 대출 가능한지 확인해줘. | 불필요 | [도서 검색](docs/TOOLS.md#search_library_books) + [복본 상세](docs/TOOLS.md#get_library_book_detail) |
| 열람실 현황 확인 | 열람실별 사용 중·표시 잔여석과 배정 가능한 방의 잔여 합계를 구분해줘. | 필요 | [열람실별 좌석](docs/TOOLS.md#get_library_seat_rooms) |
| 세미나룸 시간표 확인 | 내일 학술정보관 세미나룸 목록을 확인하고, 선택한 시설의 30분 단위 사용 표시를 보여줘. 예약은 하지 마. | 필요 | [시설 현황](docs/TOOLS.md#get_library_facility_status) |
| 학교 일정 확인 | 현재 공개된 학사일정에서 수강철회 기간을 찾아줘. | 불필요 | [학사일정](docs/TOOLS.md#get_academic_calendar) |
| 학습 현황 한 번에 보기 | LearnUs의 현재 강좌, 다가오는 마감, 강좌 공지를 정리해줘. | 필요 | [학습 종합 조회](docs/TOOLS.md#get_lms_overview) |
| 과제 제출 여부 확인 | 현재 강좌의 과제 목록을 보고 각 과제의 제출 상태와 채점 상태를 확인해줘. | 필요 | [과제 목록](docs/TOOLS.md#get_lms_assignments) + [제출상태](docs/TOOLS.md#get_lms_assignment_status) |
| 공지 찾기·내용 확인 | LearnUs 강좌 공지에서 중간시험 관련 제목을 찾아 본문을 정리해줘. | 필요 | [공지 검색](docs/TOOLS.md#search_notices) + [공지 본문](docs/TOOLS.md#get_notice) |
| 수업 장소 확인 | 내 시간표를 요일별로 정리하고 강의실과 교시를 보여줘. | 필요 | [시간표](docs/TOOLS.md#get_my_timetable) |
| 성적 확인 | 2025년 2학기 과목 성적을 보여주고, 누적 평점은 따로 표시해줘. | 필요 | [ERP 성적](docs/TOOLS.md#get_grades) |
| 개인 일정 모아보기 | 오늘부터 7일간 LearnUs 마감과 도서 반납일을 함께 보여줘. | 필요 | [개인 일정](docs/TOOLS.md#get_my_schedule) |
| 캘린더로 옮기기 | LearnUs 마감과 도서 반납일을 캘린더에 가져올 ICS 텍스트로 만들어줘. | 필요 | [마감·반납일 내보내기](docs/TOOLS.md#export_calendar_ics) |

조회 범위·캐시·권한에 따라 확인할 수 있는 결과가 달라집니다. 잔여석은 실제 배정을 보장하지 않으며, 진도·수료 마감은 제출 과제와 구분합니다. ICS 도구는 텍스트를 반환할 뿐 파일 저장이나 캘린더 등록은 하지 않습니다.
**LLM API 키는 MCP 서버 사용에 필요하지 않습니다.** 모델은 Claude Code/Desktop·VS Code 등 클라이언트가 선택합니다.

<details>
<summary>실제 대화 기록 미리보기: 도서 검색과 복본 상태</summary>

![2026-09-30 실제 도서 조회 기록 뷰어. 위키드 1권 2024년판의 신촌 복본 상태와 원문 링크](docs/assets/guide/books.png)

실제 LLM·MCP 기록을 표시한 뷰어 캡처이며 Copilot·Claude 앱 화면이 아닙니다. 상태는 촬영 시점 기준입니다. [질문 전문과 결과 해석](docs/USAGE.md#1-도서-찾기와-대출-상태)을 확인하세요.

</details>

## 지원 기능 전체 목록

**LearnUs 14개 · 도서관 10개 · 학사행정 6개 · 일정 4개 = 34개.** 도구 이름을 누르면 입력·반환값·제약을 볼 수 있습니다.
`필요`는 본인 학교 계정과 Chromium이 필요하다는 뜻입니다. 공개 조회는 로그인 불필요이며, 홈페이지 좌석 표는 화면 렌더링을 위해 Chromium을 사용합니다.

### LearnUs (14개)

| 기능 | MCP 도구 | 학교 로그인 |
| --- | --- | --- |
| 현재 수강 강좌 목록 | [get_lms_courses](docs/TOOLS.md#get_lms_courses) | 필요 |
| 연도·학기별 과거강좌 표시 목록 | [get_lms_course_history](docs/TOOLS.md#get_lms_course_history) | 필요 |
| 강좌·마감·최근 강좌 공지 묶음 | [get_lms_overview](docs/TOOLS.md#get_lms_overview) | 필요 |
| 달력에 표시된 과제·진도·수료 마감 | [get_lms_deadlines](docs/TOOLS.md#get_lms_deadlines) | 필요 |
| 강좌별 출석·학습 진도 표 | [get_lms_attendance](docs/TOOLS.md#get_lms_attendance) | 필요 |
| 주차별 학습활동·자료 제목과 링크 | [get_lms_course_materials](docs/TOOLS.md#get_lms_course_materials) | 필요 |
| 강좌별 과제 목록 | [get_lms_assignments](docs/TOOLS.md#get_lms_assignments) | 필요 |
| 과제 제출상태·채점상태·마감 | [get_lms_assignment_status](docs/TOOLS.md#get_lms_assignment_status) | 필요 |
| 항목별 LMS 성적부·선택적 피드백 | [get_lms_gradebook](docs/TOOLS.md#get_lms_gradebook) | 필요 |
| 홈에 표시된 강좌·플랫폼 공지 목록 | [get_lms_notices](docs/TOOLS.md#get_lms_notices) | 필요 |
| 수집된 공지 제목·강좌·유형 키워드 검색 | [search_notices](docs/TOOLS.md#search_notices) | 필요 |
| LearnUs·도서관 공지 본문 텍스트 | [get_notice](docs/TOOLS.md#get_notice) | LearnUs 필요 / 도서관 불필요 |
| 강좌 게시판 목록 | [get_lms_boards](docs/TOOLS.md#get_lms_boards) | 필요 |
| 게시판 첫 페이지의 글 제목·날짜·링크 | [get_lms_board_posts](docs/TOOLS.md#get_lms_board_posts) | 필요 |

자료·영상·제출물은 다운로드하지 않습니다. LMS 점수는 ERP 성적과 별개이며, 과거강좌는 화면의 표시 범위입니다.

### 도서관 (10개)

| 기능 | MCP 도구 | 학교 로그인 |
| --- | --- | --- |
| 캠퍼스·서명·저자별 소장자료 검색, 전체 건수·연속조회 | [search_library_books](docs/TOOLS.md#search_library_books) | 불필요 |
| 복본별 소장처·청구기호·상태·반납예정일 | [get_library_book_detail](docs/TOOLS.md#get_library_book_detail) | 불필요 |
| 일반공지 첫 페이지 목록 | [get_library_notices](docs/TOOLS.md#get_library_notices) | 불필요 |
| 홈페이지 전체·사용·잔여석 표의 표시값 (Chromium 필요) | [get_library_seats](docs/TOOLS.md#get_library_seats) | 불필요 |
| 열람실별 좌석·운영시간·배정 가능 여부 | [get_library_seat_rooms](docs/TOOLS.md#get_library_seat_rooms) | 필요 |
| 날짜·도서관·그룹·시설·사용시간별 선택 목록과 시간표 | [get_library_facility_status](docs/TOOLS.md#get_library_facility_status) | 필요 |
| 내 대출 도서·반납예정일 | [get_my_loans](docs/TOOLS.md#get_my_loans) | 필요 |
| 내 현재 도서 예약·순위·상태 | [get_my_reservations](docs/TOOLS.md#get_my_reservations) | 필요 |
| 내 대출 이력의 기본 표시 결과 | [get_my_loan_history](docs/TOOLS.md#get_my_loan_history) | 필요 |
| 내 이전 도서 예약 이력의 기본 표시 결과 | [get_my_reservation_history](docs/TOOLS.md#get_my_reservation_history) | 필요 |

검색 자료 수와 실제 복본 수는 다릅니다. 개인 이력의 날짜·페이지 지정, 예약 생성·취소·대출 연장은 지원하지 않습니다.
공개 좌석은 홈페이지의 셀 값을 그대로 반환합니다. `display_verified=true`는 화면과의 일치를 뜻하며, `source_totals_match=false`는 화면 자체의 합계 모순입니다. 이용률은 화면에 없어 `null`입니다. 세미나룸은 시간대별 사용 표시를 읽지만 예약 확정·개인 시설 예약내역 조회·예약 생성/취소는 수행하지 않습니다.

### 학사행정 ERP (6개)

| 기능 | MCP 도구 | 학교 로그인 |
| --- | --- | --- |
| 학과·조회 학기·수강학점 프로필 | [get_student_profile](docs/TOOLS.md#get_student_profile) | 필요 |
| 현재 수강신청내역 기반 주간 시간표·강의실 | [get_my_timetable](docs/TOOLS.md#get_my_timetable) | 필요 |
| 연도·학기별 성적과 누적 평점·취득학점 | [get_grades](docs/TOOLS.md#get_grades) | 필요 |
| 중간·기말 시험시간표 | [get_exam_schedule](docs/TOOLS.md#get_exam_schedule) | 필요 |
| 본인 장학수혜내역 | [get_scholarship_history](docs/TOOLS.md#get_scholarship_history) | 필요 |
| 교과목명·연도·학기·캠퍼스별 수강편람 | [search_courses](docs/TOOLS.md#search_courses) | 필요 |

프로필의 이름·학번은 기본 제외합니다. 장학금 모집 공고·강의계획서·수강 정원 조회·수강신청은 지원하지 않습니다. 시험 조회기간 미등록은 시험 없음과 다릅니다.

### 일정·내보내기 (4개)

| 기능 | MCP 도구 | 학교 로그인 |
| --- | --- | --- |
| 현재 공개된 신촌·국제 학사일정 | [get_academic_calendar](docs/TOOLS.md#get_academic_calendar) | 불필요 |
| 오늘부터 1~90일 마감·반납일, 주간 시간표·선택적 시험 조회 | [get_my_schedule](docs/TOOLS.md#get_my_schedule) | LearnUs·ERP 필요 / 도서 포함 시 도서관 |
| LearnUs 마감·선택적 도서 반납일 ICS 텍스트 | [export_calendar_ics](docs/TOOLS.md#export_calendar_ics) | LearnUs 필요 / 도서 포함 시 도서관 |
| 주간 시간표의 반복 ICS 텍스트 | [export_timetable_ics](docs/TOOLS.md#export_timetable_ics) | ERP 필요 |

반복 시간표에는 사용자가 확인한 학기 기간·교시별 시각·제외일이 필요합니다. 휴강·공휴일 자동 반영, 캘린더 업로드·동기화는 지원하지 않습니다.

**지원하지 않는 작업:** 과제 제출, 게시글 작성·수정, 예약·취소·연장, 수강신청·결제. 조회와 텍스트 생성만 수행합니다.

## 빠른 시작

현재 소스 버전은 **0.5.0b2 공개 베타**입니다. [변경·호환성 안내](CHANGELOG.md)를 먼저 확인하세요. PyPI 게시·GitHub Release와는 별개이며 아래 소스 설치로 사용할 수 있습니다.
의존성은 `mcp>=1.28.1,<2`로 제한합니다. `uv sync --frozen`은 SDK 1.30.0을 사용하고,
별도 wheel 설치에서도 호환되지 않는 SDK 2.x는 선택되지 않습니다.

### 1. 실행 환경 준비

- Python **3.10 이상**: Linux/WSL의 3.10·3.11·3.12에서 오프라인 회귀와 wheel 설치를 검증했습니다. 실제 포털 검증은 3.12 중심이며 다른 OS/버전 전체 검증은 아닙니다.
- [uv](https://docs.astral.sh/uv/getting-started/installation/)와 Git.
- 로그인 조회: 유효한 본인 계정, Chromium, 필요시 브라우저 창을 표시할 데스크톱 환경.
- 도서 검색·공지·학사일정만 사용: 학교 자격 증명과 Chromium 설치 생략 가능. 공개 홈페이지 좌석 표는 로그인 없이 Chromium이 필요합니다.

Linux/macOS/WSL Bash 및 Windows PowerShell에서:

```bash
git clone https://github.com/YOONPYOGitHub/yonsei-portal-MCP.git
cd yonsei-portal-MCP
uv sync --frozen
# 로그인 도구 또는 홈페이지 좌석 조회를 사용할 때 설치
uv run --frozen playwright install chromium
```

Linux 공유 라이브러리 누락 시 `playwright install-deps chromium`이 필요할 수 있습니다.
이는 시스템 패키지 변경이므로 관리자에게 설치를 요청하세요. GUI가 없는 원격 서버에서는 headed 로그인 창을 사용할 수 없습니다.

### 2. 본인 자격 증명 설정

공개 조회만 사용하면 이 단계를 건너뜁니다. 로그인 조회에는 저장소 루트의 개인 `.env`에 아래 항목을 설정하세요.
[.env.example](.env.example)은 학교 로그인·MCP 실행 설정만 담습니다. 기존 `.env`를 덮어쓰지 마세요.
Azure/OpenAI/Anthropic/Gemini 항목은 선택적 개발용 [.env.llm.example](.env.llm.example)로 분리했습니다.
이 별도 예제 파일은 자동 로딩되지 않으며, **일반 MCP 사용에는 해당 LLM 키가 필요 없습니다.**

```dotenv
YONSEI_ID=<your-student-or-staff-id>
YONSEI_HEADED=true
YONSEI_STORAGE_STATE=.session/learnus.json
YONSEI_PASSWORD=""
```

ID 자리표시자와 빈 비밀번호 항목은 실제 본인 값으로 채우되 채팅·이슈·공개 MCP 설정·셸 명령 인자에 자격 증명을 넣지 마세요.
특수문자가 있는 값은 python-dotenv 문법에 맞춰 인용하세요. 로더는 ID와 비밀번호의 앞뒤 공백을 제거합니다.
Unix에서는 `.env`를 `chmod 600 .env`로 제한하고 Windows에서는 해당 사용자만 읽도록 파일 ACL을 설정하세요.
쿠키 디렉터리도 보호해야 합니다. 서버의 POSIX 쿠키 보호와 별개로 `.env` 권한은 사용자가 제한하고,
Windows에서는 개인 사용자 ACL을 적용하세요. 쿠키는 암호화되지 않은 인증정보입니다. [보안 정책](SECURITY.md).

### 기존 버전에서 업데이트할 때

모든 클라이언트의 해당 MCP 프로세스를 먼저 종료한 뒤 소스를 업데이트하고 `uv sync --frozen`을 실행하세요.
도구 이름은 유지하지만 잘못된 인자·범위·URL은 더 엄격하게 거절하므로 클라이언트의 도구 목록을 새로 불러옵니다.
기존 쿠키가 `Session storage must be an owned private regular file` 오류로 차단되면
본인 소유의 실제 파일인지 확인하고 해당 파일만 POSIX `0600` 권한으로 제한하세요.
심볼릭 링크·다른 소유자·알 수 없는 파일은 읽도록 우회하지 마세요. 필요하면 본인 쿠키만 비공개 위치로
옮긴 뒤 다시 로그인합니다. `.env`나 모든 세션을 일괄 삭제할 필요는 없습니다.
SDK와 의존성의 보안 수정은 잠금 파일에 포함되므로 소스만 바꾸고 기존 환경을 그대로 사용하지 마세요.

### 3. 연결 전 무인증 점검

저장소 루트에서 아래 명령을 실행하면 서버를 시작해 도구 목록만 읽습니다. 학교·외부 LLM 호출이나 브라우저 기동은 하지 않습니다.
정상 출력은 `34 tools available`입니다. 설치 이후 추가 네트워크 동기화를 하지 않도록 `--no-sync`를 사용합니다.

```bash
uv run --no-sync python - <<'PY'
import asyncio, os, sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def check():
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "yonsei_portal_mcp"],
        env={"PYTHON_DOTENV_DISABLED": "1", "YONSEI_ID": "", "YONSEI_PASSWORD": ""},
    )
    with open(os.devnull, "w") as errlog:
        async with stdio_client(params, errlog=errlog) as streams:
            async with ClientSession(*streams) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                assert len(tools) == 34
                print(f"{len(tools)} tools available")

asyncio.run(asyncio.wait_for(check(), timeout=30))
PY
```

위 heredoc은 Bash용입니다. PowerShell에서는 다음 무인증 등록 목록 점검을 사용하거나 아래 클라이언트에서 목록을 확인하세요.

```powershell
$env:PYTHON_DOTENV_DISABLED = "1"
uv run --no-sync python -c "import asyncio; from yonsei_portal_mcp.server import mcp; print(len(asyncio.run(mcp.list_tools())))"
Remove-Item Env:PYTHON_DOTENV_DISABLED
```

PowerShell 간단 점검은 Python 도구 등록만 확인하며 stdio 전송 검사는 아닙니다.
`uv run --no-sync yonsei-portal-mcp` 또는 `uv run --no-sync python -m yonsei_portal_mcp`를 직접 실행하면 stdin 요청을 기다립니다.
웹 주소가 표시되지 않아도 정상일 수 있습니다. 도구 인자를 셸 인자로 보내는 CLI가 아니며 아래 MCP 클라이언트로 호출합니다.

## 클라이언트 연결

### 모델 설정과 MCP 서버 설정은 다릅니다

일반 사용 흐름은 `질문 → 클라이언트의 LLM → MCP 조회 → 클라이언트의 LLM 답변`입니다.
Hermes·Claude Code/Desktop·VS Code가 사용하는 모델은 해당 앱에서 설정합니다.
서버는 `.env`의 학교 계정으로 허용된 정보를 조회할 뿐 다른 LLM을 추가 호출하지 않습니다.
`tests/llm/`의 데모를 별도로 실행할 때만 개발용 제공자 설정과 비용이 발생할 수 있습니다.

아래 예제의 `/absolute/path/to/uv`와 `/absolute/path/to/yonsei-portal-MCP`는 실제 설치 경로로 바꿉니다.
uv 경로는 Bash의 `command -v uv`, PowerShell의 `(Get-Command uv).Source`로 확인할 수 있습니다.
Windows JSON 경로는 `C:/Users/your-name/.../uv.exe`처럼 표기할 수 있습니다.
`--directory`는 실행 위치·상대 쿠키 경로를 고정하고, `--no-sync`는 클라이언트 시작 때 자동 설치를 하지 않도록 합니다. 먼저 빠른 시작의 `uv sync`를 완료해야 합니다.

### Claude Code

사용할 프로젝트에서 등록합니다. `local` 범위는 현재 프로젝트의 개인 설정이며 비밀값을 저장소에 공유하지 않습니다.

```bash
claude mcp add --transport stdio --scope local yonsei-portal -- /absolute/path/to/uv --directory /absolute/path/to/yonsei-portal-MCP run --frozen --no-sync yonsei-portal-mcp
claude mcp get yonsei-portal
```

Claude Code에서 `/mcp`로 연결 상태를 확인하고 필요한 도구 호출만 승인하세요.
해제할 때는 `claude mcp remove yonsei-portal --scope local`을 사용합니다.
[Claude Code 공식 MCP 안내](https://code.claude.com/docs/en/mcp).

### Claude Desktop

앱의 개발자 설정에서 로컬 MCP 설정을 열고 기존 서버 설정과 병합합니다. 설정 변경 후 앱을 완전히 종료·재실행하세요.
예제는 클라이언트별 `cwd` 지원에 의존하지 않습니다.

```json
{
  "mcpServers": {
    "yonsei-portal": {
      "command": "/absolute/path/to/uv",
      "args": ["--directory", "/absolute/path/to/yonsei-portal-MCP", "run", "--frozen", "--no-sync", "yonsei-portal-mcp"]
    }
  }
}
```

서버와 클라이언트가 서로 다른 OS에 있으면 해당 OS에서 실행 가능한 명령을 설정해야 합니다.
예를 들어 Windows Desktop에서 WSL의 `/home/...` 실행 파일을 직접 실행할 수는 없습니다.
WSL 설치는 VS Code Remote WSL 또는 WSL 안의 Claude Code와 사용하는 구성을 우선 권장합니다.
네이티브 Windows·macOS Desktop에서의 계정별 로그인은 별도 검증이 필요합니다.

### VS Code

워크스페이스 `.vscode/mcp.json`에서 다음 구조를 사용합니다. 경로가 개인마다 다르면 사용자 설정에 등록하세요.

```json
{
  "servers": {
    "yonsei-portal": {
      "type": "stdio",
      "command": "/absolute/path/to/uv",
      "args": ["--directory", "/absolute/path/to/yonsei-portal-MCP", "run", "--frozen", "--no-sync", "yonsei-portal-mcp"]
    }
  }
}
```

`MCP: List Servers`에서 서버를 시작하고 도구 목록을 확인하세요. Remote WSL/SSH에서는 서버를 실행할 쪽의 워크스페이스 또는 원격 사용자 설정을 사용합니다.
설정을 신뢰하기 전에 실행 명령을 검토하세요. [VS Code 공식 MCP 안내](https://code.visualstudio.com/docs/copilot/customization/mcp-servers).

### Hermes

현재 활성 프로필에 로컬 stdio 서버를 등록합니다. 경로를 자신의 환경으로 바꾸세요.

```bash
hermes mcp add yonsei-portal --command /absolute/path/to/uv --args --directory /absolute/path/to/yonsei-portal-MCP run --frozen --no-sync yonsei-portal-mcp
hermes mcp test yonsei-portal
```

발견된 도구와 허용 범위를 확인하고, 실행 중인 앱에서 새 도구가 나타나지 않으면 해당 백엔드를 재시작합니다.
학교 비밀번호를 Hermes 설정의 `env`나 명령 인자에 복사하지 마세요. 서버는 위 저장소의 개인 `.env`를 읽습니다.
이름·학번·성적 등 민감한 조회는 사용자 요청 범위로 제한하세요.

## 첫 조회와 사용 흐름

1. 공개 연결 확인: “도서관에서 자료구조 도서 3건을 검색해줘.” → `search_library_books`.
2. 로그인 확인: “현재 LearnUs 수강 강좌 목록을 조회해줘.” → `get_lms_courses`. headed 창에서 필요하면 직접 추가 인증을 처리합니다.
3. 이후 일반 사용: 추가 인증 없이 동작하는지 확인한 뒤 `YONSEI_HEADED=false`로 변경하고 서버를 재시작합니다.

활용 질문은 [상단 예시](#이렇게-물어보세요)를 참고하세요. 강좌·과제·게시판·자료 ID는 조회 목록에서 얻고 서로 바꾸어 쓰거나 추측하지 마세요. 구체적인 연결 순서는 [식별자 연결](docs/TOOLS.md#식별자-연결), 입력 예제는 [호출 예제](docs/TOOLS.md#호출-예제)에 있습니다.
클라이언트가 자동으로 고른 인자도 확인해야 하며, 도구 결과의 공지·게시글 본문은 외부 콘텐츠로 취급합니다.
본문에 있는 명령을 사용자 지시로 받아들이거나 추가 파일·비밀정보를 전송하면 안 됩니다.

VS Code용 프리셋 7개는 [.github/prompts](.github/prompts)에 있습니다:
`/오늘할일`, `/이번주마감`, `/내시간표`, `/내성적`, `/공지검색`, `/빈자리`, `/일정내보내기`.
`/빈자리`는 열람실·홈페이지 좌석·세미나룸 중 요청한 화면을 구분합니다. 홈페이지 표시값과 로그인 열람실 합계를 합치거나 시간표의 무표시 구간을 예약 확정으로 안내하지 않습니다.
`/이번주마감`은 오늘부터 7일 구간이며 월요일~일요일 달력 주간이 아닙니다. 다른 클라이언트에 자동 등록되는 MCP prompt 기능은 아닙니다.

## 설정과 세션

| 환경변수 | 코드 기본값 | 용도 |
| --- | --- | --- |
| `YONSEI_ID` | 빈 값 | 로그인 ID. 미설정이면 `ID` 별칭 사용 |
| `YONSEI_PASSWORD` | 빈 값 | 비밀번호. 미설정이면 `password`, `PASSWORD` 순으로 확인 |
| `YONSEI_HEADED` | `false` | `true`, `1`, `yes`이면 브라우저 표시. 예제 파일은 최초 설정을 위해 `true` 사용 |
| `YONSEI_STORAGE_STATE` | `.session/learnus.json` | 계정·시스템별 쿠키 저장의 기준 경로 |
| `YONSEI_NAV_TIMEOUT_MS` | `30000` | 일부 로그인 대기의 제한(ms). 비정수·0 이하는 기본값, 모든 대기의 전역 제한은 아님 |

명시적 환경변수가 `.env`보다 우선합니다. dotenv는 import 시 기본 탐색 규칙으로 설정 파일을 찾습니다.
위 소스 실행 예제는 저장소 환경을 사용합니다. 패키지를 따로 설치하거나 다른 위치에서 실행할 때는 환경변수를 직접 준비하고 설정 파일이 어디서 읽히는지 확인해야 합니다.
프로그램이 모든 설치 방식에서 작업 디렉터리의 `.env`를 반드시 읽는다고 가정하지 마세요. 설정 변경 후에는 서버를 재시작합니다.

기본 쿠키 경로는 `.session/<account-hash>/learnus/learnus.json`,
`.session/<account-hash>/library/library.json`, `.session/<account-hash>/erp/erp.json`입니다.
`YONSEI_STORAGE_STATE`의 부모 경로와 LearnUs 파일명이 사용되며, 해시는 계정 ID의 SHA-256입니다.
해시는 암호화가 아닙니다. 기존 공용 쿠키는 자동 이관하지 않습니다. 재시작은 메모리 캐시를 비우지만 저장 쿠키와 학교 세션을 자동 철회하지 않습니다.
쿠키 문제를 초기화하려면 모든 클라이언트 서버를 종료한 뒤 해당 계정·시스템의 쿠키 파일만 비공개 위치로 옮기고 다시 로그인하세요.
여러 클라이언트 프로세스 사이에는 잠금이 공유되지 않으므로, 동시 사용이 필요하면 별도의 저장 기준 경로를 지정하세요.

`RUN_LIVE_PORTAL`, `RUN_LIVE_LLM`, `LLM_PROVIDER`와 각 API 키는 **개발/테스트 하니스 설정**입니다.
이 게이트를 `0`으로 두어도 MCP 클라이언트가 정상 도구를 호출하면 포털 조회는 실행됩니다. 서버 전체의 네트워크 차단 스위치가 아닙니다.

## 개인정보와 제한

- 본인 계정 전용 로컬 프로세스로 사용하세요. 원격 공개 서비스·다중 사용자 계정 격리·서버 측 도구별 사용자 승인 UI는 제공하지 않습니다.
- 프로필 이름·학번, 성적 피드백은 기본 제외하지만 학과·성적·출석·대출·게시글 내용 자체는 개인정보일 수 있습니다. 연결한 LLM의 보관·학습·국외 처리 정책을 확인하세요.
- 반환 결과·ICS·원시 로그·스크린샷·쿠키를 공개 이슈나 저장소에 첨부하지 마세요. SDK/예외 처리의 일부 비식별화가 모든 출력에서 개인정보가 제거됨을 보장하지 않습니다.
- 개인 이력은 기본 표시 범위입니다. 도서관 날짜·페이지 입력은 미지원이며 `count=0`을 전체 과거 이력 없음으로 단정할 수 없습니다.
- 정상 빈 응답과 조회 실패를 구분합니다. `isError=true`, 파싱 실패, 인증 실패를 0건·0점·0석으로 요약하지 마세요.
- 공개 좌석은 API 키가 아니라 홈페이지 표시값을 제공합니다. 화면 자체의 합계 모순과 실제 착석 가능 여부는 별개입니다. 지원하지 않는 필터와 미확인 화면은 오류이며 임의의 빈 결과로 바꾸지 않습니다. 지원 인자는 [도구 참조](docs/TOOLS.md)를 따르세요.
- MIT 라이선스는 이 소스 코드에 적용됩니다. 학교 공지·강의자료·학생 데이터의 재배포 권한까지 부여하지 않습니다. [LICENSE](LICENSE).

## 문제 해결

| 증상 | 확인할 사항 |
| --- | --- |
| 실행 파일 없음/`ENOENT` | 클라이언트가 보는 OS의 uv 절대 경로, 저장소 위치, 먼저 완료한 `uv sync` 확인 |
| `No module named mcp.server.fastmcp` | 이전 설치에 SDK 2.x가 남았는지 확인. 현재 소스로 업데이트한 뒤 `uv sync --frozen`으로 동기화 |
| `No module named yonsei_portal_mcp` | 다른 Python을 쓰는지 확인. 예제의 `uv --directory ... run --no-sync`로 실행 |
| `Executable doesn't exist`/Chromium 오류 | 같은 환경에서 `uv run --frozen playwright install chromium`, Linux 시스템 의존성 확인 |
| headed 실행의 DISPLAY 오류 | 로컬 데스크톱/WSLg 등 창을 띄울 수 있는 환경 필요. `false` 전환은 추가 인증을 우회하지 않음 |
| `AUTH_REQUIRED` | 자리표시자·설정 탐색·환경변수 우선순위 확인. 실행 중 설정이 바뀌었으면 서버 재시작 |
| `AUTH_FAILED`/`MFA_REQUIRED` | 학교 웹 로그인과 계정 상태 확인, 브라우저에서 필요한 추가 인증 직접 수행. 자동 반복 로그인 금지 |
| `SESSION_EXPIRED`/`SCRAPE_FAILED` | 학교 지연·권한·DOM 변경 가능. 원문 확인 후 재시도하고 계속되면 비식별 오류 종류와 버전만 보고 |
| 미지원 이력 인자 오류 | 날짜·페이지를 제거하고 현재 `tools/list` 새로고침. 삭제된 인자를 조용히 무시하지 않음 |
| 도구 목록이 예전과 다름 | 클라이언트 캐시·연결한 저장소·소스 commit 확인 후 서버 재시작 |
| TLS 오류 | 인증서 검증을 끄지 마세요. 시스템 시각·프록시·학교 인증서 변화 확인 후 비밀값 없는 오류 유형 보고 |

일부 오류에는 `[CODE]` 문자열이 있지만 모든 실패가 구조화된 오류 코드로 통일돼 있지는 않습니다.
일반 연결 확인은 `tools/list`, 실제 공개 도구 호출, 본인 로그인 조회 순으로 좁혀 확인하세요.
네트워크 조회를 원하는 경우 MCP Inspector도 사용할 수 있습니다:

```bash
npx @modelcontextprotocol/inspector uv --directory /absolute/path/to/yonsei-portal-MCP run --frozen --no-sync yonsei-portal-mcp
```

Node.js와 패키지 다운로드가 필요한 별도 도구입니다. Inspector도 민감한 결과를 표시할 수 있습니다.

## 업데이트와 개발

| 필요한 내용 | 문서 |
| --- | --- |
| 실제 질문·답변 캡처·결과 해석 | [docs/USAGE.md](docs/USAGE.md) |
| 34개 도구의 인자·반환값·캐시·예제 | [docs/TOOLS.md](docs/TOOLS.md) |
| 개발 환경·테스트·LLM 하니스·릴리스 준비 | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| 기여 절차·회귀 테스트·공개 PR 원칙 | [CONTRIBUTING.md](CONTRIBUTING.md) |
| 비밀정보 보호·취약점 비공개 신고 | [SECURITY.md](SECURITY.md) |
| MIT 적용 범위·학교 자료·의존성 고지 | [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) |
| 내부 구조·제약·미완료 작업 | [DESIGN.md](DESIGN.md) |
| 버전별 변경과 호환성 주의사항 | [CHANGELOG.md](CHANGELOG.md) |

소스 업데이트는 서버 종료 후 로컬 변경을 보존하고 `git pull --ff-only`, `uv sync --frozen`을 실행한 뒤 재시작합니다.
Playwright 버전이 바뀌면 해당 환경의 Chromium 설치도 갱신하세요. 공개 지원 여부는 설치된 서버의 `tools/list`와 해당 버전 문서를 기준으로 합니다.
