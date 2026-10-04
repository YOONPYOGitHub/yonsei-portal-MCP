# 개발 및 검증 가이드

사용자 설치는 [README](../README.md), 공개 입력·응답 계약은 [TOOLS](TOOLS.md),
기여 절차는 [CONTRIBUTING](../CONTRIBUTING.md), 비공개 취약점 신고는
[SECURITY](../SECURITY.md)를 따르세요.

## 1. 개발 환경

현재 소스 버전은 **0.6.0b1**입니다. Python 3.10 이상과 uv를 사용합니다.
잠금 환경의 MCP SDK는 **1.30.0**, 패키지 허용 범위는 `>=1.28.1,<2`입니다.
MCP 2.x와 모든 최소 의존성 조합을 검증했다는 의미는 아닙니다.

macOS·Linux·WSL과 네이티브 Windows에서 공통 설치:

```bash
uv sync --frozen --extra dev
```

macOS·Linux·WSL Bash:

```bash
PLAYWRIGHT_SKIP_BROWSER_GC=1 uv run --no-sync playwright install chromium
```

Windows PowerShell:

```powershell
$env:PLAYWRIGHT_SKIP_BROWSER_GC = "1"
uv run --no-sync playwright install chromium
```

Windows CI는 WSL이 아닌 네이티브 Python·Chromium을 사용하도록 구성했습니다. 로컬 WSL 개발 경로는 계속 사용할 수 있으며 클라이언트와 서버의 실행 OS를 맞추세요. macOS 개발도 같은 uv·pytest 경로를 사용합니다. 특정 개발 장비의 성공을 모든 OS의 로그인·파일권한 검증으로 일반화하지 않습니다.
Linux에서 Chromium 공유 라이브러리가 없으면 관리자가 `playwright install-deps chromium`을
실행해야 할 수 있습니다. 다른 프로젝트의 브라우저 리비전을 지우지 않도록 GC를 끕니다.

- `dev`: pytest·pytest-asyncio. 학교 계정과 외부 LLM 키 없이 회귀검사를 실행합니다.
- `llm`: 선택적 OpenAI·Anthropic SDK와 테스트 의존성. 제공자 어댑터/라이브 데모용입니다.
- 일반 MCP 사용은 둘 다 필요하지 않으며, LLM은 연결한 클라이언트에서 설정합니다.
- `.env.example` → `.env`: 학교 계정·브라우저 설정. 일반 MCP는 이 파일만 자동 로딩합니다.
- `.env.llm.example` → `.env.llm`: 선택적 LLM 테스트·데모 설정. 일반 MCP는 읽지 않습니다.
  별도 LLM 하네스는 `RUN_LIVE_LLM=1`일 때 저장소 루트의 `.env.llm`을 추가로 읽습니다.
  두 `.example` 파일 자체는 실행 설정이 아니라 복사·편집할 템플릿입니다. 실제 키를 코드·이슈에 넣지 마세요.

## 2. 오프라인 회귀

**비밀파일이 없는 별도 개발 체크아웃과 최소 환경**을 권장합니다. 아래 환경변수는
프로젝트/SDK dotenv 자동 읽기와 라이브 테스트 게이트를 끄지만, 이미 상속한 키를
지우거나 네트워크를 샌드박싱하지는 않습니다.

Bash:

```bash
PYTHON_DOTENV_DISABLED=1 RUN_LIVE_PORTAL=0 RUN_LIVE_LLM=0 \
  PYTHONDONTWRITEBYTECODE=1 uv run --offline --no-sync python -m pytest \
  -m "not live" -p no:cacheprovider -q --tb=short
```

PowerShell:

```powershell
$env:PYTHON_DOTENV_DISABLED = "1"
$env:RUN_LIVE_PORTAL = "0"
$env:RUN_LIVE_LLM = "0"
$env:PYTHONDONTWRITEBYTECODE = "1"
uv run --offline --no-sync python -m pytest -m "not live" -p no:cacheprovider -q --tb=short
```

