# 개발 및 검증 가이드

개발 환경, 테스트, LLM 하네스와 릴리스 절차를 설명합니다.
사용자 설치·설정은 [README](../README.md), 도구 계약은 [TOOLS](TOOLS.md), 구현 구조는 [DESIGN](../DESIGN.md)을 참고하세요.

## 1. 지원 범위와 개발 환경

- [pyproject.toml](../pyproject.toml): 버전 `0.5.0b1`, Python `>=3.10` 선언. Linux/WSL의 3.10·3.11·3.12에서 오프라인 회귀와 wheel 설치를 검증했습니다.
- [CI](../.github/workflows/ci.yml)는 Ubuntu 24.04와 위 세 Python 버전을 사용합니다. 다른 OS와 모든 최소 의존성 조합까지 검증한 것은 아닙니다.
- MCP는 `>=1.27.2,<2`로 제한합니다. [uv.lock](../uv.lock)은 SDK 1.27.2를 고정하며, 별도 wheel 설치는 해당 범위에서 의존성을 새로 해석합니다.

저장소 루트에서 실행합니다. 아래 설치 단계는 패키지/브라우저 다운로드가 필요할 수 있습니다.
MCP 서버 자체는 클라이언트가 선택한 LLM과 연결되므로 별도 LLM API 키가 필요하지 않습니다.
`llm` extra는 개발용 pytest·pytest-asyncio와 OpenAI·Anthropic SDK를 설치합니다.

```bash
uv sync --frozen --extra llm
uv run --frozen --extra llm playwright install chromium
```

PowerShell에서도 위 두 설치 명령은 동일합니다. Linux에서 Chromium 공유 라이브러리가 부족하면
관리자가 `uv run --frozen --extra llm playwright install-deps chromium`의 시스템 변경 범위를 확인하고 별도로 설치하세요.
오프라인 테스트도 `page.set_content()`로 실제 Chromium DOM을 검사하므로 브라우저가 필요합니다.

## 2. 오프라인 테스트의 경계

[pytest 설정](../pyproject.toml)은 `tests` 아래 `test_*.py`만 자동 수집하고 asyncio 모드를 `auto`로 지정합니다.
준비가 끝난 환경에서 다음 명령은 dotenv 로딩과 라이브 게이트를 명시적으로 차단합니다.
`--offline --no-sync`는 uv의 네트워크/환경 동기화를 막지만 테스트 프로세스의 네트워크를 샌드박싱하지는 않습니다.

### Bash

```bash
PYTHON_DOTENV_DISABLED=1 RUN_LIVE_PORTAL=0 RUN_LIVE_LLM=0 \
  uv run --offline --no-sync python -m pytest -m "not live" -q
```

### PowerShell

```powershell
$env:PYTHON_DOTENV_DISABLED = "1"
$env:RUN_LIVE_PORTAL = "0"
$env:RUN_LIVE_LLM = "0"
uv run --offline --no-sync python -m pytest -m "not live" -q
```

PowerShell의 환경 변수는 해당 셸에 남습니다. 새 전용 터미널을 사용하고 작업 후 닫으세요.
`load_dotenv(override=False)` 때문에 기존 환경 변수 값이 dotenv보다 우선합니다.
dotenv 차단만으로 이미 상속된 인증정보가 제거되는 것은 아니므로 비밀정보 없는 개발 셸을 권장합니다.

| 범위 | 실행/해석 기준 |
| --- | --- |
| 파서·도구 계약·세션·ICS | `tests/test_*.py`의 합성 데이터, mock 및 로컬 DOM 검증 |
| provider 변환·하네스 | `tests/llm/test_providers.py`, 실제 외부 API 가용성 검증 아님 |
| 포털 직접 검증 | `tests/test_live_tools.py`, `RUN_LIVE_PORTAL=1`일 때만 실행 |
| 포털 + 외부 LLM | `tests/llm/test_e2e_live.py`, `RUN_LIVE_LLM=1` 및 provider 설정 필요 |

