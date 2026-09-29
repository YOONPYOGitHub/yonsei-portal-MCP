# 도구 API 참조

**0.5.0b1**의 MCP 도구 33개를 설명합니다. 설치 버전의 입력은 `tools/list`로 확인하세요.
설치와 연결은 [README](../README.md), 구조와 운영 계약은 [DESIGN](../DESIGN.md), 개발·검증 절차는 [개발 문서](DEVELOPMENT.md)를 참고하세요.

## 공통 계약

- 모든 도구는 조회 또는 로컬 텍스트 생성용입니다. 수강신청, 과제 제출, 대출 연장, 예약 생성·취소, 게시글 변경은 수행하지 않습니다.
- 입력 표의 `필수`는 생략 불가, `null`은 Python의 `None`에 해당합니다. 인자 이름과 문자열 식별자의 철자를 그대로 사용하세요.
- 숫자 범위·문자열 패턴·선택지는 별도 표시가 없는 한 Python 실행 시 검사이며, MCP 입력 스키마의 `minimum`·`enum`·`pattern` 제약을 뜻하지 않습니다.
- 반환 설명은 구현의 데이터 계약입니다. `dict`와 `list[dict]` 반환은 필드가 닫힌 정밀 JSON 스키마가 아니므로, 클라이언트는 `tools/list`만으로 항목 필드를 검증할 수 없습니다.
- 계정 데이터는 민감정보입니다. 도구 호출·응답·내보낸 일정의 공유 범위를 최소화하고 사용자가 요청한 범위만 조회하세요.

### 인증·캐시·출처

LearnUs·ERP·개인 도서관 조회는 서버에 설정된 본인 계정으로 인증합니다. 도구 인자로 ID·비밀번호·쿠키를 전달하지 않습니다. 공개 HTTP 도구는 로그인이나 브라우저가 필요 없습니다. `get_notice`는 URL에 따라 경로가 달라집니다.
캐시는 프로세스 메모리에 있으며 인증 조회는 계정별, 공개 조회는 계정과 무관하게 공유합니다. TTL은 초 단위의 재사용 기간이지 원천 시스템의 갱신 주기가 아닙니다. 실패는 정상 결과로 캐시하지 않으며 강제 새로고침 인자는 없습니다.
`source_url`·`fetched_at`은 **각 반환 설명에 명시된 도구만** 제공합니다. 항목의 `url`이나 마감의 `source`와 구분하세요. 수집시각은 캐시 적중 때 갱신되지 않습니다. LearnUs의 수집시각은 KST, 공개·개인 도서관 및 학사일정은 UTC 오프셋이 포함된 ISO 시각입니다. 원문 날짜 문자열을 일괄 ISO 날짜로 가정하지 마세요.
이 API에는 임의 URL 탐색 도구가 없습니다. 고정 조회 경로와 검증된 게시글 주소를 사용하며, 공개 HTML의 리다이렉트는 동일 HTTPS 출처만 허용합니다. 링크를 반환한다는 사실이 외부 사이트 열람·파일 다운로드·열람 권한 확대를 뜻하지 않습니다.

### 식별자 연결

| 필요한 값 | 얻는 곳 | 다음 호출 |
| --- | --- | --- |
| `course_id` | 현재·과거 LearnUs 강좌 항목의 `id` | 출석·자료·과제 목록·성적부·게시판 |
| `assignment_id` | 과제 목록 항목의 `url`: `/mod/assign/view.php?id=...` | 과제 제출상태 |
| `board_id` | 게시판 목록의 `board_id`; `/mod/ubboard/view.php?id=...` | 게시글 목록 |
| `post_id` | 게시글의 `post_id`; 게시글 URL의 `bwid` | 단독 인자로 받는 도구 없음; 전체 `url`을 `get_notice`에 전달 |
| `catalog_id` | 도서 검색 결과의 `catalog_id` (`detail_supported=true` 확인) | 복본 상세 |

게시글 주소의 `id`는 게시판 ID이고 `bwid`는 글 ID입니다. 강좌 ID·과제 ID·게시판 ID·ERP `course_code`를 서로 바꾸어 사용하지 마세요. 모든 ID는 목록에서 얻은 문자열을 유지합니다.

### MCP 응답과 오류

각 절의 “반환”은 도구 함수의 논리적 값입니다. 아래 전송 표현은 잠금 환경의 MCP SDK **1.27.2** 기준입니다.

| 논리적 반환 | MCP 성공 응답 |
| --- | --- |
| 일반 `dict` | `content`의 text 블록에 JSON 객체를 직렬화. 현재 `outputSchema` 없음, `structuredContent`는 미제공/`null` 가능 |
| `get_lms_courses`, `get_lms_deadlines`, `get_lms_notices`의 배열 | `structuredContent`가 `{"result":[...]}`. `content`는 각 항목의 JSON text 블록이며 빈 배열이면 빈 목록 |
| 두 `export_*_ics`의 문자열 | `structuredContent`가 `{"result":"..."}`. `content`는 ICS 원문 text 블록 |

정상 `CallToolResult.isError`는 `false`입니다. 오류 시 동일한 반환 필드를 기대하지 마세요. 입력·조회 오류는 SDK가 `isError=true`인 도구 결과의 text로 전달할 수 있으며, Python 함수를 직접 호출하면 예외입니다. 이것은 stdio 연결 종료 등 전송 오류나 JSON-RPC 요청 자체의 오류와 다릅니다.
일부 조회 오류에는 `[AUTH_REQUIRED]`, `[AUTH_FAILED]`, `[MFA_REQUIRED]`, `[SESSION_EXPIRED]`, `[SCRAPE_FAILED]`, `[UPSTREAM_TIMEOUT]` 같은 코드가 텍스트로 포함됩니다. 모든 예외가 이 코드를 갖지는 않으며 자동으로 `{"error":{"code":...}}` 객체를 반환하는 계약은 없습니다. 인증 오류는 설정·로그인 상태를 확인하고, 추출 실패·시간 초과는 데이터 없음이나 0점·0석으로 바꾸지 마세요.
이력 도구 `get_my_loan_history`, `get_my_reservation_history`, `get_lms_course_history`는 입력 스키마의 `additionalProperties=false`와 서버의 별도 검사로 미등록 인자를 거부합니다. 다른 도구도 표에 없는 인자에 의존하지 마세요. 자료형은 스키마와 Pydantic 검증 대상이지만 숫자 범위·패턴 등은 실행 코드에서 추가 검사하며, 일부 오류 검사는 인증 이후에 이루어집니다.