전용 셸을 사용하고 작업 후 닫으세요. uv의 `--offline`은 uv 다운로드만 차단합니다.
Playwright DOM fixture 검사는 설치된 Chromium을 사용하되 실제 학교 페이지를 열지 않습니다.
`tests/smoke*.py`를 일괄 실행하면 안 됩니다. 수동 스크립트는 pytest의 live 마커 보호를 받지
않을 수 있고, 실제 포털에 접속하거나 민감정보를 출력할 수 있습니다.

### 로컬 진단 CLI

```bash
uv run --no-sync yonsei-portal-mcp doctor --json
uv run --no-sync python -m yonsei_portal_mcp doctor --browser --timeout 20
```

`doctor`는 서버/설정 모듈을 먼저 로딩하지 않는 별도 CLI이며, 인자 없는 `yonsei-portal-mcp`와 `python -m yonsei_portal_mcp`의 기본 stdio 실행은 유지합니다. 임시 작업 폴더와 허용 목록 환경의 자식 프로세스에서 `initialize`·`tools/list`만 수행하며 `tools/call`을 실행하지 않습니다. 현재 목록은 38개입니다.
기본 모드에서는 현재 폴더 `.env`의 존재만 확인하고 내용을 읽지 않으며, 상위 폴더 탐색·쿠키 읽기·로그인·포털·외부 LLM 호출을 하지 않습니다. `--env-file`로 명시한 파일만 내용 검사하며 자격 증명 값 대신 존재 여부와 출처를 출력합니다. 변수 치환·환경 변경은 하지 않으며 인증 유효성 검사도 아닙니다.
`--browser`는 임시·격리 Chromium의 `about:blank` 시작만 확인합니다. 기본은 실행 파일 유무 확인이며 Chromium/자격 증명 부재가 필수 점검 실패는 아닙니다. 종료 코드 0은 필수 로컬 준비 확인, 1은 필수 설치·stdio/요청한 브라우저 기동 실패, 2는 잘못된 인자나 명시한 설정 파일 오류입니다. `--timeout`은 각 연결 검사에 적용하며 기본 10초, 0 초과~120 이하입니다. 원시 예외·stderr·비밀값·개인 경로를 노출하지 않는 계약과 보안 감사가 아니라는 한계를 보존하세요.

### 검증 계층

| 대상 | 검사 위치 / 의미 |
|---|---|
| 원문 파서·필터·빈 결과·ICS | `tests/test_*.py`의 합성 데이터·로컬 DOM |
| 도구 경계·오타·PII·출석 구조·SDK dotenv | `tests/test_contract_hardening.py` |
| 인증 출처·자격 증명 입력 차단·쿠키 안전성·재시도 | `tests/test_security_hardening.py`, `tests/test_session.py` |
| 공개 공지 소스·페이지·본문·첨부 링크 경계 | `tests/test_university.py`, `tests/test_new_notice_tools.py` |
| LearnUs 활성 페이지·제목 검색·범위 제한 | `tests/test_board_pagination.py` |
| 무인증 진단·설정 비노출·stdio·브라우저 | `tests/test_doctor.py` |
| TTL·동시 요청·취소·실패·clear | `tests/test_cache.py` |
| 라이선스·dev extra·wheel/stdio | `tests/test_public_metadata.py`, `tests/test_packaging.py` |
| LLM 제공자 변환·runner | `tests/llm/test_providers.py` — 외부 API 실검증 아님 |
| 실사이트 원문 비교 | `tests/test_live_tools.py` — 명시적 본인 계정 승인 필요 |
| 실제 LLM + MCP | `tests/llm/test_e2e_live.py` — 추가 제공자 설정·데이터 전송 승인 필요 |

정상 입력의 호환성도 검증하세요. 예를 들어 실제 출석 표의 빈 첫 열 제목은 `col0`로 보존해야
하며, 중복/충돌하는 열 이름으로 값을 덮어쓰는 것은 거절해야 합니다. 안전성 강화라는 이유로
정상 UI를 모두 오류 처리하는 수정은 충분하지 않습니다.

## 3. SDK 설정 로딩 경계