`tests/smoke*.py`는 자동 수집 대상이 아닙니다. 개별 실행 시 라이브 접속·로그인·민감정보 출력이 가능하며,
모든 smoke/수동 probe에 같은 게이트가 있다고 가정하면 안 됩니다. `tests`의 모든 Python 파일을 일괄 실행하지 마세요.
현재 자동 수집되는 실제 포털·LLM 테스트는 `live` 마커로 분리됩니다. 마커 제외와 환경 게이트를 함께 사용하고,
새 테스트를 추가할 때도 둘을 유지하세요. 개별 수동 스크립트는 pytest 마커의 보호를 받지 않습니다.

빠른 회귀는 위 오프라인 명령의 `-m pytest` 뒤에 `tests/llm/test_providers.py`를 넣어 대상을 좁히세요. 환경 게이트는 그대로 유지합니다.
파서 수정은 해당 합성/DOM 테스트, 도구 인자 변경은 스키마와 하네스 계약 테스트를 함께 확인합니다.

### 자동 CI

[ci.yml](../.github/workflows/ci.yml)은 push·pull request·수동 실행을 지원합니다. 저장소 권한은 `contents: read`, checkout 인증정보 저장은 비활성화하며 외부 액션은 커밋 SHA로 고정합니다. 학교 계정이나 LLM 키를 GitHub Secrets에 등록할 필요가 없습니다.

각 Python 버전에서 잠금 의존성과 Chromium을 설치하고, `PYTHON_DOTENV_DISABLED=1` 및 두 라이브 게이트 `0`으로 오프라인 테스트를 실행합니다. 이후 sdist/wheel을 빌드하고, 프로젝트 밖의 새 가상환경에 wheel과 테스트 실행기만 설치합니다. SDK를 별도 고정하지 않아 배포 메타데이터의 호환 범위도 검사합니다.
[test_packaging.py](../tests/test_packaging.py)는 설치 모듈·인증서·진입점과 무인증 stdio 초기화·33개 도구 등록을 확인합니다. 소스 경로가 대신 import되지 않는지도 CI에서 검사합니다. 의존성·브라우저 설치에는 네트워크가 필요하며 테스트 게이트 자체가 네트워크 샌드박스는 아닙니다.

## 3. LLM Provider 하네스

[providers.py](../tests/llm/providers.py)의 `make_provider(name)`는 명시적 인자, `LLM_PROVIDER` 순으로 선택하고
공백 제거·소문자 변환을 합니다. factory 자체에는 기본 provider가 없으며, 누락/알 수 없는 이름은 `ProviderUnavailable`입니다.
demo는 CLI `--provider` 또는 환경 설정을 쓰지만, scenarios CLI는 환경 변수가 없으면 `azure-openai`를 기본으로 넘깁니다.
API 키는 이 개발 하네스에만 필요합니다. 사용자의 MCP 클라이언트 모델 선택과 이 표의 설정은 별개입니다.

| `LLM_PROVIDER` | 필수 설정 | 코드에 들어 있는 기본값 / 선택 설정 | 호출 경로 |
| --- | --- | --- | --- |
| `azure-openai` | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, 아래 인증 키 중 하나 | `AZURE_OPENAI_API_VERSION=2024-10-21`; deployment 기본값 없음 | 날짜형 버전: Azure Chat Completions |
| `azure-openai` + `v1` | 위와 동일 | endpoint 끝에 `/openai/v1/` 추가; resource/gateway 루트 사용 | Responses, `store=False`, encrypted reasoning 재전달 |
| `openai` | `OPENAI_API_KEY` | `OPENAI_MODEL=gpt-4o-mini`; `OPENAI_BASE_URL` 미설정 시 SDK 기본 주소 | Chat Completions |
| `anthropic` | `ANTHROPIC_API_KEY` | `ANTHROPIC_MODEL=claude-sonnet-5`; 생성자 `max_tokens=1024` | Messages API, 지연 SDK import |
| `gemini` | `GEMINI_API_KEY` | `GEMINI_MODEL=gemini-3.8-flash`; `GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/` | OpenAI 호환 Chat Completions |

