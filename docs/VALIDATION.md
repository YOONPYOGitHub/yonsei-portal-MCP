# 검증 기록

## 0.6.0b2 — 2026-10-05

기능 확장 없이 기존 조회의 정합성·질문 평가·보관 검증을 보완했습니다. 실제 계정 응답과 답변은 비공개이며, 아래 합성 회귀와 실제 MCP 조회를 구분합니다.

| 검사 | 확인 결과 |
|---|---|
| macOS Python 3.11 잠금 환경 오프라인 회귀 | **1557 passed, 1 skipped, 24 deselected**, 별도 subtest 37개 통과. skip은 네이티브 Windows 전용 시간대 검사 |
| 정적 오류 검사 | Ruff 0.14.1 `E9,F63,F7,F82` 통과. 전체 스타일/타입 검사를 의미하지 않음 |
| 독립 코드 검토 | 중첩 활동의 제목·링크 소유권 결함을 추가 재현·수정한 뒤 회귀 및 독립 재검토 통과 |
| 수강편람 실제 MCP | 기본 조회 조건과 수신 행 범위가 다름을 경고로 구분. 명시 조건 제외와 출력 제한을 따로 확인 |
| 강의자료 실제 MCP | 최종 소유권 보완 후 자료·과제 목록 재조회. 해당 계정 표본에서 이전 수신 내용과 일치함 확인 |
| 시설 후속 질문 실제 MCP | 원문 `past` 표시로 발생한 오류를 재현. 합성 회귀 보완 후 같은 날짜·시설·사용시간으로 재조회하여 24개 시간 구간과 과거 표시 확인. 예약/시간대 클릭 없음 |
| 빌드·독립 wheel | sdist→wheel 빌드 성공. 소스 밖 Python 3.11에서 wheel 설치 후 실제 stdio 도구 38개와 격리 Chromium 기동 확인 |
| 잠금 외 의존성 표본 | 독립 wheel이 선택한 Playwright 1.63.0의 Chromium 설치 후 `doctor --browser --json` 종료 0. 학교 로그인 검증은 잠금 Playwright 경로와 구분 |

### 질문 평가와 실패 기록

- 공개 카탈로그는 152개 질문의 정의이며 실행 현황을 대신하지 않습니다. 최신 상태는 비공개 실행별 답변·검토 기록에 남깁니다.
- 실제 데이터 조회는 MCP로 수행하고 현재 대화 모델이 답변합니다. 질문별 경로를 지정한 보조 평가이지 자연어 도구 선택의 블라인드 E2E나 별도 `.env.llm` 제공자 시험이 아닙니다.
- 안전 거절은 `refused`, 모호성 해석/확인은 `needs_clarification`, 조건 미충족은 `blocked`로 분리합니다. 올바른 거절을 조회 실패로 집계하지 않습니다.
- 과제 상세처럼 선행 대상이 없는 사례에 임의 강좌/ID를 대입하지 않습니다. 그런 표본은 실제 상세 경로를 검증한 것으로 세지 않습니다.
- 열람실 조회에서 일회성 일반 `SCRAPE_FAILED`가 관찰됐고, 제한된 진단과 후속 MCP 조회는 성공했습니다. 정확한 원인은 미확정이며 코드로 해결했다고 표시하지 않습니다.
- 수집 보조 코드의 잘못된 `semester`/`scope` 값과 응답 파싱 실패도 운영 기록에 남깁니다. 올바른 계약으로 정정한 조회와 최초 실패를 구분하며 일괄 무오류 성공으로 표시하지 않습니다.
- 원본 답변·응답은 보존합니다. `verify_archive`는 핵심 근거/집계, `verify_full_archive`는 인벤토리의 전체 파일 체크섬·누락·추가를 검사합니다. 어느 쪽도 학교 원문의 진실성·모델 정확도·원격 실행을 암호학적으로 증명하지 않습니다.

최종 커밋의 OS별 CI·보안 결과는 GitHub Actions에서 별도로 확인합니다. 새 학교 기능, PyPI 게시, GitHub Release 발행은 이번 변경 범위가 아닙니다.

## 0.6.0b1 — 2026-10-05

로컬 개발·실사이트 검증은 **Mac mini / Apple M4 / macOS arm64**에서 수행했습니다.
이전 Windows+WSL 개발 환경과 현재 실행 환경을 혼동하지 않습니다. Windows는 네이티브
GitHub Actions 러너의 별도 실행 결과로 검증합니다. 개인 자격 증명·쿠키·원문 캡처·생로그는 공개하지 않습니다.