## LearnUs 강좌와 학습

### `get_lms_courses`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| 없음 | - | - | 인자 없음: `{}` |

인증·출처·캐시: LearnUs 로그인, 홈의 수강 강좌 목록, 계정별 1800초.
반환: 배열. 항목은 `id`, `name`, `code`, `professor`, `category`, `progress_percent`, `url`, `attendance_url`입니다. 학수번호·교수·구분·진도·출석 URL은 확인되지 않으면 `null`일 수 있습니다.
범위: 홈에 표시된 본인 강좌이며 전체 학적 이력이나 ERP 수강신청 목록과 동일하지 않습니다. 강좌 링크를 기다리므로 강좌가 없는 화면은 빈 배열 대신 조회 오류가 날 수 있습니다.

### `get_lms_deadlines`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `course_id` | `string` 또는 `null` | `null` | 생략 시 전체, 지정 시 수집 결과의 강좌 ID로 필터 |

인증·출처·캐시: LearnUs 로그인, 달력의 예정된 할 일, 계정·필터별 300초.
반환: 배열. `title`, `due`(KST ISO 시각 또는 `null`), `due_text`(원문), `kind`, `course_id`, `course`, `url`, `source="calendar"`. 원문·강좌·URL도 `null`일 수 있습니다. URL 중복을 제거하고 마감 오름차순, 시각 미확인은 마지막에 둡니다.
범위: 숫자 ID 형식 검사는 없으며 문자열이 정확히 일치하는 항목만 남깁니다. `kind`는 제목 문구 기반 분류로 `assignment`, `progress`(진도 종료), `completion`(수료 권장일)입니다. 뒤 두 종류는 제출 과제가 아니며, 제출 여부는 이 결과로 알 수 없습니다.

### `get_lms_notices`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `scope` | `string` | `"all"` | `all`, `course`, `platform`; 그 밖의 값은 `all`로 처리 |

인증·출처·캐시: LearnUs 로그인, 홈 공지 링크, 계정·범위별 300초.
반환: 배열. 항목은 `type`(`course`/`platform`), `course`(플랫폼 공지는 `null`), `date`(`YYYY-MM-DD` 또는 `null`), `title`, `url`입니다.
범위: 홈에 표시된 공지이며 게시판 전체 이력을 순회하지 않습니다. 공지 링크가 전혀 없는 화면은 조회 오류가 날 수 있습니다. 강좌 공지에는 수강 정보가 포함됩니다.

### `search_notices`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `query` | `string` | 필수 | 공백으로 나눈 단어를 대소문자 구분 없이 AND 검색; 빈 검색어는 전체 |
| `scope` | `string` | `"all"` | `all`, `course`, `platform`; 그 밖의 값은 `all` |
| `limit` | `integer` | `20` | 실행 시 최소 1로 보정; 별도 상한 없음 |

인증·출처·캐시: LearnUs 로그인, `get_lms_notices`의 300초 계정·범위 캐시를 공유합니다. 검색 결과 자체는 별도 캐시하지 않습니다.
반환: `query`, 정규화된 `scope`, `count`, `results`. 각 결과는 공지 항목과 같습니다. 검색 대상은 `title`, `course`, `type`이며 본문은 검색하지 않습니다.
범위: `count`는 수집된 공지 중 제한 적용 전 일치 수이고 `len(results)`와 다를 수 있습니다. 학교 전체 공지 검색이 아니며 개인정보 범위도 원 공지와 같습니다.

### `get_notice`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `url` | `string` | 필수 | 지원 공지 목록에서 얻은 HTTPS 게시글 URL |

인증·출처·캐시: LearnUs 본문은 로그인·계정별, 도서관 일반공지는 무로그인 공개 HTTP·공유 캐시이며 모두 URL별 1800초.
입력 검사: HTTPS, 사용자명·비밀번호 없음, 포트 생략 또는 443. LearnUs는 호스트 `ys.learnus.org`, 경로 `/mod/ubboard/article.php`, 단일 `id`(ASCII 숫자 1~20자리)가 필수이고 `bwid`가 있으면 같은 규칙입니다. 이 함수는 그 밖의 쿼리 키를 일괄 금지하지 않습니다. 도서관은 `library.yonsei.ac.kr`의 `/bbs/content/1_숫자`만 지원하며 쿼리·프래그먼트를 제거해 요청합니다.
반환: `url`, `title`, `date`, `author`, `body`. LearnUs는 제목·날짜·작성자·본문이 `null`일 수 있고 반환 URL에 `lang=ko`가 적용됩니다. 도서관은 `author=null`, 날짜는 ISO 날짜 또는 `null`, 추가로 `image_count`와 `note`(이미지 없으면 `null`)가 있습니다.
범위: 본문 텍스트만 읽으며 요약·이미지 OCR·첨부 다운로드는 하지 않습니다. LearnUs 작성자·본문에 개인정보가 포함될 수 있습니다. 게시글 목록의 `url`을 그대로 사용하고 임의 호스트 열람 용도로 사용하지 마세요.

### `get_lms_attendance`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `course_id` | `string` | 필수 | LearnUs 강좌의 ASCII 숫자 ID 1~20자리 |

인증·출처·캐시: LearnUs 로그인, 강좌의 출석/학습 진도 보고서, 계정·강좌별 300초.
반환: `course_id`, `header`(원문 열 제목 배열), `weeks`(행 객체 배열). 행의 키는 원문 열 이름이며 제목 없는 열 등은 `col0`, `col1`처럼 대체합니다. 셀은 원문 문자열입니다.
범위: 표 구조가 동적이므로 고정된 출석률·결석 횟수 필드를 가정하지 마세요. 빈 표를 확인하지 못하면 오류이며 출석 없음으로 바꾸지 않습니다. 본인의 출결 정보입니다.

