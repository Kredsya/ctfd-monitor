# CTFd Monitor

Linux용 CTFd 문제 모니터와 첨부 파일 다운로더입니다. 대회 전에 LLM과 함께 TOML 프로필을 준비하고, 대회 중에는 LLM 없이 변경 감지·다운로드·상태 복원을 실행합니다.

## 설치

Python 3.12 이상과 Linux가 필요합니다. 런타임 외부 의존성은 없습니다.

```sh
git clone https://github.com/Kredsya/ctfd-monitor.git
cd ctfd-monitor
python3 -m venv .venv
. .venv/bin/activate
pip install .
cp examples/competition.toml competition.local.toml
```

프로필의 `url`, `name`, `root`를 수정합니다. 상대 경로는 프로필 위치 기준입니다.

```sh
export CTFD_MONITOR_USER='your-user'
read -rs -p 'Password: ' CTFD_MONITOR_PASSWORD
export CTFD_MONITOR_PASSWORD
ctfd-monitor --config competition.local.toml doctor
ctfd-monitor --config competition.local.toml probe
ctfd-monitor --config competition.local.toml run
```

API 토큰은 `CTFD_MONITOR_TOKEN`에 넣습니다. 토큰이 사용자/비밀번호보다 우선합니다. 비밀 값을 프로필이나 Git에 저장하지 마세요.

## 실행과 저장

`doctor`는 로컬 설정과 인증 변수·보조 파일을 검사합니다. `probe`는 로그인하고 문제 목록·계정·팀·순위 API를 조회합니다. 대회 시작 전 비공개 API는 `unverified`일 수 있습니다. 종료 코드 0만으로 전체 호환성을 판단하지 말고 JSON 결과를 확인하세요.

`run`은 터미널 화면을 표시합니다. `--headless` 또는 출력 리다이렉션을 사용하면 JSON 상태 줄을 출력합니다. Ctrl-C 또는 headless 모드의 SIGTERM으로 종료합니다. 같은 명령으로 재시작하면 상태와 다운로드 manifest를 읽습니다.

기본 상태 경로는 `root/.ctfd-monitor/<URL 해시>`입니다. 같은 URL을 재사용하는 새 대회나 다른 계정에는 별도 root/state를 설정하세요. 문제는 `<id>_<name>/chall/`에 저장되며, 설명은 `README.md`, 첨부는 `deploy/`에 저장됩니다. 풀이 코드는 `deploy/` 밖에 두세요. 첨부를 덮어쓸 때 기존 파일은 상태 디렉터리의 archive에 보존합니다.

압축 해제는 기본적으로 꺼져 있습니다. `auto_extract = true`로 켜면 ZIP/TAR를 제한된 임시 디렉터리에 해제하고 deploy에 반영합니다. 링크·특수 파일·경로 이탈·중복 파일은 거부하며, 최대 10,000개 파일과 `max_download_bytes` 크기 제한을 적용합니다. 실행 권한이나 심볼릭 링크가 필요한 문제는 수동으로 확인 후 해제하세요. 첨부를 실행하지는 않습니다.

## 설정

| 키 | 기본값 / 의미 |
| --- | --- |
| `url`, `name` | 대회 URL, 화면 제목 |
| `root`, `state` | 작업 루트, 선택적 상태 경로 |
| `poll_interval` | 5초, 실패 시 최대 120초 백오프 |
| `max_workers` | 다운로드 작업자 4개 |
| `max_download_bytes` | 다운로드 및 압축 해제 한도 2147483648 바이트 |
| `auto_extract` | false |
| `contest_end` | 선택적 ISO 8601 시각, 시간대 필수 |
| `username_env`, `password_env`, `token_env` | 인증 환경변수 이름 |
| `agents_template` | 새 문제에만 복사할 지침 파일 |
| `helpers` | 루트·설치 모듈 폴더·홈에서 찾을 보조 파일명 목록 |
| `koth`, `codex_usage` | false, 기존 ACDC 전용 KOTH 및 Codex 통합 |

`CTFD_MONITOR_URL`, `CTFD_MONITOR_ROOT`, `CTFD_MONITOR_STATE`는 프로필 값을 덮어씁니다. 알 수 없는 설정 키는 오류입니다. 기존 AGENTS.md는 덮어쓰지 않습니다. 문제 설명은 신뢰할 수 있는 운영 지침과 분리합니다.

## LLM으로 대회 준비

1. 이 문서와 예제 프로필을 읽고 URL·인증 방식·작업 경로를 확정합니다.
2. 프로필을 만들고 `doctor`, `probe`를 실행합니다. 비밀 값을 출력하지 않습니다.
3. 시작 전 검증 불가능한 기능을 기록하고 공개 후 다시 검사합니다.
4. 특수 API가 필요하면 비밀정보를 제거한 응답 fixture와 테스트를 추가합니다. `CTFdClient`의 경로 대체와 `Monitor.normalize_challenge`를 중심으로 수정합니다.
5. 테스트 후 실행 명령·상태 경로·미검증 기능을 전달합니다.

## 개발과 배포

```sh
pip install -e .
python -m unittest discover -s tests -v
pip install build
python -m build
```

GitHub Actions는 Python 3.12/3.13에서 테스트하고 wheel/sdist를 생성합니다. 빌드 산출물은 workflow artifact에서 받을 수 있습니다. PyPI 자동 게시나 라이선스 선택은 포함하지 않습니다.

일반 CTFd v1 경로와 기존 ACDC v2 경로를 지원 대상으로 합니다. SSO/MFA·CAPTCHA 자동 로그인, 모든 CTFd 플러그인, Windows/macOS는 지원 범위 밖입니다. KOTH 구현은 아직 모니터 모듈 안에 있으며 ACDC 외 대회에서는 기본 비활성화합니다. Linux 로컬 mock 서버 테스트가 실제 대회별 인증/플러그인 검증을 대신하지는 않습니다.