| 검사 | 실제 결과 |
|---|---|
| macOS Python 3.10.20 / 3.11.15 / 3.12.13 | 각각 **1168 passed, 1 skipped, 24 deselected** (라이브/LLM 제외; skip은 네이티브 Windows 전용 시간대 검사) |
| `doctor --browser --json` | 종료 0, Chromium 격리 기동 성공, 실제 MCP initialize/tools/list **38개** |
| 실제 MCP/포털 기존 회귀 21항목 | 최종 전체 실행 20 passed / 1 failed; 실패한 stdio 통합 항목 단독 재실행 1 passed. 한 번의 21개 일괄 성공으로 표시하지 않음 |
| stdio 통합 재검사 | 등록된 **38개 도구 모두 실제 호출**, 등록 목록과 호출 집합 일치 |
| LearnUs 게시판 후속 페이지 | 1페이지 15건 + 2페이지 7건, 고유 22건. ID·제목·작성일을 브라우저 DOM과 대조, 제목 검색 결과 일치 |
| 공식 대학 공지 | 1·2페이지 14/15건, 목록 ID·제목·날짜 및 선택 본문 DOM 일치 |
| 일반대학원 공지 | 1·2페이지 각 21건(고정글 포함), 목록 및 선택 본문 DOM 일치 |
| 인공지능융합대학원 공지 | 1·2페이지 각 12건(고정글 포함), 목록 및 선택 본문 DOM 일치 |
| 배포물 | sdist→wheel 빌드, `twine check` 통과 |
| 독립 wheel | 소스 밖 새 Python 3.11 환경의 패키징/메타데이터/Windows 의존성 선언 7 passed, 1 skipped; 설치본 doctor 종료 0·38개 도구 |
| 잠금 런타임 감사 | `pip-audit==2.9.0 --require-hashes --disable-pip --strict` 알려진 취약점 미탐지 |
| 공개 파일·Git 이력 | Gitleaks 8.30.1, redacted 검사 미탐지; 비공개 파일은 수집·게시하지 않음 |

독립 wheel은 잠금 파일과 별도로 의존성을 해결하여 Playwright 1.63.0을 설치했습니다.
그 버전의 Chromium은 별도 설치하지 않아 doctor가 `chromium_missing` 경고를 정확히 표시했습니다.
공개 HTTP 기능의 로컬 준비 확인(종료 0)과 브라우저 기동 성공을 혼동하지 않습니다.
실사이트·브라우저 검증은 잠금 Playwright 1.60.0에서 수행했습니다.

환경파일 후속 정리도 포함했습니다. `.env.llm` 로더/네 실행 진입점/제공자별 템플릿에
대한 독립 검토는 189개 합성 검사를 통과했습니다. 실행 차단·우선순위·허용 키·비치환·일반 MCP의
분리 경계를 확인했으며 실제 LLM API는 호출하지 않았습니다. Windows에는 KST 처리에 필요한
`tzdata` 조건부 의존성을 추가했습니다. 로컬 Mac에서 Windows 실행을 흉내 낸 결과는 아닙니다.

### 검증 중 수정·재시도

- 실제 LearnUs 2페이지 글 링크에 붙는 `page=2`를 기존 파서가 거절하는 문제를 재현한 뒤 수정했습니다.
- 공지 후속 페이지의 활성 표시 누락, 현재/마지막 페이지 모순, 다른 게시판으로의 리다이렉트,
  중복 ID의 제목/날짜 충돌을 합성 회귀로 보강했습니다. 실제 원문 3개 소스도 다시 대조했습니다.
- 시설 테스트가 특정 방을 항상 선택 불가로 가정하던 문제를 발견했습니다. 현재 DOM에서 실제
  선택 불가 항목을 찾아 검사하며, 표본이 없으면 명시적으로 skip합니다. 예약/변경 요청은 하지 않습니다.
- 초기 실사이트 실행에서 도서관 화면 응답 시간 초과와 stdio 도구 오류가 발생했습니다.
  실패를 성공/빈 결과로 바꾸지 않고 원문 조회 및 실패 항목을 재실행해 확인했습니다.
- 기존 CI의 유효하지 않은 setup-uv 커밋 고정값을 공식 태그·커밋·action.yml 확인 후 교체했습니다.

### 원격 CI와 검증 경계

- CI 매트릭스: Linux Python 3.10/3.11/3.12, macOS 3.11, **네이티브 Windows 3.11**.
- 별도 Security 워크플로: 잠금 런타임 의존성 감사와 전체 Git 이력/공개 트리 비밀정보 검사.
  push/PR·주간·수동 실행, 최소 읽기 권한, 학교/LLM 자격 증명 없이 실행합니다.