python-dotenv의 `PYTHON_DOTENV_DISABLED`만으로 SDK의 별도 Pydantic dotenv 소스가 꺼지는
것은 아닙니다. `PortalMCP`는 opt-out 상태에서 SDK Settings의 `_env_file=None`을 적용하는
격리된 초기화 경로를 사용합니다. 프로세스 cwd·환경·SDK 전역 설정을 임시 변경하지 않습니다.
이 호환 경계는 SDK 내부 초기화에 의존하므로 SDK 업데이트 때 **파일 접근 audit hook 검사와
실제 stdio 기동 검사**를 함께 실행해야 합니다. 단순 import 성공은 dotenv 비접근 증거가 아닙니다.

## 4. 선택적 실제 포털 검증

본인 계정으로 허용된 읽기 경로만 사용합니다. 로그인·조회는 학교 접근 로그를 남길 수 있습니다.
다른 MCP 프로세스와 동일 쿠키 경로를 동시에 사용하지 마세요. 기존 쿠키가 새 권한 검사를
통과하지 못하면 [README](../README.md)의 마이그레이션 안내를 따르세요. 실패 원인을 숨기려고
TLS/출처/파일권한 검사를 해제하면 안 됩니다.

```bash
RUN_LIVE_PORTAL=1 RUN_LIVE_LLM=0 PYTHONDONTWRITEBYTECODE=1 \
  uv run --no-sync python -m pytest tests/test_live_tools.py \
  -x -q --tb=no --show-capture=no -p no:cacheprovider
```

`-x`로 첫 실패에서 멈추고, 도구·오류 코드/클래스·범위만 남겨 원인을 좁히세요. `-s`,
`--showlocals`, 원시 stderr/HTML/스크린샷 전체 저장은 피합니다. 실패/빈 결과/skip을 구분하며,
한 계정의 정상 빈 이력은 비어 있지 않은 이력 파싱을 검증하지 못합니다.

## 5. LLM 하네스 (일반 MCP 실행과 별개)

일반 MCP를 Claude Desktop·Claude Code·VS Code(GitHub Copilot)에 연결하는 사용자는 이 절의
LLM 설정이 필요 없습니다. 해당 앱의 모델·구독·API 설정을 사용합니다. 아래는 이 저장소에서
별도 모델을 직접 호출하는 **개발 테스트·데모 전용** 설정입니다.

1. `uv sync --frozen --extra dev --extra llm`으로 선택 의존성을 설치합니다.
2. `.env.example`을 `.env`로 복사해 학교 설정을 입력합니다. 이미 있는 파일은 덮어쓰지 마세요.
3. LLM 테스트를 할 때만 `.env.llm.example`을 저장소 루트의 `.env.llm`으로 복사합니다.
4. `LLM_PROVIDER`에 아래 네 값 중 하나를 넣고 **선택한 제공자의 항목만** 채웁니다.
   `<your-model-id>` 등은 자리 표시자이므로 본인 제공자 콘솔의 실제 모델/배포 ID로 바꿔야 합니다.
5. 데이터 전송·API 비용을 승인한 실행에만 환경변수 `RUN_LIVE_LLM=1`을 지정합니다.
   단순히 파일을 생성하는 것은 실행 승인이 아닙니다. 두 파일 모두 Git에서 제외됩니다.

**로딩·우선순위**

- 실행 환경변수 > 기존 `.env` > `.env.llm` 순입니다. 기존 단일 `.env` 사용자와
  `RUN_LIVE_LLM=0` 등 명시적 실행 차단을 보존하기 위해 기존 값을 덮어쓰지 않습니다.
- 분리하려면 `.env`의 LLM 관련 키만 `.env.llm`으로 옮기고 중복 키를 남기지 마세요.
  `.env`의 빈 값도 우선하므로 빈 `OPENAI_API_KEY=` 등을 남기면 뒤 파일을 가립니다.
- `.env.llm`에서는 제공자 설정 키만 허용하며 학교 자격 증명·쿠키 경로·실행 허용 플래그는
  읽지 않습니다. `RUN_LIVE_LLM`은 실행 환경 또는 `.env`에만 둡니다.
- `.env.llm`은 `${...}` 치환 없이 읽습니다. 다른 작업 폴더의 같은 이름 파일을 찾지 않습니다.
- `PYTHON_DOTENV_DISABLED=1`이면 하네스 로더는 두 파일 모두 읽지 않습니다.
  일반 MCP·doctor는 이 하네스 로더를 호출하지 않습니다.
