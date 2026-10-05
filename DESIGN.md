# 연세대학교 포털 MCP 설계

0.6.0b3 구현의 구조와 개발 제약을 설명합니다. 설치는 [README](README.md),
도구별 계약은 [도구 참조](docs/TOOLS.md), 검증·릴리스 절차는 [개발 가이드](docs/DEVELOPMENT.md)를 참고하세요.

## 1. 범위와 상태

개인용 **읽기 전용 stdio MCP 서버**입니다. 로그인과 조회용 검색 외에 예약·취소·연장·신청·제출·결제를 실행하지 않습니다.
UI, 다중 사용자 서비스, 쓰기 도구는 현재 범위가 아닙니다.
공개 도구는 LearnUs 15개, 도서관 10개, ERP 6개, 일정 4개, 공개 공지 3개로 총 38개입니다. 진단 CLI `doctor`는 MCP 도구가 아닙니다.
내부 함수·실험 코드·포털 메뉴의 존재를 공개 지원으로 취급하지 않습니다.

## 2. 구현 구조

```mermaid
flowchart LR
    Client[MCP 클라이언트 / LLM] -->|stdio| Server[PortalMCP 도구]
    Server --> Cache[프로세스 내 TTL 캐시]
    Cache --> Sessions[시스템별 BrowserSession]
    Cache --> HTTP[httpx 공개 조회]
    Cache --> Anonymous[익명 Chromium / 홈페이지 좌석 표]
    Sessions --> LMS[LearnUs / Moodle]
    Sessions --> ERP[ERP / cpr eXBuilder]
    Sessions --> Library[도서관 / 열람실]
    HTTP --> Public[공개 검색 / 복본 / 공지 / 학사일정]
    Sessions --> Cookies[로컬 계정별·시스템별 쿠키 파일]
```

| 구현 파일 | 책임 |
| --- | --- |
| [src/yonsei_portal_mcp/server.py](src/yonsei_portal_mcp/server.py) | 도구 등록, 입력·개인정보 옵션, 캐시 키, 종료 훅 |
| [src/yonsei_portal_mcp/session.py](src/yonsei_portal_mcp/session.py) | 브라우저 지연 기동, 인증·잠금·재시도·정리 |
| [src/yonsei_portal_mcp/config.py](src/yonsei_portal_mcp/config.py) | 환경변수 우선 설정 로딩 |
| [src/yonsei_portal_mcp/cache.py](src/yonsei_portal_mcp/cache.py) | 도구·계정·인자별 TTL 캐시 |
| [src/yonsei_portal_mcp/httpclient.py](src/yonsei_portal_mcp/httpclient.py) | 공개 HTTP, TLS 검증, HTML 동일 출처 리다이렉트 제한 |
| [src/yonsei_portal_mcp/scrapers/learnus.py](src/yonsei_portal_mcp/scrapers/learnus.py) | 한국어 수집, 강좌·마감·공지·자료·과제·성적부·강좌 이력 |
| [src/yonsei_portal_mcp/scrapers/boards.py](src/yonsei_portal_mcp/scrapers/boards.py) | 강좌 게시판·선택 페이지·제한된 페이지 제목 검색, 작성자·본문·숨김/링크 없는 제목 제외 |
| [src/yonsei_portal_mcp/scrapers/library.py](src/yonsei_portal_mcp/scrapers/library.py) | 도서·공지·개인 대출/예약/이력·열람실 |
| [src/yonsei_portal_mcp/scrapers/erp.py](src/yonsei_portal_mcp/scrapers/erp.py) | 메뉴 조작 후 조회 JSON 캡처·정규화 |
| [src/yonsei_portal_mcp/scrapers/seats.py](src/yonsei_portal_mcp/scrapers/seats.py) | 익명 브라우저의 실제 홈페이지 좌석 표·표시 모순 검증 |
| [src/yonsei_portal_mcp/scrapers/facilities.py](src/yonsei_portal_mcp/scrapers/facilities.py) | 도서관 SSO 시설 선택 UI·시간표 표시 조회, 변경 요청 차단 |
| [src/yonsei_portal_mcp/scrapers/academic.py](src/yonsei_portal_mcp/scrapers/academic.py) | 공개 학사일정의 월별 원문 날짜·제목 |
| [src/yonsei_portal_mcp/scrapers/university.py](src/yonsei_portal_mcp/scrapers/university.py) | 등록된 대학·대학원 공개 공지 목록·본문·첨부 링크, 소스/ID 검증 |
| [src/yonsei_portal_mcp/doctor.py](src/yonsei_portal_mcp/doctor.py) | 비밀값 비노출 로컬 설치·stdio·선택적 빈 브라우저 진단 |
| [src/yonsei_portal_mcp/ics.py](src/yonsei_portal_mcp/ics.py) | 일정 합성·마감 ICS·명시적 입력 기반 반복 ICS |

