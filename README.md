# Yonsei Portal MCP

연세대학교 **LearnUs(LMS)** 데이터를 LLM이 조회할 수 있게 해주는 **읽기 전용 MCP 서버**입니다.
Playwright(Chromium)로 연세포털 SSO 로그인을 자동화하고, 강좌·마감일·공지·출석 정보를
구조화된 JSON으로 제공합니다.

> ⚠️ 본 서버는 **조회(read-only)** 전용입니다. 과제 제출·성적 변경 등 쓰기 작업은 하지 않습니다.
> 자격 증명과 세션 쿠키는 로컬에만 저장되며 외부로 전송되지 않습니다.

## 제공 도구

| 도구 | 로그인 | 설명 |
| --- | --- | --- |
| `get_lms_courses` | 🔒 | 수강 중인 강좌 목록 (학수번호, 교수, 진도율, 출석 URL 포함) |
| `get_lms_deadlines` | 🔒 | 다가오는 과제/활동 마감일 (LearnUs 달력 '예정된 할 일') |
| `get_lms_notices` | 🔒 | 공지사항 (`scope`: `all` / `course` / `platform`) |
| `search_notices` | 🔒 | 공지 통합 검색 (키워드 AND 매칭, `scope`/`limit`) |
| `get_notice` | 🔒 | 단일 공지/게시글 본문 전체 |
| `get_lms_attendance` | 🔒 | 특정 강좌의 주차별 출석/학습 현황 (`course_id` 필요) |
| `get_lms_course_materials` | 🔒 | 특정 강좌의 주차별 학습활동/자료 목록 (`course_id` 필요) |
| `get_lms_overview` | 🔒 | 강좌 + 마감일 + 최근 강좌 공지 종합 요약 |
| `get_my_loans` | 🔒 | 도서관 개인 대출현황 (반납예정일·연장횟수 등) |
| `export_calendar_ics` | 🔒* | 마감일·반납예정일을 iCalendar(.ics)로 내보내기 |
| `get_library_seats` | 🔓 | 도서관 좌석 집계 (건물군 × 좌석유형, **브라우저 불필요**) |
| `get_library_seat_rooms` | 🔒 | 중앙도서관 **열람실별** 실시간 좌석현황 |
| `get_student_profile` | 🔒 | 학사행정(ERP) 학생 본인 프로필·학기·학점 요약 |
| `get_my_timetable` | 🔒 | 학사행정(ERP) 수강신청내역 기반 본인 시간표 (요일·교시 파싱) |
| `get_grades` | 🔒 | 학사행정(ERP) 전체 성적 이력 (이력 없으면 정상 빈 구조) |

> 🔒 = 연세포털/도서관 로그인 필요 · 🔓 = 로그인 불필요

> \*`export_calendar_ics(include_loans=False)` 로 두면 도서관 로그인 없이 LMS 마감일만 내보냅니다.
> `get_library_seats` 는 공개 JSON(`/seat/info`)을 쓰는 무로그인·무브라우저 도구입니다.

> 학사행정(ERP) 도구(`get_student_profile`·`get_my_timetable`·`get_grades`)는
> `underwood1.yonsei.ac.kr` SSO 로그인 후 WebSquare 화면의 JSON 응답을 캡처합니다.
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

```bash
pip install yonsei-portal-mcp
playwright install chromium          # 로그인 도구를 쓰려면 필요
# 또는 격리 실행:
uvx --from yonsei-portal-mcp yonsei-portal-mcp
```

> ⚠️ 로그인 기반 도구(LMS·대출현황·열람실 좌석)는 Playwright Chromium이 필요합니다
> (`playwright install chromium`). 무로그인 `get_library_seats` 만 쓴다면 브라우저
> 없이도 동작합니다.

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

로그인에 성공하면 세션 쿠키가 `.session/storage_state.json` 에 저장되어 이후
재실행 시 재로그인 없이 재사용됩니다. (`YONSEI_HEADED=false` 로 무인 실행 가능)

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
확인할 수 있는 하니스가 `tests/llm/` 에 있습니다. 목업/픽스처는 제거되어
**실제 연세포털에 로그인해 실데이터로만** 검증합니다. 추가 의존성은 선택
그룹으로 분리되어 있습니다:

```bash
uv sync --extra llm     # openai / anthropic / pytest 등 테스트 전용 의존성
```

LLM 제공자는 `.env` 의 `LLM_PROVIDER` 로 고릅니다
(`azure-openai` | `openai` | `anthropic`). 각 제공자 설정 키는
`.env.example` 의 주석을 참고하세요. Azure OpenAI는 **keyless(APIM)** 와
**AOAI 키** 두 방식을 입력한 키에 따라 자동 판별합니다
(`AZURE_OPENAI_API_KEY` 가 비어 있으면 APIM 구독키로 대체).

> ⚠️ 모든 하니스(데모/시나리오/pytest)는 **실제 포털 로그인 + 본인 학사정보를
> 클라우드 LLM으로 전송**합니다. 안전장치로 `.env` 에 `RUN_LIVE_LLM=1` 을
> 설정해야만 실행됩니다.

### 대화 데모 (`tests/llm/demo.py`)

```bash
# 한 번에 질문 1개
RUN_LIVE_LLM=1 uv run python -m tests.llm.demo "이번 학기 시간표 알려줘"

# 인터랙티브 채팅(계속 타이핑; 빈 줄 또는 exit 로 종료)
RUN_LIVE_LLM=1 uv run python -m tests.llm.demo --chat

# 제공자 강제 지정
RUN_LIVE_LLM=1 uv run python -m tests.llm.demo --provider azure-openai --chat
```

### 시나리오 일괄 검증 (`tests/llm/scenarios.py`)

```bash
# 13개 한국어 질의를 실제 포털에 붙여 도구 선택을 채점
RUN_LIVE_LLM=1 uv run python -m tests.llm.scenarios
```

### pytest

```bash
# 실제 포털+LLM E2E 테스트 (RUN_LIVE_LLM=1 미설정 시 skip)
RUN_LIVE_LLM=1 uv run pytest tests/llm -v
```

## 클라이언트 등록

### Claude Desktop (`claude_desktop_config.json`)

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
| `/오늘할일` | 마감 임박 과제 + 최근 강좌 공지 정리 | `get_lms_overview` |
| `/이번주마감` | 다가오는 모든 과제/활동 마감일 | `get_lms_deadlines` |
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
description: 오늘 처리할 과제 마감과 최근 강좌 공지를 정리합니다.
---
`get_lms_overview` 도구를 호출해서, 마감이 임박한 순으로 과제를 정리하고
최근 강좌 공지에서 중요한 항목만 3줄 이내로 요약해줘. 마감이 지난 항목은 제외.
```

예) `.github/prompts/공지검색.prompt.md` (인자 사용):

```markdown
---
mode: agent
description: 키워드로 LearnUs 공지를 통합 검색합니다.
---
`search_notices` 도구를 `query="${input:키워드}"`, `scope="all"` 로 호출하고,
결과를 제목·강좌·날짜 표로 정리해줘. 결과가 없으면 그렇다고 답해줘.
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
- 개인정보(학번·이름)는 도구 응답에서 추출 대상에서 제외했습니다.

## 한계 / 알려진 사항

- 최초 로그인이나 2단계 인증/보안문자 발생 시 `YONSEI_HEADED=true` 로 직접 처리 필요.
- LearnUs 주간 강의시간표 그리드는 비어 있는 경우가 많아 MVP에서 제외했습니다.
- 사이트 DOM 변경 시 스크래퍼 셀렉터 갱신이 필요할 수 있습니다.