- `tests/llm/providers.py`의 선택은 명시적인 `--provider`/`make_provider(name)` 인자 >
  `LLM_PROVIDER`입니다. factory 자체에 기본 제공자는 없습니다.

`LLM_PROVIDER` 지원값은 **`azure-openai`, `openai`, `anthropic`, `gemini`**입니다.
예를 들어 `LLM_PROVIDER=gemini`를 선택하면 `GEMINI_API_KEY`와 `GEMINI_MODEL`을 채웁니다.
Azure를 선택하면 일반 모델명이 아니라 `AZURE_OPENAI_DEPLOYMENT`에 실제 배포 이름을 넣습니다.

| 제공자 | 필요한 설정 | 호출 경로 |
|---|---|---|
| azure-openai | endpoint, deployment, Azure 키 또는 APIM 구독 키 | `AZURE_OPENAI_API_VERSION=v1`: Responses, `store=False`; 날짜 버전: Azure Chat Completions |
| openai | OPENAI_API_KEY, 계정에서 사용 가능한 OPENAI_MODEL | Chat Completions, 선택적 OPENAI_BASE_URL |
| anthropic | ANTHROPIC_API_KEY, ANTHROPIC_MODEL | Messages API; Claude Code 로그인과 별개 |
| gemini | GEMINI_API_KEY, GEMINI_MODEL | OpenAI 호환 Gemini endpoint |

Azure 키가 있으면 SDK 인증에 우선 사용하고, APIM 키는 별도 헤더에도 전달합니다. APIM 백엔드
인증·모델 배포·권한을 이 프로젝트가 자동 생성하지 않습니다. 문자열로 설정 가능한 모델과 실제
계정에서 사용 가능한 모델은 다르며, 예제 모델은 가용성/요금 보증이 아닙니다.

실행은 사용자 승인 후 `RUN_LIVE_LLM=1`로 opt-in합니다. 이 경로는 학교 데이터의 외부 LLM 전송과
API 사용량을 발생시킬 수 있습니다. `RUN_LIVE_PORTAL=0`이라도 LLM E2E가 포털 조회를 할 수 있습니다.

```bash
RUN_LIVE_LLM=1 uv run --no-sync python -m tests.llm.demo --chat --provider azure-openai
RUN_LIVE_LLM=1 uv run --no-sync python -m pytest tests/llm/test_e2e_live.py -q --tb=no --show-capture=no
```

시나리오는 도구 선택·인자·오류·빈 답변 등 일부 계약을 검사합니다. **시나리오 수는 도구 커버리지
수가 아니며, 통과가 모든 문장의 정확성을 보증하지 않습니다.** 과제/진도 구분, 시험 조회기간 미등록,
일부 페이지만 수집한 결과의 해석은 별도 결정적 검증과 원문 비교가 필요합니다. skip은 접속 성공이 아닙니다.

## 6. 빌드와 외부 설치 검증

```bash
uv lock --check
uv build
```

`dist/`의 새 wheel과 sdist에서 코드·인증서·MIT LICENSE 포함을 확인합니다. `.env` 실파일,
`.session`, `.auth`, 개인 보고서, 로컬 경로와 비밀정보가 포함되면 공개하지 마세요. 예제 `.env.*.example`만
공개할 수 있습니다. 압축파일의 파일명만 검사하지 말고 비밀정보 검사도 실행합니다.

macOS·Linux·WSL Bash 예시 (현재 디렉터리가 저장소 루트):

```bash
repo="$PWD"
scratch=$(mktemp -d)
uv venv --python 3.11 "$scratch/venv"
uv pip install --python "$scratch/venv/bin/python" \
  "$repo/dist/yonsei_portal_mcp-0.6.0b1-py3-none-any.whl[dev]"
cd "$scratch"
"$scratch/venv/bin/python" -c 'from pathlib import Path; Path("wheel-pytest.ini").write_text("[pytest]\nasyncio_mode = auto\n", encoding="utf-8")'
PYTHON_DOTENV_DISABLED=1 RUN_LIVE_PORTAL=0 RUN_LIVE_LLM=0 \
  "$scratch/venv/bin/python" -I -m pytest -c "$scratch/wheel-pytest.ini" -p no:cacheprovider \
  --import-mode=importlib "$repo/tests/test_packaging.py" "$repo/tests/test_public_metadata.py" -q
```