ERP 화면은 cpr/eXBuilder의 `.clx.js` 기반입니다.
학교 대기열과 실제 조회 UI를 거쳐 `*.do` 응답을 읽으며, 대기열 우회나 쓰기 API 직접 호출은 하지 않습니다.
공개 HTTP는 certifi와 동봉된 Sectigo 중간 인증서로 TLS를 검증합니다. HTML 리다이렉트는 같은 출처 HTTPS로 최대 5회 요청합니다.

## 3. 데이터 처리 원칙

공개 입력의 기준은 `tools/list`입니다. 반환 필드·페이지 범위·캐시는 [도구 참조](docs/TOOLS.md)에서 관리합니다.

- 오류·로딩·미확인 상태를 정상 0건이나 0점으로 바꾸지 않습니다. 빈 결과는 원문의 명시적 표식으로 확인합니다.
- 필터는 요청 전송뿐 아니라 선택된 조건과 응답 행을 검증합니다. 모든 도구는 지원하지 않는 추가 인자를 SDK 처리 전에 거절하며 조회 범위를 조용히 넓히지 않습니다.
- 원문 전체 건수·출력 제한·로컬 잘림·후속 페이지를 구분합니다. 페이지 사이 변경 가능성이 있으므로 ID 중복과 수집 건수를 대조해야 합니다.
- 달력의 진도/수료와 제출 과제, LMS 점수와 ERP 성적, 자료 건수와 복본 수, 좌석 잔여와 배정 가능을 구분합니다.
- 공개 좌석은 무로그인 Chromium으로 실제 홈페이지 표를 읽습니다. API 키 해석 대신 화면 전체/사용/잔여 값을 보존하고 합계 모순을 표시합니다. `display_verified`는 화면 일치이며 실제 착석 보장은 아닙니다.
- 시설 현황은 도서관 SSO 후 444번 포트 UI의 날짜·건물·그룹·시설·사용시간 선택을 대조합니다. 시간대 클릭·예약 제출을 하지 않고 시간표 표시만 반환하며, 인증 이후 시설 서버의 변경 요청은 차단합니다.
- 공지의 이미지 수와 이미지 내용 미추출 안내를 반환합니다. LearnUs 이미지 전용 본문은 텍스트가 비어도 유효하지만, 본문 구조가 없거나 콘텐츠가 준비되지 않은 화면은 오류입니다.
- LearnUs는 `lang=ko`와 실제 DOM 언어·대상 ID를 검증합니다. ERP 성적의 `dsSgra100`은 과목, `dsSgra120`은 학기 데이터입니다.
- 개인정보 옵션은 기본 최소화하되 도구 응답 전체가 비식별화됐다고 가정하지 않습니다. 게시판 목록의 본문 제외는 다른 도구 호출을 차단하는 권한 장치가 아닙니다.
- 학사 시각은 KST 기준, 수집시각은 오프셋을 포함한 ISO8601입니다. 날짜만 있는 마감에 임의 시각을 넣지 않습니다.
- 반복 시간표 ICS는 사용자가 확인한 기간·교시·제외일로 생성하며 미지원 시간 표현을 부분 결과로 숨기지 않습니다.

### 공지 소스와 페이지 계약

- 공개 공지는 고정 등록부의 `university`·`graduate`·`ai_graduate`만 지원합니다. 대학 공지·일반대학원 교내공지·인공지능융합대학원 공지는 적용 범위가 다릅니다. 임의 URL·게시판 탐색·개별 과정의 규정 자동 추론은 하지 않습니다.
- `get_university_notices`의 `page`는 서버 페이지(1~1000), `limit`은 현재 페이지 출력 상한(기본 10, 최대 100)입니다. `truncated`이면 `same_page_request`로 먼저 확장하고 나서 `next_request`를 사용합니다. 확대된 응답 및 페이지별 고정글 중복을 구분하며 `has_next=null`을 종료로 바꾸지 않습니다. `complete_history=false`와 확인된 원문 `total`은 전체 수집 완료 주장이 아닙니다.
- `get_university_notice`는 등록된 소스·목록 ID로 주소를 구성하고 원문 식별자를 확인합니다. 첨부는 허용 링크만 반환하며 다운로드·이미지 OCR·첨부 내용 추출은 하지 않습니다. 본문은 신뢰할 수 없는 외부 콘텐츠입니다.
- `get_lms_board_posts`는 page 1~100과 활성 페이지·연속된 다음 링크를 검증합니다. `next_request`로 한 페이지씩 이어 읽으며 마지막 페이지를 본 것만으로 전체 수집을 주장하지 않습니다.
- `search_lms_board_posts`는 선택 게시판 첫 페이지부터 기본 3·최대 10페이지의 링크 있는 **제목만** AND 검색합니다. 기본 limit 20·최대 50이며 본문·작성자·숨김 행은 검색하지 않습니다. 수집 페이지·고유 글 수·일치 수·반환 잘림·후속 페이지를 따로 표시합니다. 후속 요청은 `get_lms_board_posts` 목록 조회이지 검색 자동 재개가 아닙니다.
- 기존 `get_lms_notices`·`search_notices`의 홈 공지 범위는 유지합니다. 본문 조회는 선택한 반환 URL의 `get_notice` 호출로 분리합니다.

