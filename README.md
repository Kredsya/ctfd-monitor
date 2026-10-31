# CTFd Monitor

CTFd 대회의 문제 공개·설명 변경·풀이 상태를 감시하고 첨부 파일을 내려받는 Linux용 모니터입니다. v0.2.0부터 대화형 설치 도구가 인증 확인과 설정 저장을 수행합니다. LLM, pip, 가상환경, 별도 API 키는 필요하지 않습니다.

## 시작하기

Linux와 Python 3.12 이상이 필요합니다.

```sh
git clone https://github.com/Kredsya/ctfd-monitor.git
cd ctfd-monitor
python3 install.py
python3 ctfd-monitor.py
```

설치 도구가 묻는 정보는 다음뿐입니다.

1. 대회 루트 URL (예: `https://ctf.example.org` 또는 하위 경로를 사용하는 대회 주소)
2. 인증 방식: CTFd 토큰 또는 아이디·비밀번호
3. 선택한 인증 정보

비밀번호와 토큰은 터미널에 표시하지 않습니다. 일반 CTFd의 토큰은 사용자 Settings → Access Tokens에서 발급받습니다. 이미 발급받은 토큰으로 설치할 때는 아이디·비밀번호가 필요하지 않습니다. 토큰 인증 요청에는 GET을 포함해 `Content-Type: application/json`을 전송합니다.

설치 도구는 계정 인증과 문제 목록을 확인하고, 계정의 팀 소속에 따라 팀전/개인전 경로를 선택합니다. 대회 시작 전 접근 제한(403)은 인증 성공과 구분하여 표시하고 설정을 저장합니다. 이 경우 실제 문제 조회는 공개 후 확인해야 합니다. 잘못된 인증이나 연결 실패로 설치가 중단되면 기존 설정을 교체하지 않습니다. 다시 `python3 install.py`를 실행해 입력할 수 있습니다.

## 실행과 종료

```sh
python3 ctfd-monitor.py          # 설치한 대회 모니터
python3 ctfd-monitor.py doctor   # 로컬 설정 검사
python3 ctfd-monitor.py probe    # API 접근 확인
python3 ctfd-monitor.py --headless  # JSON 상태 로그
```

터미널 출력이면 화면을 갱신하고, 파일로 리다이렉션하면 JSON 상태 로그를 출력합니다. Ctrl-C로 종료합니다. headless 실행은 SIGTERM도 처리합니다. 실행 위치와 관계없이 스크립트 옆 설치 설정을 찾습니다. 설치 전 실행하면 설치 명령을 안내합니다.

## 설정과 파일

설정은 `.ctfd-monitor-local/competition.toml`, 인증 정보는 같은 폴더의 `credentials-*.json`에 저장됩니다. 디렉터리는 `0700`, 파일은 `0600` 권한이며 Git에서 제외됩니다. 암호화 저장은 아니므로 이 폴더를 공유하지 마세요. 설치 도구를 다시 실행하면 검증 후 설정을 교체하고 이전 인증 파일을 삭제합니다.

작업 폴더는 `workspace/<대회 URL과 사용자 ID의 해시>/`로 자동 결정합니다. 같은 대회·계정의 재설치는 상태를 유지하며, 다른 대회나 계정은 분리됩니다. 같은 URL에서 새 대회를 개최하면 설정의 `root`를 다른 경로로 지정하세요.

문제는 `<id>_<name>/chall/`, 첨부는 그 아래 `deploy/`, 문제 설명은 `README.md`에 저장합니다. 풀이 코드는 `deploy/` 밖에 두세요. 첨부를 교체할 때 기존 파일은 작업 폴더의 `.ctfd-monitor/<URL 해시>/archive/`에 보관합니다. 재시작 시 manifest와 이벤트를 읽어 중복 다운로드·이벤트를 줄입니다.

압축 해제는 기본적으로 꺼져 있습니다. 설정의 `auto_extract = true`로 켜면 ZIP/TAR를 임시 디렉터리에서 검사하고 deploy에 반영합니다. 링크·특수 파일·경로 이탈·중복 파일은 거부하며 10,000개 파일과 `max_download_bytes` 크기 제한을 적용합니다. 실행 권한이나 링크를 필요로 하는 배포 파일은 수동으로 확인 후 해제하세요. 첨부를 자동 실행하지 않습니다.

## 고급 설정

일반 사용에는 설정 편집이 필요하지 않습니다. `examples/competition.toml`의 옵션을 설치된 TOML에 추가할 수 있습니다.

| 키 | 의미 |
| --- | --- |
| `url`, `name` | 대회 루트 주소, 화면 제목 |
| `root`, `state` | 작업 폴더, 선택적 상태 폴더 (프로필 기준 상대 경로) |
| `account_mode` | users, teams 또는 auto |
| `poll_interval`, `max_workers` | 기본 5초, 다운로드 작업자 4개 |
| `max_download_bytes` | 다운로드/압축 해제 한도, 기본 2 GiB |
| `contest_end` | 선택적 ISO 8601 종료 시각, 시간대 필수 |
| `auto_extract` | 기본 false |
| `agents_template`, `helpers` | 새 문제의 선택적 지침·보조 파일 |
| `koth`, `codex_usage` | 기존 ACDC용 통합, 기본 false |

기존 환경변수 프로필도 `--config`로 지정할 수 있습니다. `CTFD_MONITOR_URL/ROOT/STATE`는 프로필보다 우선합니다. `CTFD_MONITOR_TOKEN` 또는 `CTFD_MONITOR_USER/PASSWORD` 중 인증 환경변수가 하나라도 지정되어 있으면 저장된 인증 대신 환경변수 세트를 사용합니다. 기존 환경변수가 남아 있으면 먼저 해제하세요. 저장된 비밀번호·토큰을 TOML에 직접 넣지 마세요.

## 지원 범위와 검증

표준 CTFd v1 API와 사용자 토큰·일반 로그인, 일부 ACDC v2 경로를 지원합니다. SSO/MFA/CAPTCHA 로그인, 사이트 비밀번호, 모든 플러그인 자동 설정, Windows/macOS는 지원하지 않습니다. 임의 API 형식에 맞춰 코드를 자동 생성하거나 LLM을 호출하지 않습니다.

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

테스트는 JSON 헤더가 빠진 토큰 요청을 거부하는 서버, 폼 로그인, 다운로드·재시작, 대화형 설치의 두 인증 방식, 비밀 입력 비표시, 설정 파일 권한과 실패 시 기존 설정 보존을 검증합니다. GitHub Actions는 Python 3.12/3.13에서 wheel/sdist를 빌드하고 설치하여 검사합니다. 별도 작업에서는 공식 CTFd 3.8.9 이미지(고정 digest)로 토큰·비밀번호 인증, 문제 목록·상세 및 풀이 API를 검증합니다.

개발자가 패키지 배포 파일을 만들 때만 `build` 패키지가 필요합니다. 일반 사용자 설치·실행에는 외부 패키지가 없습니다.