### `get_lms_course_materials`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `course_id` | `string` | 필수 | LearnUs 강좌의 ASCII 숫자 ID 1~20자리 |

인증·출처·캐시: LearnUs 로그인, 강좌 콘텐츠 페이지, 계정·강좌별 1800초.
반환: `course_id`, `section_count`, `activity_count`, `sections`. 섹션은 `id`, `week`, `name`, `activities`; 활동은 `type`(예: `vod`, `ubfile`, `assign`, `ubboard`), `title`, `url`입니다. 추출하지 못한 값은 `null`일 수 있고 `week=null`은 개요 또는 주차 미확인입니다.
범위: 주차순으로 정렬하며 `week=null`이 먼저입니다. 활동 메타데이터만 제공하고 파일·영상·과제 내용을 내려받지 않습니다. 수강 자료 링크의 재배포 권한을 부여하는 결과가 아닙니다.

### `get_lms_assignments`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `course_id` | `string` | 필수 | ASCII 숫자 1~20자리; 서버는 숫자 여부, 하위 자료 조회는 길이까지 검사 |

인증·출처·캐시: LearnUs 로그인, `get_lms_course_materials`의 계정·강좌별 1800초 캐시를 재사용합니다.
반환: `course_id`, `count`, `assignments`; 항목은 `title`, `url`, `week`(`null` 가능), `section`(미확인 시 `null` 가능)입니다. `type="assign"` 활동만 추립니다.
범위: 동영상·퀴즈는 제외하며 마감·제출 여부·점수는 포함하지 않습니다. `assignment_id`라는 결과 필드는 없으므로 `url`의 `/mod/assign/view.php?id=...`에서 추출합니다. 제출 기능은 없습니다.

### `get_lms_overview`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| 없음 | - | - | 인자 없음: `{}` |

인증·출처·캐시: LearnUs 로그인, 강좌·달력·강좌 공지를 한 번에 수집하여 계정별 **300초** 캐시.
반환: `courses`, `upcoming_deadlines`, `recent_course_notices`. 항목 형식은 각각 강좌·마감·공지 도구와 같으며 공지는 수집 순서의 앞 10개입니다.
범위: 이 묶음 캐시는 개별 조회 캐시와 독립적입니다. 날짜 재정렬이나 사용자용 요약을 생성하지 않고 원천 정보를 묶습니다. 수강·마감 정보가 함께 포함됩니다.

### `get_lms_course_history`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `year` | `integer` 또는 `null` | `null` | 2003~현재 KST 연도; 생략 시 전체 연도 |
| `semester` | `string` | `"all"` | `all`, `10`(1학기), `11`(여름), `20`(2학기), `21`(겨울) |

인증·출처·캐시: LearnUs 로그인, 과거강좌조회 표, 계정·연도·학기별 1800초.
반환: `count`, `courses`, 요청한 `year`(`null` 가능)·`semester`, `page=1`, `has_pagination=false`, `next_page=null`, `has_next=null`, `pagination_supported=false`, `scope="displayed_result"`, `filters_verified=true`, `scope_note`, `source_url`, `fetched_at`.
항목: `id`, `name`, `year`(원문 문자열), `semester`(원문 학기명으로 입력 코드와 다름), `url`. 현재 수강 강좌도 포함될 수 있습니다.
범위: **입력은 `year`, `semester`만 허용**합니다. `page`는 입력이 아닌 내부 호환 반환값입니다. 선택된 조건과 행의 일치를 확인하고, 페이지 이동 구조가 나타나면 오류로 처리합니다. 페이지 UI 부재·`count`는 전체 이력 완전성의 증거가 아닙니다.

### `get_lms_assignment_status`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `assignment_id` | `string` | 필수 | 과제 URL의 `id`; ASCII 숫자 1~20자리, 강좌 ID 아님 |

인증·출처·캐시: LearnUs 로그인, 단일 과제 제출상태 표, 계정·과제별 300초.
반환: `assignment_id`, `title`, `submission_status`(`submitted`/`not_submitted`/`draft`/`unknown`), `submission_status_raw`, `grading_status_raw`, `due`, `due_raw`, `remaining_raw`, `overdue_marker`, `last_modified_raw`, `url`, `fetched_at`.
범위: 제목·원문 항목은 누락 시 `null`; `due`는 원문이 `YYYY-MM-DD HH:MM`으로 해석될 때만 KST ISO 시각입니다. `overdue_marker`는 화면 표시 여부이며 지각 제출 판정이 아닙니다. 제출·채점 상태를 구분하며 제출물 본문은 읽지 않습니다.

### `get_lms_gradebook`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `course_id` | `string` | 필수 | 현재·과거 LearnUs 강좌의 ASCII 숫자 ID 1~20자리 |
| `include_feedback` | `boolean` | `false` | 사용자가 요청한 경우만 피드백 포함 |

인증·출처·캐시: LearnUs 로그인, 본인 강좌 성적부, 계정·강좌·피드백 옵션별 300초.
반환: `course_id`, `count`, `items`, `feedback_included`, `note`, `source_url`, `fetched_at`. 항목은 `name`, `kind`(`category`/`item`/`total`), `grade_raw`, `grade_available`입니다.
선택 필드: 화면에 해당 열이 있는 점수 행에 `weight_raw`, `range_raw`, `percentage_raw`, `contribution_raw`를 포함합니다. `feedback`도 해당 열과 요청 옵션이 있을 때만 포함합니다. 분류 행은 점수 `null`·가용 여부 `false`; 숨김 셀도 `null`일 수 있습니다.
범위: LMS 표시 성적은 ERP 확정 성적/GPA가 아닙니다. `-`, 빈 값, 숨김은 0점이 아니며 소계·총계와 항목을 중복 합산하지 마세요. 성적과 피드백은 민감정보입니다.

### `get_lms_boards`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `course_id` | `string` | 필수 | 현재·과거 LearnUs 강좌의 ASCII 숫자 ID 1~20자리 |