## 4. 설정·세션·운영

### 인증과 저장

- LearnUs는 `a.btn-sso` 클릭 후 통합인증 폼, ERP는 별도 SSO, 도서관은 자체 SSO 로그인 폼을 사용합니다. 브라우저는 사용자에게 허용된 읽기 흐름만 재현합니다.
- 명시적 환경변수가 설정 파일보다 우선합니다(`override=False`). 설정 변경 뒤에는 서버를 재시작해야 합니다.
- 쿠키는 `YONSEI_STORAGE_STATE`의 부모 경로 아래 `SHA256(계정 ID)/시스템/파일명`으로 분리합니다. 기존 공용 쿠키는 자동 이관·재사용하지 않습니다.
- 파일명 해시는 암호화가 아닙니다. 자격 증명과 쿠키는 민감한 로컬 파일이며 Git에 포함하지 않습니다. OS 키체인·쿠키 암호화는 미구현입니다.
- POSIX에서는 전용 계정/시스템 디렉터리와 쿠키 파일을 제한 권한으로 관리하고 임시 파일·원자적 교체로 저장합니다. 심볼릭 링크·소유권/권한이 안전하지 않은 쿠키는 거절합니다. Windows에서는 사용자 ACL도 별도로 적용하고 여러 프로세스의 같은 쿠키 경로 공유는 피합니다.
- 프로필의 이름·학번과 성적 피드백은 기본 제외합니다. 성적·출석·도서명 자체는 여전히 개인정보이며 MCP 클라이언트/LLM에 전달됩니다.
- `RUN_LIVE_PORTAL`/`RUN_LIVE_LLM`은 테스트 하니스의 실행 게이트입니다. 공개 MCP 도구 호출을 차단하는 서버 정책이나 네트워크 방화벽이 아닙니다.

### 생명주기와 오류

- 브라우저는 지연 기동하고 시스템별 잠금으로 조회를 직렬화합니다. 재시도 중에도 잠금을 유지하며 시작 실패·세션 무효화·서버 종료에서 브라우저와 드라이버를 정리합니다.
- ERP 진입에서는 로그인 폼과 인증된 셸 중 먼저 준비되는 화면을 기다립니다. 이미 인증됐으면 자격 증명을 재제출하지 않습니다. 별도로 관찰된 최초 프로필 호출의 간헐 실패 원인까지 확정된 것은 아닙니다.
- 자격 증명 없음/실행 중 설정 변경은 `AUTH_REQUIRED`, 로그인 실패는 `AUTH_FAILED`, 추가 인증 필요는 `MFA_REQUIRED`입니다. 이 오류는 자동 인증 재시도를 하지 않습니다.
- 입력 검증·파싱 오류는 재인증이나 쿠키 무효화 사유로 사용하지 않습니다. 인증 만료 등 재시도 가능한 오류와 구분하며, 구체적인 예외 및 정리 동작은 세션 회귀검사로 유지합니다.
- `UPSTREAM_TIMEOUT` 타입은 정의돼 있으나 모든 HTTP 오류가 그 코드로 변환되거나 지수 백오프되는 것은 아닙니다. `YONSEI_NAV_TIMEOUT_MS`도 모든 대기시간을 통제하지 않습니다.
- 브라우저 종료는 학교 측 로그아웃·쿠키 철회를 의미하지 않습니다. 전역 오류 비식별화나 모든 개인정보 마스킹이 완성됐다고 가정하지 않습니다.

### 진단과 배포 검증

