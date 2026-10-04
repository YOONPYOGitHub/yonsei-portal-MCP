# Validation record — 0.5.0b2

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

- Live tests의 성공은 단일 계정·해당 시점 표본의 성공이다. 빈 시험·장학·대출/예약 이력 응답은
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
# Credential-free development checkout / environment
uv sync --frozen --extra dev
PYTHON_DOTENV_DISABLED=1 RUN_LIVE_PORTAL=0 RUN_LIVE_LLM=0 \
  uv run --offline --no-sync python -m pytest -m "not live" -p no:cacheprovider -q

# Only after authorization for the configured account; no external LLM calls
RUN_LIVE_PORTAL=1 RUN_LIVE_LLM=0 \
  uv run --no-sync python -m pytest tests/test_live_tools.py -x -q --tb=no --show-capture=no
```

ライブラリのインストールやuvのネットワーク設定と、実際のテストプロセスの通信許可は別物です。
公開時は履歴・選別した公開ファイル・配布アーカイブの秘密情報検査も実施し、結果をコミット/PRの
検証欄に記録します。個人の分析レポートや生ログはリポジトリに含めません。