인증·출처·캐시: LearnUs 로그인, 강좌 게시판 목록 표, 계정·강좌별 300초.
반환: `course_id`, `count`, `boards`, `source_url`, `fetched_at`. 항목은 `board_id`, `name`, `post_count`(표의 숫자를 정수로 변환), `updated_raw`(원문 문자열), `url`입니다.
범위: 공통 메뉴는 제외합니다. `count`는 게시판 수이며 `post_count`는 다음 도구에서 실제 수집할 게시글 수가 아닙니다. 글 작성·수정·삭제는 지원하지 않습니다.

### `get_lms_board_posts`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `board_id` | `string` | 필수 | `get_lms_boards` 결과의 ASCII 숫자 게시판 ID 1~20자리 |

인증·출처·캐시: LearnUs 로그인, 게시판 첫 표시 페이지, 계정·게시판별 300초.
반환: `board_id`, `count`, `posts`, `unlinked_count`, `scope="displayed_page"`, `has_pagination`, `note`, `source_url`, `fetched_at`. 항목은 `post_id`, `title`, `date_raw`(원문 문자열), `url`입니다.
범위: 작성자·본문·링크 없는 글의 제목은 제외합니다. 링크 없는 행 수만 `unlinked_count`로 제공하고 중복 `post_id`는 제거합니다. 후속 페이지는 수집하지 않으며 `count`는 반환된 링크 있는 글 수입니다. 본문은 권한이 있는 반환 `url`로 `get_notice`를 호출합니다.

## 도서관

### `get_my_loans`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| 없음 | - | - | 인자 없음: `{}` |

인증·출처·캐시: 도서관 로그인, `/myloan/list`의 현재 대출 표, 계정별 300초.
반환: `count`, `loans`. 항목은 `title_author`, `location`, `reg_no`, `loan_date`, `due_date`, `overdue_fee`, `renew_count`이며 모두 원문 문자열입니다. 빈 셀은 `""`이고 요금·연장횟수를 숫자로 변환하지 않습니다.
범위: `due_date`는 반납예정일입니다. 명시적 빈 결과에서만 `count=0`; 표 미확인은 오류입니다. 도서·등록번호·대출 이력은 개인정보이며 연장은 수행하지 않습니다.

### `get_my_reservations`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| 없음 | - | - | 인자 없음: `{}` |

인증·출처·캐시: 도서관 로그인, `/myreserve/integratedList`의 도서 예약 표, 계정별 300초.
반환: `count`, `reservations`. 항목은 `title_author`, `location`, `queue_position`, `reservation_date`, `notification_date`, `status`; 모두 원문 문자열이며 미통보일 등 빈 셀은 `""`입니다.
범위: 현재 도서 예약만 조회하며 캠퍼스간 신청·좌석·스터디룸 예약은 포함하지 않습니다. 순위·상태를 임의 해석하지 마세요. 개인 예약을 생성·취소하지 않습니다.

### `get_my_loan_history`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| 없음 | - | - | 인자 없음: `{}`; 날짜·페이지 인자는 지원하지 않음 |

인증·출처·캐시: 도서관 로그인, `/myloan/history` 기본 화면, 계정별 300초.
반환: `count`, `loans`, `scope="displayed_page"`, `date_filters_raw`(`from`, `to`), `has_pagination`, `page=1`, `note`, `source_url`, `fetched_at`. 원문에 근거가 있는 경우만 `total`, `has_next`, `next_page`를 추가합니다. 다음 페이지 없음이 확인되면 `has_next=false`, `next_page=null`; 미확인은 키 자체가 없을 수 있습니다.
항목: `title_author`, `location`, `reg_no`, `loan_date`, `return_date`, `return_type`은 원문 문자열입니다. `return_date`는 실제 반납일로 반납예정일과 다릅니다. 동일한 원문 행은 중복 제거합니다.
범위: **날짜·페이지 입력을 받지 않습니다.** 표시 기간은 `YYYYMMDD` 또는 `""`인 `date_filters_raw`로 확인하며 빈 값은 전체 기간을 뜻하지 않습니다. `count`는 표시 결과 수로 전체 이력 수가 아니고, 원문 `total`도 현재 조회 조건 기준입니다. 독서 이력은 개인정보입니다.

### `get_my_reservation_history`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| 없음 | - | - | 인자 없음: `{}`; 날짜·페이지 인자는 지원하지 않음 |

인증·출처·캐시: 도서관 로그인, `/myreserve/integratedhistory` 기본 화면, 계정별 300초.
반환: `count`, `reservations`, `scope="displayed_page"`, `has_pagination`, `page=1`, `note`, `source_url`, `fetched_at`; 근거가 있을 때만 `total`, `has_next`, `next_page`가 추가됩니다. 미확인 키는 생략되며 다음 페이지 없음이 확인되면 `next_page=null`입니다.
항목: 현재 예약과 같은 `title_author`, `location`, `queue_position`, `reservation_date`, `notification_date`, `status` 원문 문자열입니다. 빈 셀은 `""`; 동일 원문 행은 중복 제거합니다.
범위: 날짜·페이지 입력과 `date_filters_raw` 출력은 없습니다. 과거 순위·상태를 현재 예약으로 안내하지 마세요. 캠퍼스간 신청·시설 예약을 제외하며 전체 이력 수집을 보장하지 않습니다. 개인정보입니다.

### `search_library_books`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `query` | `string` | 필수 | 앞뒤 공백 제거 후 1~200자 |
| `page` | `integer` | `1` | 원문 페이지 1~100; 페이지당 10건 |
| `limit` | `integer` | `10` | 이번 호출의 반환 상한 1~10; 원문 페이지 크기와 별개 |
| `campus` | `string` | `"all"` | `all`, `sinchon`, `international`, `sinchon_international`, `mirae` |
| `search_field` | `string` | `"all"` | `all`(전체 항목), `title`(서명), `author`(저자) |
| `offset` | `integer` | `0` | 현재 원문 페이지 내 0~9 위치; 실제 행 범위도 검사 |