`__main__.py`는 `doctor`를 먼저 분기하고 인자 없는 기존 MCP stdio 실행을 유지합니다. 진단 기본값은 현재 폴더 `.env`의 존재만 검사하며 내용·쿠키를 읽지 않습니다. 명시적 `--env-file`만 내용 검사하고 자격 증명은 존재 여부·출처만 출력합니다. 상위 폴더 탐색·변수 치환·환경 변경·인증 확인은 하지 않습니다.
설치·버전·Chromium 실행 파일과 격리된 자식 프로세스의 `initialize → tools/list`를 확인하며 포털·LLM 호출은 없습니다. `--browser`만 임시 Chromium의 `about:blank`를 시작합니다. 원시 예외·서버 stderr·개인 경로·비밀값은 진단 출력에서 제외합니다. 종료 코드 0/1/2는 각각 필수 로컬 점검 성공/필수 점검 실패/인자·지정 설정 오류이며 기본 모드에서 자격 증명·Chromium은 선택 사항입니다. 이는 보안 감사·실제 학교 접속 검증이 아닙니다.
CI는 Linux 3.10·3.11·3.12, macOS 3.11, 네이티브 Windows 3.11의 5개 조합으로 구성합니다. 네이티브 Windows의 오프라인 회귀·빌드·독립 wheel 설치 성공을 원격 CI에서 확인했으며, Windows 로그인·NTFS ACL 검증은 완료하지 않았습니다. 별도 Security workflow는 push·PR·주간·수동 실행에서 잠금 런타임 의존성 감사와 비식별 Gitleaks 이력/공개 트리 검사를 구성합니다. 구성과 실행 증거는 [개발 가이드](docs/DEVELOPMENT.md)·[검증 기록](docs/VALIDATION.md)에서 구분합니다.

### 캐시와 호출 부하

| 데이터 | 현재 TTL |
| --- | --- |
| 강좌·자료·과거강좌·ERP 프로필/시간표/성적·공식 학사일정 | 30분 |
| 마감·공지 목록·과제 상태·성적부·게시판·도서 검색/복본·개인 대출/예약/이력·시험·장학수혜 | 5분 |
| LearnUs·도서관 공지 본문 | 30분 |
| 공개 학교·대학원 공지 목록/본문·LearnUs 게시판 페이지/제목 검색 | 5분 |
| 공개 좌석·열람실 | 60초 |

캐시 키는 계정과 조회 인자를 반영하고 공개 데이터는 계정이 필요 없습니다.
동일 이벤트 루프의 동일 키 진행 중 요청은 합쳐 처리하며 완료 캐시는 최대 256항목입니다. 읽기/쓰기 시 만료 항목을 정리합니다. 캐시 clear 이전의 진행 중 결과는 캐시를 다시 채우지 못합니다. TTL은 재사용 기준이지 백그라운드 개인정보 삭제 시한은 아닙니다. 공통 최소 호출 간격과 HTTP 백오프는 미구현입니다.
시스템별 잠금만으로 모든 서버 호출의 레이트리밋이 보장된다고 설명하지 않습니다.

## 5. 미완료 작업

아래는 지원 기능이 아니라 검증 후 범위를 정할 개발 후보입니다.

| 항목 | 현재 상태와 필요한 근거 |
| --- | --- |
| 도서관 이력 날짜·후속 페이지 | 내부 실험만 존재. 실제 비어 있지 않은 이력으로 날짜별 변화·페이지 합계·중복 대조 필요 |
| 강의계획서 | `.crf` 경로만 확인. 뷰어 본문·권한·과목 식별자 검증 필요 |
| 장학 공고·마감 통합 | 등록된 공개 공지 목록/본문은 지원. 장학 공고 전체 검색·마감 자동 통합은 미구현이며 장학수혜내역과 별개 |
| 게시판 본문 검색·전체 이력 | 페이지 조회·제한된 제목 검색·선택 본문 조회는 지원. 통합 본문 검색은 미지원이며 전체 이력 완전성·다양한 원문 표본 검증은 별개 |
| 공식 교시·학기 연결 | 사용자 입력만 지원. 캠퍼스·과정별 근거와 휴강/휴일 처리 기준 필요 |
| 추가 조회·출력 지역화 | 지도교수 공지·강의평가·본인 시설 예약내역·메일·졸업요건은 접근/표본 미확인. 시설 현황 시간표는 구현했으나 개인 예약내역과 별개. 출력 번역은 미구현 |
| 운영 안정성 | 중복 요청 합치기·완료 캐시 크기·쿠키 보호는 반영. 호출 간격·장시간/다중 클라이언트 운영·추가 오류 계약 검증은 후속 과제 |
| 지원 환경 확대 | Linux/Python 3.10·3.11·3.12, macOS/Python 3.11, 네이티브 Windows/Python 3.11 CI 구성. 네이티브 Windows의 오프라인 회귀·빌드·독립 wheel 설치 성공을 원격 CI에서 확인. Windows 로그인/ACL 및 다양한 계정 검증은 남아 있음. 로컬 실행과 원격 CI 근거는 [검증 기록](docs/VALIDATION.md) 참고 |

변경 시 원문 근거와 실패/빈 상태 회귀 테스트를 함께 확보합니다. 검증 결과와 실행 명령은
[개발 가이드](docs/DEVELOPMENT.md), 사용자에게 영향을 주는 계약 변경은 [CHANGELOG](CHANGELOG.md)에 기록합니다.