- 코드 커밋 [`6ff4b34`](https://github.com/YOONPYOGitHub/yonsei-portal-MCP/commit/6ff4b342e11afce4546eb8c2a87c8fdd1d211853)의
  [CI 5개 작업](https://github.com/YOONPYOGitHub/yonsei-portal-MCP/actions/runs/37220296131)과
  [Security 2개 작업](https://github.com/YOONPYOGitHub/yonsei-portal-MCP/actions/runs/37220296200)이 모두 성공했습니다.
  Windows 실제 결과는 **1161 passed, 8 skipped, 24 deselected**, 독립 wheel 검사 **6 passed**입니다.
  POSIX 권한/심볼릭 링크 전용 검사 등은 해당 OS에서 제외되며 KST 시간대 검사는 Windows에서 실행됩니다.
- 초기 Windows 실행에서 네트워크 차단 fixture의 설치 순서와 subprocess 감사 인자 표현 차이를
  발견했습니다. 비동기 루프 초기화 이후 차단을 설치하고, stdlib 소켓쌍의 자체 IPC만 검증해 허용하도록
  테스트 보조 코드를 수정했습니다. 임의 loopback/외부 연결·DNS는 계속 차단하며 검사 생략으로 해결하지 않았습니다.
- Windows에서 본인 학교 계정 로그인·NTFS ACL을 실검증한 것은 아닙니다. WSL 전용 러너도 아니므로
  Linux 통과가 모든 WSL 배포판/Windows Desktop 연결을 보증하지 않습니다.
- 실제 외부 LLM은 호출하지 않았습니다. 인증 검증은 승인된 단일 계정 표본이며 전 계정 보증이 아닙니다.
- 공식 공지의 전체 이력·이미지 OCR·첨부 본문·LearnUs 통합 본문 검색은 이번 검증 범위가 아닙니다.

## 이전 검증 — 0.5.0b2

검증일: **2026-10-04**. 이 기록은 아래 실행 범위의 결과이며 전 계정·전 OS·모든 답변의
정확성이나 무취약점을 보증하지 않습니다. 저장소의 코드/잠금 파일과 함께 읽으세요.
원격 GitHub Actions는 [해당 커밋의 실행](https://github.com/YOONPYOGitHub/yonsei-portal-MCP/actions)으로
별도 확인합니다. 이 표의 로컬 성공을 원격 CI 성공으로 대체하지 않습니다.

## 로컬 실행

| 검사 | 환경·범위 | 결과 |
|---|---|---|
| 변경 전 기준선 | macOS arm64, Python 3.11.15, 기존 잠금 환경 | 766 passed, 24 live deselected |
| 변경 후 전체 오프라인 | macOS arm64, Python 3.10.20, locked dev-only 환경 | 966 passed, 24 live deselected |
| 변경 후 전체 오프라인 | macOS arm64, Python 3.11.15, locked dev-only 환경 | 966 passed, 24 live deselected |
| 변경 후 전체 오프라인 | macOS arm64, Python 3.12.13, locked dev-only 환경 | 966 passed, 24 live deselected |
| 실사이트 읽기 전용 | Python 3.11.15, `tests/test_live_tools.py`, 승인된 단일 계정 | 21 passed; stdio 34개 도구 호출과 원문 비교 포함 |
| 빌드 | sdist 및 sdist에서 wheel 생성 | 성공 |
| 배포 메타데이터 | `twine check` — wheel/sdist | 모두 통과 |
| 독립 wheel 설치 | 소스 밖의 새 Python 3.11 환경, wheel `[dev]`, SDK 1.30.0 | 패키징·라이선스·무인증 stdio 검사 6 passed |
| 정적 검사 | `ruff check src tests --select E9,F63,F7,F82` | 통과; 전체 스타일/타입 검사라는 의미는 아님 |
| 런타임 의존성 감사 | macOS/Python 3.11에 적용되는 잠금 runtime 34개, pip-audit | 알려진 취약점 미탐지 |

새 wheel 설치는 lockfile과 별도로 의존성을 해결했으며 Playwright 1.63.0을 선택했다.
독립 wheel의 6개 검사는 브라우저 기동을 하지 않는다. 실제 사이트 및 DOM 검사는 잠금 환경의
Playwright 1.60.0/Chromium에서 수행했다. 각 의존성의 모든 허용 버전을 검증한 것은 아니다.

## 수정 전 실패를 확인한 회귀

- 모르는 MCP 인자/필터 오타가 무시되어 조회 범위가 넓어지는 경우.
- 잘못된 강좌 ID가 세션 무효화·재인증 경로로 들어가는 경우.
- ERP 학기 응답의 미등록 원천 필드 전달.
- 출석 중복 헤더·셀 수 불일치·로딩 중 빈 표에서 데이터 소실/잘못된 성공.
- 외부/유사 도메인·HTTP·userinfo·비허용 포트의 인증 출처 오판 및 폼 목적지 혼동.
- Settings repr의 비밀 필드 노출, 쿠키 저장 권한/원자성/안전한 파일 처리.
- 같은 키 동시 캐시 요청의 중복 작업, 만료/clear/취소/실패 계약.
- dotenv opt-out 상태에서 MCP SDK가 별도로 `.env`를 열려는 동작.
- MIT SPDX/라이선스 파일 메타데이터와 LLM SDK 없는 dev extra 계약.

수정은 합성 입력의 실패→성공 검증을 거쳤다. 실제 비밀번호·학번·성적·쿠키를 테스트 fixture로
저장하지 않았다. 실제 upstream 공격, 타인 계정 접근, 예약/신청/제출/결제는 하지 않았다.

## 실사이트 검증에서 추가로 발견한 사항

- 이전 버전의 제한되지 않은 쿠키 파일이 새 보호 검사에서 차단됐다. 본인 파일의 권한을 제한한
  후 다시 검증했다. 검사를 해제하거나 쿠키를 공개하지 않았다. 업데이트 사용자는 README의
  쿠키 권한 마이그레이션을 확인해야 한다.
- 출석 표의 정상 빈 첫 번째 제목을 새 검증이 지나치게 거절하는 회귀를 발견했다. 합성 회귀
  테스트를 추가하고 `colN` 키로 보존하도록 수정한 후 전체 실사이트 21개 검사를 다시 통과했다.
- 홈페이지 좌석 합계가 자체적으로 모순되는 경우는 원천 값을 보존하고 경고 플래그로 구분한다.
  소프트웨어가 숫자를 임의로 보정하거나 실제 배정/예약 성공을 보장하지 않는다.

## 검증 경계

- 실사이트 테스트의 성공은 단일 계정·해당 시점 표본의 성공이다. 빈 시험·장학·대출/예약 이력 응답은
  비어 있지 않은 모든 원문 형식의 검증을 대신하지 못한다.
- Windows 로그인/NTFS ACL, 다중 프로세스의 동일 쿠키 경로 공유, 전 학교 계정/캠퍼스 및
  사이트 변경 후 동작은 별도 검증이 필요하다.
- 실제 외부 LLM E2E는 이번 변경에서 실행하지 않았다. 일반 MCP에 LLM 키가 필요하지 않으며,
  결정적 단위/계약 검사와 실제 MCP/원문 대조로 검증했다.
- 취약점 감사는 조회 시점 DB·대상 의존성·실행 환경에 한정된다. 프로젝트 소스의 무취약성이나
  다른 플랫폼별 의존성까지 증명하지 않는다. 잠금 의존성 업데이트 후에도 정기적으로 재검사한다.
- CI, 코드 리뷰, secret scanner 통과는 학교 콘텐츠·개인정보 재배포 권한을 부여하지 않는다.

## 재현 명령

상세 환경 준비·격리·라이브 승인 규칙은 [DEVELOPMENT.md](DEVELOPMENT.md)를 참고하세요.

```bash
# 자격 증명 없는 개발 체크아웃·환경
uv sync --frozen --extra dev
PYTHON_DOTENV_DISABLED=1 RUN_LIVE_PORTAL=0 RUN_LIVE_LLM=0 \
  uv run --offline --no-sync python -m pytest -m "not live" -p no:cacheprovider -q

# 설정된 계정의 사용 승인을 받은 경우에만 실행하며 외부 LLM은 호출하지 않음
RUN_LIVE_PORTAL=1 RUN_LIVE_LLM=0 \
  uv run --no-sync python -m pytest tests/test_live_tools.py -x -q --tb=no --show-capture=no
```

라이브러리 설치·uv의 네트워크 설정과 실제 테스트 프로세스의 통신 허용은 별개입니다.
공개 전에는 이력·선별한 공개 파일·배포 아카이브의 비밀정보도 검사하고 결과를 커밋/PR의
검증 항목에 기록합니다. 개인 분석 보고서와 생로그는 저장소에 포함하지 않습니다.