인증·출처·캐시: 무로그인 공개 HTTP, 도서관 통합 소장자료 검색, 모든 입력별 공유 캐시 300초. `sinchon_international`은 사이트의 "신촌 + 국제"이며 기본 `all`은 전체 캠퍼스입니다. 전체 항목 검색에는 출판사 등에만 검색어가 있는 자료도 포함될 수 있습니다.
반환: `query`, `page`, `offset`, `count`, `results`, `total`, `displayed_total`, `source_limited`, `total_pages`, `page_size=10`, `page_count`, `truncated`, `has_next`, `next_page`, `next_request`, `page_limit_reached`, `filters`, `filters_verified`, `source_url`, `fetched_at`, `note`.

- `count`: 이번에 반환한 자료 수. `page_count`: 로컬 제한 전 원문 페이지 자료 수. `total`: 원문 전체 검색 자료 수. `displayed_total`: 원문 출력 대상 수. 모두 **복본 수가 아닙니다**. `total_pages`는 출력 대상의 페이지 수이며, `source_limited=true`이면 원문 자체가 일부만 제공해 전체 수집 완료로 안내할 수 없습니다.
- `truncated`: 현재 페이지에 아직 반환하지 않은 뒷부분이 있는지 표시합니다. 이 경우 `next_page`는 현재 페이지이고 `next_request.offset`이 증가합니다.
- `next_request`: 이어 호출할 완전한 인자 객체입니다. 페이지를 다 읽어야 다음 페이지의 `offset=0`으로 이동합니다. 예를 들어 `limit=3`이면 `(page, offset)`이 `(1,0)`, `(1,3)`, `(1,6)`, `(1,9)`, `(2,0)` 순서로 이어집니다. `page`만 증가시키면 자료가 누락됩니다.
- `has_next=false`일 때 후속 결과가 없으며 `next_page`/`next_request`는 `null`입니다. 이전 페이지도 수집했다는 뜻은 아닙니다. 전체 0건은 원문의 명시적 0건으로 검증합니다.
- `page_limit_reached=true`이면 후속 자료가 있지만 100페이지 상한을 넘습니다. 이때 `has_next=true`, `next_page=101`, `next_request=null`이므로 전체 수집 완료로 안내하지 마세요.
- `filters`는 `campus`/`search_field`입니다. 숨은 검색 조건·페이지 크기·현재 페이지·자료 수·다음 링크를 원문과 검증한 경우만 `filters_verified=true`로 반환하며, 불명확하거나 모순되면 오류입니다.

자료 항목: `catalog_id`, `detail_supported`, `title`, `author`, `publisher`, `published_year`, `material_type`, `url`, `holdings`. 서지 필드는 누락 시 `null`, 출판년은 원문 문자열입니다. `detail_supported`는 현재 상세 도구가 지원하는 CATTOT ID 형식인지 표시하며 복본 표의 존재까지 보장하지 않습니다.
`holdings`는 `location`, `status`(미표시 시 `null`), `campus`를 포함하며 빈 배열일 수 있습니다. 캠퍼스는 원문 접두어가 확인될 때 `sinchon`/`international`/`mirae`, 그 밖에는 `null`입니다. 원문 위치를 보존합니다.

전체 목록은 첫 페이지 `offset=0`부터 `next_request`를 따라 수집하고, `catalog_id` 중복·고유 건수와 매 응답의 `total`을 대조하세요. 페이지 사이 검색 결과가 바뀔 수 있고 캐시도 별도라 원자적 스냅샷은 아닙니다. 변동·원문 제한·페이지 상한·상세 조회 실패가 있으면 불완전함을 명시합니다.
전체 복본 집계는 관련 작품의 모든 판본 ID에 대해 `get_library_book_detail` 완료 여부를 대조한 뒤, 요청 캠퍼스의 복본만 `reg_no`로 구분합니다. 검색 캠퍼스는 서지 결과를 제한할 뿐 상세의 다른 캠퍼스 복본을 제거하지 않습니다. 검색 `holdings` 요약을 실물 복본 수로 세지 마세요. 상태는 실제 이용 전 원문에서 재확인하세요.

### `get_library_book_detail`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `catalog_id` | `string` | 필수 | `CATTOT` 뒤 ASCII 숫자 1~20자리 |

인증·출처·캐시: 무로그인 공개 HTTP, 도서관 `/search/detail/`의 CATTOT 소장자료, 식별자별 공유 캐시 300초.
반환: `catalog_id`, `count`, `copies`, `note`, `source_url`, `fetched_at`. 복본은 `reg_no`, `call_number`, `location`, `status_raw`, `due_date_raw` 원문 문자열과 정규화한 `campus`를 포함하며 청구기호·반납예정일이 빈 문자열일 수 있습니다. `campus`는 `sinchon`/`international`/`mirae` 또는 미확인 `null`입니다.
범위: `count`는 확인된 복본 수입니다. 복본 표가 없으면 미소장으로 단정하지 않고 오류로 처리합니다. 상태·빈 반납예정일로 예약 가능성을 추정하지 마세요. 차용자·예약 버튼 정보는 읽지 않습니다.

### `get_library_notices`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `limit` | `integer` | `10` | 1~20; 일반공지 첫 페이지의 반환 상한 |

인증·출처·캐시: 무로그인 공개 HTTP, 도서관 `/bbs/list/1`, 상한별 공유 캐시 300초.
반환: `count`, `notices`; 항목은 `title`, `date`(원문 날짜 문자열), `url`입니다. 작성자 필드는 없습니다.
범위: 고정 공지를 포함한 첫 페이지 원문 순서이며 중복 URL과 명시적으로 삭제된 글은 제외합니다. `count`는 반환 수로 전체 공지 수가 아닙니다. 본문은 `get_notice`로 확인합니다.

### `get_library_seats`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `seat_type` | `string` 또는 `null` | `null` | `general`/일반열람석, `pc`/PC석, `study`/스터디룸, `notebook`/노트북석; 생략 또는 `""`이면 전체 |