Azure 인증은 `AZURE_OPENAI_API_KEY`가 우선이며, 없으면 `AZURE_OPENAI_APIM_SUBSCRIPTION_KEY`를 API 키로 사용합니다.
APIM 키가 있으면 별도로 `Ocp-Apim-Subscription-Key` 헤더도 보냅니다. 두 키가 있으면 각 용도가 유지됩니다.
`v1`과 정확히 일치할 때만 Responses를 선택합니다. 날짜형 경로에는 `temperature`/`max_tokens`를 보내지 않습니다.
OpenAI 모델과 Azure API 버전의 빈 문자열은 기본값으로 대체되지 않습니다. Anthropic/Gemini의 빈 모델 값은 기본값으로 대체됩니다.
표의 모델명은 저장소 기본 문자열이지 공식 제공·권한·요금·현재 서비스 가용성 보증이 아닙니다.
접근 가능한 모델/deployment를 직접 선택해야 하며, direct OpenAI·Anthropic·Gemini의 외부 API 실검증을 했다는 뜻이 아닙니다.

하네스는 MCP 도구 스키마와 결과를 모델 형식으로 변환합니다. `run_agent` 기본 한도는 6턴, 주요 라이브 runner는 8턴입니다.
Azure Responses는 `status=completed`, Chat 계열은 `stop`/`tool_calls`, Anthropic은 `end_turn`/`stop_sequence`/`tool_use`만 완료로 받습니다.
잘린 응답·잘못된 JSON 도구 인자·MCP 오류·턴 소진·빈 최종 답변은 성공으로 보지 않습니다.
단, demo/dump의 종료 코드 0은 이 엄격한 시나리오 판정을 대신하지 못합니다.

## 4. 선택적 라이브 검증

아래는 실행 승인을 받은 본인 계정용 절차입니다. 자동 CI나 일반 온보딩에서 실행하지 마세요.
먼저 비공개 방식으로 필요한 설정을 준비하세요. 비밀값을 셸 명령에 직접 넣거나 터미널 기록에 남기지 마세요.
dotenv 대신 이미 설정된 환경을 사용하도록 예제를 구성했습니다. LLM 검증은 실제 학사정보의 외부 전송을 포함합니다.

```bash
PYTHON_DOTENV_DISABLED=1 RUN_LIVE_PORTAL=1 RUN_LIVE_LLM=0 \
  uv run --offline --no-sync python -m pytest tests/test_live_tools.py -q --tb=no --show-capture=no
PYTHON_DOTENV_DISABLED=1 RUN_LIVE_PORTAL=0 RUN_LIVE_LLM=1 \
  uv run --offline --no-sync python -m pytest tests/llm/test_e2e_live.py -q --tb=no --show-capture=no
```

```powershell
$env:PYTHON_DOTENV_DISABLED = "1"
$env:RUN_LIVE_PORTAL = "1"
$env:RUN_LIVE_LLM = "0"
uv run --offline --no-sync python -m pytest tests/test_live_tools.py -q --tb=no --show-capture=no
$env:RUN_LIVE_PORTAL = "0"
$env:RUN_LIVE_LLM = "1"
uv run --offline --no-sync python -m pytest tests/llm/test_e2e_live.py -q --tb=no --show-capture=no
$env:RUN_LIVE_LLM = "0"
```

`RUN_LIVE_PORTAL=0`이어도 `RUN_LIVE_LLM=1`인 E2E는 포털에 접속합니다. 두 값은 독립된 테스트 선택 게이트입니다.
provider fixture는 LLM 게이트부터 검사합니다. 미설정/필수 설정·SDK 누락은 skip이고, 기타 초기화 오류는 비식별 실패입니다.
skip을 provider 접속 성공으로 집계하지 마세요. `--offline`도 실제 포털/LLM 호출을 차단하지 않습니다.