네이티브 Windows에서는 venv Python 경로가 `Scripts/python.exe`입니다. CI도 OS별 경로를 선택하고 실제 `wheel-pytest.ini` 파일을 생성하므로 POSIX 전용 `/dev/null` 설정 경로에 의존하지 않습니다.

이 검사는 무인증 stdio 초기화·도구 목록·설치 메타데이터 검사이지 실제 로그인/학교 데이터 정확성 검증이
아닙니다. 새 버전에서는 파일명을 실제 빌드 결과와 맞추세요. 외부 설치는 잠금 환경과 별도이므로 SDK 버전을
기록해야 합니다. PyPI 게시, release/tag 생성은 별도 승인 작업입니다.

## 7. CI와 공개 체크리스트

[CI](../.github/workflows/ci.yml)는 push·PR·수동 실행에서 다음 **5개 조합**의 오프라인 회귀·sdist/wheel 빌드·소스 트리 밖 wheel 설치 및 stdio 목록 검사를 구성합니다.

| runner | Python |
| --- | --- |
| `ubuntu-24.04` | 3.10, 3.11, 3.12 (각 1개 job) |
| `macos-latest` | 3.11 |
| `windows-latest` | 3.11 |

Windows는 Git Bash로 네이티브 setup-python·uv·Chromium을 실행하며 WSL 검사가 아닙니다. 새 네이티브 Windows runner는 구성 단계로 실제 원격 실행 결과가 아직 확인되지 않았습니다. 매트릭스 구성·로컬 성공·해당 SHA의 원격 성공을 구분하고 Windows 로그인/NTFS ACL을 검증했다고 쓰지 마세요. 학교·LLM 자격 증명 없이 `not live and not llm` 회귀를 실행합니다.

[Security](../.github/workflows/security.yml)는 push·PR·매주 월요일 04:23 UTC·수동 실행에서 별도로 수행하도록 구성했습니다.

- 잠금 파일의 **런타임 의존성만** `uv export --locked --no-dev --no-default-groups --no-emit-project`로 내보내고 해시 검증·strict 모드의 `pip-audit`로 검사합니다. 프로젝트 코드를 설치하지 않으며 공개 취약점 조회에는 네트워크가 필요합니다. 모든 OS/선택 의존성 조합의 안전성을 보장하는 것은 아닙니다.
- 체크섬으로 검증한 Gitleaks로 전체 Git 이력(`--all`)과 현재 커밋의 공개 트리(`git archive HEAD`)를 각각 검사합니다. 출력은 `--redact=100`으로 비식별화하며 보고서·민감 로그를 artifact로 업로드하지 않습니다. 로컬 `.env`·쿠키 전체를 수집하는 작업이 아닙니다.
- Actions는 SHA 고정, repository `contents: read`, checkout 인증정보 저장 비활성화 상태를 유지합니다. fork PR에 쓰기 권한·학교 계정·LLM 키를 제공하지 않습니다. 보안 workflow 구성은 실제 통과나 취약점 부재의 증거가 아닙니다.

- [ ] 재현 테스트 RED→GREEN 및 전체 회귀 결과 기록
- [ ] 학교 원문 대조 범위·비어 있는 표본·실패/skip 한계 기록
- [ ] 잠금 의존성 감사 및 새 wheel/소스 배포 내용 점검
- [ ] Git 이력과 공개할 파일의 비밀정보 검사, 개인 자료 수동 검토
- [ ] 입력/응답 변경·마이그레이션 안내·라이선스 범위 문서 일치
- [ ] 원격 커밋과 해당 SHA의 GitHub Actions 결과 확인

최신 실행 기록은 [VALIDATION.md](VALIDATION.md)에 한정된 근거로 기록합니다. 과거 `0.5.0b1`의
766개 오프라인 통과 기록을 새 커밋의 검증으로 사용하지 않습니다. 문서의 화면 캡처는 보관된 과거 실행이며
현재 상태가 아닙니다. 발견한 보안 문제는 [비공개 신고 절차](../SECURITY.md)를 따르세요.