인증·출처·캐시: 무로그인 공개 HTTP, 도서관 `/seat/info`, 입력 필터별 공유 캐시 60초.
반환: `rows`, `total`, `in_use`, `remaining`, `usage_pct`, `source_url`, `fetched_at`, `availability_note`. 행은 `building`, `building_code`(`center`/`yonsei`), `seat_type`, `seat_type_code`, `total`, `in_use`, `remaining`, `usage_pct`입니다. 좌석 수는 정수, 이용률은 소수점 한 자리 숫자입니다.
범위: 건물군×유형 집계이며 0/0인 행은 제외합니다. 필터는 공백 제거·소문자 변환 후 적용하고 합계를 다시 계산합니다. 알 수 없는 값이나 공백만 있는 문자열은 오류가 아니라 빈 행·0 합계가 됩니다. 한글 유형명은 코드의 표시용 매핑입니다.
주의: `remaining`은 공개 집계상 잔여석이지 배정 가능 좌석이 아닙니다. 개인 정보는 없지만 열람실 도구와 집계 범위·갱신 상태가 달라 합산하면 안 됩니다.

### `get_library_seat_rooms`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| 없음 | - | - | 인자 없음: `{}` |

인증·출처·캐시: 도서관 로그인, `/relation/seat` 열람실별 좌석 표, 계정별 60초. 로그인은 필요하지만 개인 배정 내역은 아닙니다.
반환: `count`, `rooms`, `total`, `in_use`, `available`, `source_totals_match`(`true` 또는 원문 합계 미표시 시 `null`), `assignable_available`, `unassignable_rooms`, `usage_pct`, `availability_note`, `source_url`, `fetched_at`.
항목: `name`, `assignable`(불리언), `total`(운영좌석), `capacity`(수용좌석, `null` 가능), `in_use`, `available`, `hours`(원문), `usage_pct`·`note`(`null` 가능). `count`는 열람실 수입니다. 원문 합계 불일치는 `false` 반환이 아닌 오류입니다.
범위: `available`은 배정불가 방도 포함한 표시 잔여석, `assignable_available`은 배정가능 방만의 잔여 합계, `unassignable_rooms`는 배정불가 방 수입니다. 어느 값도 실제 착석을 보장하지 않습니다.

## 학사행정 ERP

### `get_student_profile`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `include_pii` | `boolean` | `false` | 사용자가 명시적으로 요청한 경우만 이름·학번 포함 |

인증·출처·캐시: ERP 로그인, 수강신청내역의 프로필·학기 데이터, 계정별 1800초. 원본 캐시에서 이름·학번을 응답 직전에 걸러냅니다.
반환: `department`, `department_full`, `department_code`, `current_term`, `current_term_credits`, `terms`, `pii_included`. 학기 항목은 `term`, `year`, `code`, `credits`; 원천 형식을 보존하며 누락 값은 `null`입니다. `include_pii=true`일 때만 `name`, `student_no` 키를 포함합니다.
범위: `current_term`은 반환 학기 코드가 가장 큰 행에서 가져오며 오늘 기준 재학 상태를 계산한 값이 아닙니다. 기본 응답도 학과·수강학점을 포함한 개인정보이고, 기본 필터가 내부 캐시의 이름·학번까지 삭제하지는 않습니다.

### `get_my_timetable`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| 없음 | - | - | 인자 없음: `{}` |

인증·출처·캐시: ERP 로그인, 현재 화면 학기 수강신청내역, 계정별 1800초.
반환: `term`(`null` 가능), `count`, `total_credits`(정수 또는 실수), `courses`. 항목은 `course_code`, `section`, `course_name`, `course_name_en`, `professor`, `professor_en`, `credits`, `category`, `room`, `time_raw`, `time_en`, `slots`입니다. 식별 필드·학점 외 누락 값은 `null`일 수 있습니다.
범위: `credits`는 원천 문자열/숫자, 총학점은 유효한 비음수 학점만 정확하게 합산합니다. 누락·손상 값은 오류입니다. 슬롯은 `day`(월~일), `day_en`(`Mon`~`Sun`), `period`(1~99)이며 범위·격주·미정 등 미지원 원문은 보존하고 `slots=[]`로 둡니다. 수업 없음으로 해석하지 마세요. 본인의 주간 시간표입니다.

### `get_grades`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `year` | `integer` 또는 `null` | `null` | 1900~현재 KST 연도 |
| `term_code` | `string` 또는 `null` | `null` | `10`, `11`, `20`, `21`; 생략한 조건은 필터하지 않음 |

인증·출처·캐시: ERP 로그인, 전체성적조회 후 로컬 과목·학기 필터, 계정·조건별 1800초. 학기 코드는 10=1학기, 11=여름, 20=2학기, 21=겨울입니다.
반환: `count`, `courses`, `terms`, `summary`, `summary_scope="all_terms"`, `filters`(`year`, `term_code`). 과목이 없을 때만 `note`를 추가합니다. 과목은 `term`, `year`, `term_code`, `course_code`, `course_name`, `credits`, `grade`, `category`, `professor`; 연도·학기 코드는 문자열, 그 외는 원천 값으로 `null`일 수 있습니다.
범위: `summary`의 `total_earned_credits`, `gpa`는 항상 전체 학기 누적이며 누락 시 `null`입니다. **`terms`는 필터된 ERP 원천 행을 그대로 반환**하므로 `syy`, `smtDivCd` 외 필드·형식은 고정하지 않으며 내부 필드나 개인정보가 없다고 보장하지 않습니다. 0건을 전체 성적 이력 없음으로 단정하지 마세요.

### `get_scholarship_history`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| 없음 | - | - | 인자 없음: `{}` |

인증·출처·캐시: ERP 로그인, 장학수혜내역조회, 계정별 300초.
반환: `count`, `scholarships`; 항목은 `year`, `term_code`, `name`, `amount`, `payment_date_raw`. 금액은 숫자/문자열 등 원천 형식, 날짜도 원문이며 값이 `null`일 수 있습니다.
범위: 현재 조회 표의 본인 수혜내역이지 신청 가능한 장학금 목록이 아닙니다. 학번·내부 식별자 필드는 제외하지만 수혜내역 자체는 민감정보입니다. 신청·증명서 발급은 하지 않습니다.