- [scenarios.py](../tests/llm/scenarios.py): 33개 질문의 기대 도구 교집합, 도구 오류, 비어 있지 않은 답변을 검사합니다.
- 성적·기말시험·수강편람 시나리오는 지정 필터도 검사하고, 성적부 피드백 요청과 게시판 본문 호출을 제한합니다.
- 성공은 모든 문장·필드의 정확성이나 33개 도구 각각의 완전한 커버리지가 아닙니다. 일부 시나리오는 같은 도구를 반복 사용합니다.
- 게이트 미승인은 scenarios/dump 종료 코드 `98`, provider 불가는 scenarios `99`; scenarios 정상 완료 시 코드는 실패 시나리오 수입니다.
- demo는 게이트 미승인 `3`, provider 불가 `2`입니다. dump는 LLM을 부르지 않아도 `RUN_LIVE_LLM=1`이 필요합니다.
- 필요한 설정과 명시적 `RUN_LIVE_LLM=1` 승인 후 `uv run --offline --no-sync python -m tests.llm.scenarios --provider azure-openai`는 전체 라이브 시나리오를, `uv run --offline --no-sync python -m tests.llm.demo --chat`은 대화형 도우미를 실행합니다.
- demo는 최종 답변, scenarios는 답변과 JSON 요약, [dump_tools.py](../tests/llm/dump_tools.py)는 인자와 원시 응답을 출력합니다.

이 runner들의 출력을 공개 로그로 저장하지 마세요. `-s`, `--showlocals`, 원시 subprocess stderr를 켜는 것도 피하세요.
자동 테스트의 일부 비식별 처리가 애플리케이션 전역의 개인정보 마스킹을 보증하지는 않습니다.

### 검색·복본 집중 검증

브라우저 검색 폼과 MCP의 전체 자료 ID·순서를 대조합니다. LLM 검사는 공개 검색·상세 두 도구만 허용해
판본 누락과 복본 상태 집계를 원문과 비교하며, 특정 건수나 대출 상태를 고정하지 않습니다.

```bash
RUN_LIVE_PORTAL=1 RUN_LIVE_LLM=0 uv run --offline --no-sync python -m pytest tests/test_live_tools.py -k 'catalog_mcp or gradebook_copies' -q --tb=no --show-capture=no
RUN_LIVE_PORTAL=0 RUN_LIVE_LLM=1 uv run --offline --no-sync python -m pytest tests/llm/test_e2e_live.py -k catalog_answer -q --tb=no --show-capture=no
```

## 5. 검증 기록과 한계

다음은 로컬 검증 기록입니다. GitHub 호스팅 CI의 실행 결과와 구분합니다.

| 범위 | 확인일 | 결과 |
| --- | --- | --- |
| 최신 소스 오프라인 회귀 | 2026-10-04 | Linux/WSL·Python 3.12에서 742개 통과. 공개 좌석 미확인 계약·수동 검사, 이미지 전용 공지, ERP 준비 상태 회귀 포함 |
| 실사이트 전수 검사 | 2026-10-04 | 18개 통과. 실제 stdio 33개 도구 호출, LearnUs·도서관·학사일정 원문 비교, 프로필 최초/후속 호출과 원천 필드 대조 포함 |
| 오프라인 회귀 | 2026-09-30 | Linux/WSL, Python 3.10.20·3.11.15·3.12.3 각각 733개 통과. SDK 1.27.2 잠금 환경 |
| 독립 wheel 설치 | 2026-09-30 | 세 Python 버전 각각 4개 검사 통과. 별도 SDK 핀 없이 1.30.0 선택, 소스 경로 격리 확인 |
| 검색·복본 원문 대조 | 2026-09-29 | Python 3.12에서 7개 통과: 검색 폼/MCP 비교 6개와 성적부·복본·이력 비교 1개 |
| 실제 Azure LLM 검색 집계 | 2026-09-29 | 1개 통과: 전체 목록·관련 판본 상세·캠퍼스별 복본 상태 대조 |