### `get_exam_schedule`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `exam_type` | `string` | `"default"` | `default`(화면 기본), `midterm`, `final`; 그 밖의 값은 오류 |

인증·출처·캐시: ERP 로그인, 현재 화면 학기 시험시간표조회, 계정·요청 시험구분별 300초.
반환: `term`(`null` 가능), `exam_type`(실제 선택된 원문, 예: `중간시험`), `period_configured`, `note`(조회기간 등록 시 `null`), `count`, `exams`. 항목은 `course_code`, `section`, `course_name`, `exam_date_raw`, `time_raw`, `room`, `exam_type`, `professor`이며 원천 값과 `null`을 보존합니다.
범위: 응답 시험구분은 입력의 `midterm`/`final` 코드가 아닙니다. `period_configured=false`는 조회기간 미등록이며 시험 없음이 아닙니다. 개인 시험 일정을 원문 날짜·교시로 제공하고 신청·등록은 하지 않습니다.

### `search_courses`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `keyword` | `string` | 필수 | 앞뒤 공백 제거 후 2~100자, 교과목명 검색 |
| `limit` | `integer` | `20` | 1~50 |
| `year` | `integer` 또는 `null` | `null` | 2003~서버 로컬 현재 연도+1; 생략 시 화면 기본값 |
| `term_code` | `string` 또는 `null` | `null` | `10`, `11`, `20`, `21`; 생략 시 화면 기본값 |
| `campus_code` | `string` 또는 `null` | `null` | `s1`, `s3`, `s7`(신촌 학부·대학원·의료원), `s2`, `s4`, `s8`(미래 학부·대학원·의료원); 생략 시 화면 기본값 |

인증·출처·캐시: ERP 로그인, 수강편람 교과목명 검색, 계정·검색 조건별 1800초.
반환: `keyword`, `filters`, `count`, `fetched_count`, `matching_count`, `requested_filters`, `truncated`, `courses`. `filters`는 실제 조회 요청의 `year`, `term_code`, `campus_code`, `college_code`, `department_code`, `keyword_type` 원천 값(`null` 가능); `requested_filters`는 사용자가 지정한 연도·학기·캠퍼스만 포함합니다.
항목: `year`, `term_code`, `course_code`, `section`, `course_name`, `professor`, `credits`, `time_raw`, `room`, `department`, `category`, `campus_code`. 값은 원천 형식이며 누락 필드는 `null`입니다. ERP 과목코드는 LearnUs `course_id`가 아닙니다.
범위: `fetched_count`는 학교 응답 행 수, `matching_count`는 그 안에서 요청 필터와 일치한 수, `count`는 `limit` 적용 후 수입니다. `truncated`는 일치 수가 상한을 넘거나 응답이 200건 이상이면 참이므로 0건이어도 부재를 단정하지 마세요. 정원·수강인원·강의계획서는 제공하지 않고 수강신청도 하지 않습니다.

## 일정과 내보내기

### `get_academic_calendar`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| 없음 | - | - | 인자 없음: `{}` |

인증·출처·캐시: 무로그인 공개 HTTP, 공식 홈페이지 신촌·국제 학사일정 `/sc/373/subview.do`, 공유 캐시 1800초.
반환: `academic_year`(정수), `semester`(`first`/`second`), `months`, `count`, `source_url`, `date_note`, `fetched_at`. 월은 `display_year`, `month`, `events`; 이벤트는 `date_raw`, `title` 원문 문자열입니다.
범위: 현재 표시 학기만 조회합니다. `count`는 월별 표시 항목 합계로 월 경계의 같은 일정이 중복될 수 있습니다. `display_year`/`month`는 표시 구간이지 모든 일정의 시작 연월이 아닙니다. 개인·학과 시험 일정을 대체하지 않습니다.

### `get_my_schedule`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `days` | `integer` | `7` | 오늘(KST)부터 1~90일 |
| `include_loans` | `boolean` | `true` | 도서 반납일 포함 |
| `include_exams` | `boolean` | `false` | 중간·기말 시험 조회를 함께 포함 |

인증·출처·캐시: LearnUs와 ERP 로그인은 항상 필요하며 도서 포함 시 도서관도 필요합니다. 마감·대출·시험 300초, 시간표 1800초의 개별 캐시를 재사용하고 묶음은 별도 캐시하지 않습니다.
반환: `window`(`start`, `end_exclusive`, `timezone="Asia/Seoul"`), `count`, `events`, `undated_items`, `weekly_timetable`, `exams`, `generated_at`, `coverage_note`. `exams`는 미포함 시 `null`, 포함 시 `midterm`, `final`에 각각 시험 도구 결과를 담습니다.
이벤트: 공통 `title`, `kind`, `source`, `due_raw`, `date`, `due`, `all_day`. LMS는 추가로 `course`, `url`(`null` 가능), `source="learnus"`, `all_day=false`; 도서 반납은 `kind="loan_return"`, `source="library"`, `due=null`, `all_day=true`이며 `course`·`url` 키가 없습니다. 날짜 미확인은 `date`·`due`·`all_day` 없이 `undated_items`에 보존합니다.
범위: 오늘부터 종료일 직전까지 KST 날짜로 필터하므로 오늘 이미 지난 시각도 포함될 수 있습니다. `count`는 날짜 확인된 이벤트 수이고 시간표·시험·미확인 항목 수를 합치지 않습니다. 시간표는 주간 패턴, 시험은 `days`로 필터하지 않은 원문 조회 범위입니다. 생성시각은 원천 갱신시각이 아니며 개인정보가 합쳐집니다.

### `export_calendar_ics`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `include_loans` | `boolean` | `true` | `false`이면 도서관 로그인을 생략 |
| `course_id` | `string` 또는 `null` | `null` | LearnUs 마감 결과의 강좌 ID 필터; 도서 반납일에는 적용하지 않음 |

인증·출처·캐시: LearnUs 로그인, 도서 포함 시 도서관 로그인. 마감·현재 대출의 300초 캐시를 공유하고 ICS 문자열을 로컬 생성합니다.
반환: iCalendar 문자열. 마감은 UTC 시각의 단일 시점 이벤트(`DTEND`·`DURATION` 없음), 도서 반납일은 종일 이벤트이며 종료 날짜는 다음 날입니다. 날짜·시각을 해석하지 못한 항목은 제외합니다.
범위: `progress`·`completion`도 내보내며 제출 과제로 재분류하지 않습니다. 파일 저장·캘린더 업로드·구독 URL 제공은 하지 않는 일회성 텍스트 내보내기입니다. 제목·강좌·도서 정보가 포함되므로 외부 캘린더 공유에 주의하세요.

### `export_timetable_ics`

| 인자 | 형식 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `start_date` | `string` | 필수 | 사용자가 확인한 시작일 `YYYY-MM-DD` |
| `end_date` | `string` | 필수 | 사용자가 확인한 종료일 `YYYY-MM-DD` |
| `period_times` | `object<string,object<string,string>>` | 필수 | 교시별 `{"2":{"start":"10:00","end":"10:50"}}` 형태의 사용자 확인 KST 시각 |
| `exclude_dates` | `array<string>` 또는 `null` | `null` | 제외할 날짜 목록; 공휴일 자동 제외 없음 |

인증·출처·캐시: ERP 로그인, `get_my_timetable`의 계정별 1800초 캐시를 이용해 로컬 생성합니다. 시간표 조회 후 입력 날짜·교시를 검사하므로 잘못된 입력도 먼저 ERP 조회를 일으킬 수 있습니다.
추가 검사: 실제 유효 날짜, 시작일≤종료일, **종료일−시작일≤366일**입니다. 양끝을 포함하므로 구현상 최대 367개 날짜입니다. 제외일은 기간 안이어야 합니다. 교시 키는 `1`~`99`(앞자리 0 없음), 값의 `start`·`end`는 유효한 `HH:MM`이며 같은 날 종료>시작이어야 합니다. 시간표에 쓰인 모든 교시를 제공해야 합니다.
반환: iCalendar 문자열. 과목·요일·교시별 주간 반복 이벤트(`RRULE`)와 지정 제외일(`EXDATE`)을 UTC 시각으로 생성합니다. 이벤트에는 과목명과 강의실이 포함될 수 있습니다.
범위: 사용자 확인 없이 학기 기간·교시 시각을 추측하지 마세요. 위 시각은 형식 예시이며 학교 공통 시간표가 아닙니다. 해석 불가 시간·빈 시간표·필수 교시 누락은 부분 내보내기 대신 오류입니다. 휴강·공휴일은 자동 반영하지 않으며 파일·공유 캘린더는 생성하지 않습니다.

## 호출 예제

아래는 `tools/call`의 `params`에 넣을 `name`·`arguments` 예시 모음입니다. 배열 전체를 배치 요청으로 보내는 것이 아니라 필요한 객체 하나씩 사용합니다. **숫자 ID와 CATTOT 식별자는 모두 합성 자리표시자이므로 실제 조회 결과로 교체해야 합니다.** 연도·검색어·옵션도 사용자 요청에 맞게 선택하세요.

```json
[
	{"name":"get_lms_courses","arguments":{}},
	{"name":"get_lms_course_history","arguments":{"year":2025,"semester":"20"}},
	{"name":"get_lms_assignments","arguments":{"course_id":"123456"}},
	{"name":"get_lms_assignment_status","arguments":{"assignment_id":"234567"}},
	{"name":"get_lms_gradebook","arguments":{"course_id":"123456","include_feedback":false}},
	{"name":"get_lms_boards","arguments":{"course_id":"123456"}},
	{"name":"get_lms_board_posts","arguments":{"board_id":"345678"}},
	{"name":"get_notice","arguments":{"url":"https://ys.learnus.org/mod/ubboard/article.php?id=345678&bwid=456789"}},
	{"name":"search_notices","arguments":{"query":"중간 시험","scope":"course","limit":5}},
	{"name":"search_library_books","arguments":{"query":"자료구조","page":1,"limit":5,"campus":"sinchon","search_field":"title","offset":0}},
	{"name":"get_library_book_detail","arguments":{"catalog_id":"CATTOT12345678"}},
	{"name":"get_my_loan_history","arguments":{}},
	{"name":"get_my_reservation_history","arguments":{}},
	{"name":"get_library_seats","arguments":{"seat_type":"pc"}},
	{"name":"get_student_profile","arguments":{"include_pii":false}},
	{"name":"search_courses","arguments":{"keyword":"인공지능","limit":10,"year":2026,"term_code":"20","campus_code":"s3"}},
	{"name":"get_grades","arguments":{"year":2025,"term_code":"20"}},
	{"name":"get_my_schedule","arguments":{"days":7,"include_loans":false,"include_exams":true}},
	{"name":"export_calendar_ics","arguments":{"include_loans":false}}
]
```

시간표 내보내기는 사용자에게 기간·교시 시각·제외일을 확인한 뒤 호출합니다. 다음 값은 합성이며 공식 학사기간·교시 시각이 아닙니다. 실제 시간표가 2·3교시만 사용한다는 전제의 형식 예제입니다.

```json
{"name":"export_timetable_ics","arguments":{"start_date":"2026-09-01","end_date":"2026-12-21","period_times":{"2":{"start":"10:00","end":"10:50"},"3":{"start":"11:00","end":"11:50"}},"exclude_dates":["2026-09-28"]}}
```

### 합성 응답 예제

다음 두 객체는 실계정 조회가 아닌 **SYNTHETIC** 예제이며 현재 파서와 단위 테스트의 구조로 검증한 논리적 반환값입니다. MCP 전송 봉투는 생략했습니다.
과제 목록에서 `assign` 활동만 선택한 경우:

```json
{"course_id":"123456","count":1,"assignments":[{"title":"합성 보고서","url":"https://ys.learnus.org/mod/assign/view.php?id=234567","week":1,"section":"1주차"}]}
```

현재 대출 표에서 “결과가 없습니다.”라는 명시적 빈 상태가 확인된 경우:

```json
{"count":0,"loans":[]}
```