CI 워크플로 스키마 검증과 테스트·설치 단계의 로컬 재현을 마쳤습니다. 각 원격 커밋의 호스팅 결과는 [GitHub Actions](https://github.com/YOONPYOGitHub/yonsei-portal-MCP/actions/workflows/ci.yml)에서 확인하세요. 이전 성공이 새 커밋의 성공을 뜻하지 않습니다.

현재 계약 전체의 33개 LLM 시나리오나 direct OpenAI·Anthropic·Gemini API 재검증 결과는 아닙니다.
비어 있지 않은 시험·장학수혜·대출 이력의 실표본은 미검증이며, 0행 응답으로 전체 이력 없음이나 날짜 필터 적용을 입증할 수 없습니다.
프로필은 새 프로세스 3개에서 성공했고 재시도 없는 원문 비교도 통과했지만 저장된 인증 상태를 사용했습니다. 과거 첫 호출의 간헐 실패 원인이나 모든 계정·최초 로그인 경로가 해결됐다는 증거는 아닙니다.
공개 좌석은 숫자가 API와 같아도 사용·잔여 의미는 미검증입니다. 별도 시설 예약 사이트는 2026-10-04 인증서 날짜 오류로 접근하지 못했으며 검증을 우회하지 않았습니다. 세미나룸 예약 조회는 현재 도구 범위 밖입니다.
새 변경은 관련 테스트를 다시 실행하고 날짜·명령·표본 범위·skip 사유를 기록하세요. 개인 원문은 기록하지 않습니다.

### 공개 베타 평가

현재 범위는 개인 계정용 읽기 전용 베타입니다. 검증된 입력·출력 계약, 회귀 검사, 원문 대조와 문서화된 제한을 전제로 소스 공개가 가능합니다. 전 계정·전 OS에서의 안정성이나 모든 LLM 답변의 정확성을 보증하는 정식 서비스는 아닙니다.

2026-10-04 공개 예정 파일과 Git 전체 이력을 gitleaks 8.30.1로 검사했습니다. 당시 이력에서 탐지된 비밀정보는 없었고, 파일 검사 1건은 README 비밀번호 자리표시자로 확인했습니다. 자격 증명·세션 경로는 추적 파일과 파일명 기준 이력에 없었습니다. 자동 검사만으로 개인정보·비밀정보가 절대 없다고 보증할 수 없으며, 이미 공개된 이력에서 실제 키가 발견되면 삭제만 하지 말고 먼저 폐기·교체해야 합니다.

남은 운영 위험은 학교 DOM·인증 변경, 최초 프로필 호출의 간헐 실패, 제한된 계정 표본, 쿠키 파일 권한의 사용자 관리입니다. 공개 좌석 의미 미확인과 세미나룸 예약 미지원은 기능 제한으로 유지하며 확인되지 않은 값을 추정해 제공하지 않습니다.

## 6. 로컬 빌드와 릴리스 준비

빌드 산출물과 버전·[릴리스 노트](../CHANGELOG.md)를 일치시키고, 소스 환경과 별도로 설치를 점검합니다.
아래 절차는 패키지를 게시하지 않습니다.

```bash
uv lock --check
uv build
uv run --with twine twine check dist/yonsei_portal_mcp-0.5.0b1-py3-none-any.whl dist/yonsei_portal_mcp-0.5.0b1.tar.gz
```

위 명령은 PowerShell에서도 같습니다. 마지막 twine 검사는 선택 사항이며 게시 명령이 아닙니다.
잠금 검사·빌드·twine 환경 준비는 의존성 다운로드가 필요할 수 있습니다. 기존 `dist`의 오래된 파일과 혼동하지 마세요.
Hatchling의 sdist와 wheel을 각각 확인하고, wheel에는 모든 패키지 모듈 및 `_certs/*.pem`이 포함되어야 합니다.
Python 소스 MIT 라이선스가 학교 공지·강의자료·조회 데이터의 저작권이나 재배포 권한까지 부여하지는 않습니다.

### 설치된 Wheel의 무인증 점검

Linux/WSL Bash 예제입니다. 방금 빌드한 **정확한 로컬 wheel 경로**를 지정하세요.
프로젝트 밖의 임시 환경에 설치하며, 인터프리터·의존성 다운로드가 필요할 수 있습니다.
wheel 설치는 `uv.lock`을 적용하지 않습니다. 별도 SDK 핀 없이 패키지 메타데이터의 범위로 설치하고, 종료 시 이 예제가 만든 임시 디렉터리만 지웁니다.

```bash
(
set -euo pipefail
wheel="$PWD/dist/yonsei_portal_mcp-0.5.0b1-py3-none-any.whl"
tests="$PWD/tests/test_packaging.py"
[[ -f "$wheel" ]]
scratch=$(mktemp -d /tmp/yonsei-wheel.XXXXXX)
trap 'rm -rf -- "$scratch"' EXIT
uv venv --python 3.12 "$scratch/venv"
uv pip install --python "$scratch/venv/bin/python" "$wheel" "pytest>=8" "pytest-asyncio>=0.24"
cd "$scratch"
env -i PATH="$PATH" HOME="$scratch" PYTHON_DOTENV_DISABLED=1 \
  RUN_LIVE_PORTAL=0 RUN_LIVE_LLM=0 "$scratch/venv/bin/python" -I - <<'PY'
import sys
from pathlib import Path
import yonsei_portal_mcp

assert Path(yonsei_portal_mcp.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
PY
env -i PATH="$PATH" HOME="$scratch" PYTHON_DOTENV_DISABLED=1 \
  RUN_LIVE_PORTAL=0 RUN_LIVE_LLM=0 "$scratch/venv/bin/python" -I -m pytest \
  -c /dev/null -p no:cacheprovider --import-mode=importlib "$tests" -q --tb=short
)
```

이 검사는 import·인증서 파일 존재·stdio 초기화·도구 목록만 확인합니다. `tools/call`, 로그인, 브라우저, 외부 HTTP/LLM은 호출하지 않습니다.
Chromium 동작·TLS 연결 성공·실제 데이터 정확성의 증거는 아닙니다. 새 릴리스에서는 예상 도구 수와 파일명을 다시 맞추세요.

### 공개 릴리스 전 권고 체크리스트

- [ ] 변경 계약, 현재 버전, 릴리스 노트, 실제 빌드 산출물의 대응 관계를 확정합니다.
- [ ] 새 wheel 설치에서 MCP 지원 범위와 stdio 기동 검사를 통과시킵니다.
- [ ] 지원 Python/OS 매트릭스를 실제 실행하고, 최소 의존성 미검증 범위를 명시합니다. 공개 CI는 무인증·오프라인 회귀로 구성합니다.
- [ ] 새 오프라인 결과와 skip 사유를 기록하고, 승인된 라이브 검증은 계정 표본·provider·계약 시점을 별도로 남깁니다.
- [ ] sdist/wheel의 모듈·인증서·라이선스 포함 및 `.env`·쿠키·개인 출력 미포함을 확인합니다. 설치 wheel 점검도 통과시킵니다.
- [ ] 현재 계약의 Azure 재검증, direct provider 가용성, 실제 0행 표본 한계를 릴리스 설명에서 숨기지 않습니다.
- [ ] 원격 반영 후 GitHub Actions의 모든 매트릭스 결과를 확인합니다.
- [ ] 미확인 범위를 릴리스 설명에 명시하고 게시 여부를 별도로 승인합니다.

## 7. 안전한 버그 보고

공개 이슈에는 아래 항목만 비식별 형태로 기입하세요. 모델 답변·도구 원문 대신 합성 데이터로 재현하면 좋습니다.

```text
환경: OS/WSL 여부, Python/uv/Playwright 버전
코드: 패키지 버전과 commit, 소스 또는 설치 wheel 여부
범위: 도구 이름, 오프라인/승인된 라이브 구분, provider 종류(해당 시)
재현: 비밀값 없는 명령, 합성 입력, 기대/실제 동작
진단: 오류 코드/클래스, 건수, 필터 일치 여부, displayed_result 등 범위 메타데이터
제외: 학번·이름·비밀번호·키·쿠키·인증 URL·강좌/도서/성적 원문·개인 파일 경로
```

필터 값·식별자·시각·URL도 개인을 식별할 수 있으면 제거하세요. 원본은 비공개로 보관하고 필요한 최소 요약만 공유합니다.