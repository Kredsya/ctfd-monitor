# CTFd Monitor

CTFd 대회의 문제 공개·설명 변경·풀이 상태를 감시하고 첨부 파일과 풀이 작업 폴더를 준비하는 Linux용 모니터입니다. URL과 CTFd 인증 정보만 입력하면 실행할 수 있습니다. 모니터 설치에 LLM, pip, 가상환경, 별도 API 키는 필요하지 않습니다. 대회별 지침과 옵션은 시작 전에 직접 또는 LLM과 함께 수정할 수 있습니다.

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

설치 도구는 계정 인증, 문제 목록, 필수 스크립트를 확인하고 계정의 팀 소속에 따라 팀전/개인전 경로를 선택합니다. 서버가 명시적으로 대회 기간 제한을 알린 경우에는 인증 성공과 문제 접근 불가를 구분하여 표시하고 설정을 저장합니다. 그 외 403은 권한 오류로 처리합니다. 잘못된 인증, 불완전한 설치본, 연결·저장 실패가 발생하면 기존 설정을 유지합니다.

## 문제 작업 시작

문제가 공개되면 `workspace/<대회·계정 해시>/<id>_<문제 이름>/`에 다음을 준비합니다.

```text
22.sh                 # tmux 창 4개
25.sh                 # tmux 창 10개
chall/
  AGENTS.md           # 기본 작업 지침 또는 사용자 템플릿
  README.md           # 최신 문제 설명
  deploy/             # 첨부 파일
```

문제 폴더에서 `./22.sh` 또는 `./25.sh`를 실행하면 `dist_1`, `dist_2`, …에 독립 작업 폴더를 만들고 창을 엽니다. F2는 동시 입력 전환, F3는 한 창 확대·복원입니다. 재접속 시 진행 중인 작업을 유지합니다. 스크립트는 셸을 열며 LLM을 자동 실행하지 않습니다. 창 분할에는 `tmux`가 필요합니다 (`sudo apt install tmux`). tmux 없이도 모니터와 다운로드는 사용할 수 있습니다.

새 문제의 `AGENTS.md`는 자동 생성되며 기존 파일은 덮어쓰지 않습니다. 템플릿을 쓰려면 `agents_template`을 지정하세요. 보조 스크립트는 작업 폴더 루트 → clone 루트 → 설치 패키지 순서로 찾습니다. 따라서 clone의 `22.sh`·`25.sh` 수정은 문제 폴더에 반영됩니다. 문제 폴더의 기존 스크립트 내용이 달라 교체할 때는 먼저 백업합니다. 다른 홈 디렉터리의 동명 파일을 자동으로 가져오지 않습니다.

## 실행과 종료

```sh
python3 ctfd-monitor.py          # 설치한 대회 모니터
python3 ctfd-monitor.py doctor   # 로컬 설정 검사
python3 ctfd-monitor.py probe    # API 접근 확인
python3 ctfd-monitor.py --headless  # JSON 상태 로그
```

터미널 출력이면 화면을 갱신하고, 파일로 리다이렉션하면 JSON 상태 로그를 출력합니다. Ctrl-C로 종료합니다. headless 실행은 SIGTERM도 처리합니다. 실행 위치와 관계없이 스크립트 옆 설치 설정을 찾습니다. 설치 전 실행하면 설치 명령을 안내합니다.

`doctor`는 보조 스크립트의 실제 경로와 tmux 설치 여부를 출력합니다. `probe`는 인증되더라도 필수 API에 접근할 수 없으면 실패 종료 코드를 반환합니다. 빈 문제 목록은 성공한 조회와 구분해 상세 문제 검증이 아직 안 됐음을 표시합니다.

화면의 `LIVE`는 최근 조회 성공, `STALE`은 저장된 정보 표시, `UNAVAILABLE`은 서버가 알린 대회 접근 제한입니다. 명시적인 시작 전·종료 코드는 `PRE-START`·`ENDED`로 표시합니다. 장애나 종료 때문에 기존 문제·점수를 지우지 않으며, 재시작 직후에는 서버 조회가 성공할 때까지 `STALE`입니다. 일반 점수판에는 총점과 점수 차이를 표시하고 ACDC 전용 세부 점수는 기본 화면에서 제외합니다.

## 설정과 파일

설정은 `.ctfd-monitor-local/competition.toml`, 인증 정보는 같은 폴더의 `credentials-*.json`에 저장됩니다. 디렉터리는 `0700`, 파일은 `0600` 권한이며 Git에서 제외됩니다. 암호화 저장은 아니므로 이 폴더를 공유하지 마세요. 설치 도구를 다시 실행하면 검증 후 설정을 교체하고 이전 인증 파일을 삭제합니다.

작업 폴더는 `workspace/<대회 URL과 사용자 ID의 해시>/`로 자동 결정합니다. 같은 대회·계정의 재설치는 상태를 유지하며, 다른 대회나 계정은 분리됩니다. 같은 URL에서 새 대회를 개최하면 설정의 `root`를 다른 경로로 지정하세요.

문제는 `<id>_<name>/chall/`, 첨부는 그 아래 `deploy/`, 문제 설명은 `README.md`에 저장합니다. 풀이 코드는 `deploy/` 밖에 두세요. 첨부를 교체할 때 기존 파일은 작업 폴더의 `.ctfd-monitor/<URL 해시>/archive/`에 보관합니다. 재시작 시 manifest와 이벤트를 읽어 중복 다운로드·이벤트를 줄입니다.

압축 해제는 기본적으로 꺼져 있습니다. 설정의 `auto_extract = true`로 켜면 ZIP/TAR를 임시 디렉터리에서 검사하고 deploy에 반영합니다. 링크·특수 파일·경로 이탈·중복 파일, 원본 첨부 덮어쓰기, 대상 심볼릭 링크를 거부하며 10,000개 파일과 `max_download_bytes` 크기 제한을 적용합니다. 전체 경로 검사를 마친 후 파일별로 반영합니다. 여러 파일 전체를 한 번에 교체하는 파일시스템 트랜잭션은 아니며, 중단·실패 시 완료로 기록하지 않고 재시도합니다. 실행 권한이나 링크를 필요로 하는 배포 파일은 수동으로 확인 후 해제하세요. 첨부를 자동 실행하지 않습니다.

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
| `agents_template` | 새 문제의 사용자 지침 템플릿. 생략하면 기본 지침 생성 |
| `helpers` | 기본 `["22.sh", "25.sh"]`. 명시적으로 `[]`를 넣으면 복사하지 않음 |
| `koth`, `codex_usage` | 기존 ACDC용 통합, 기본 false |

기존 환경변수 프로필도 `--config`로 지정할 수 있습니다. `CTFD_MONITOR_URL/ROOT/STATE`는 프로필보다 우선합니다. `CTFD_MONITOR_TOKEN` 또는 `CTFD_MONITOR_USER/PASSWORD` 중 인증 환경변수가 하나라도 지정되어 있으면 저장된 인증 대신 환경변수 세트를 사용합니다. 기존 환경변수가 남아 있으면 먼저 해제하세요. 저장된 비밀번호·토큰을 TOML에 직접 넣지 마세요.

## 지원 범위와 검증

표준 CTFd v1 API와 사용자 토큰·일반 로그인, 일부 ACDC v2 경로를 지원합니다. SSO/MFA/CAPTCHA 로그인, 사이트 비밀번호, 모든 플러그인 자동 설정, Windows/macOS는 지원하지 않습니다. 임의 API 형식에 맞춰 코드를 자동 생성하거나 LLM을 호출하지 않습니다.

```sh
python -m build
PYTHONPATH=src python3 tests/run_suite.py
```

전체 검사 조건·실패 판정·개발용 의존성은 [테스트 매트릭스](tests/TEST-MATRIX.md)에 기록합니다. v0.2.0의 실패는 [당시 감사 기록](tests/BASELINE.md), v0.3.0의 변경 근거는 [설계·복기](docs/v0.3.0-design.md), 배포 변경은 [릴리스 노트](RELEASE-NOTES.md)를 참고하세요.

테스트는 JSON 헤더가 빠진 토큰 요청을 거부하는 서버, 폼 로그인, 다운로드·재시작, 대화형 설치의 두 인증 방식, 비밀 입력 비표시, 설정 파일 권한과 실패 시 기존 설정 보존을 검증합니다. GitHub Actions는 Python 3.12/3.13에서 wheel/sdist를 빌드하고 설치하여 검사합니다. 별도 작업에서는 공식 CTFd 3.8.9 이미지(고정 digest)로 토큰·비밀번호 인증, 문제 목록·상세 및 풀이 API를 검증합니다.

개발자가 패키지 배포 파일을 만들 때만 `build` 패키지가 필요합니다. 일반 사용자 설치·실행에는 외부 패키지가 없습니다.

## v0.2.0에서 업데이트

모니터를 종료하고 `git pull --ff-only`로 업데이트한 뒤 `python3 ctfd-monitor.py doctor`, `python3 ctfd-monitor.py`를 실행하세요. 기존 설치 설정·인증·작업 폴더는 그대로 사용할 수 있으며 재설치가 필요하지 않습니다. `helpers`를 생략한 기존 설치는 두 스크립트가 기본으로 추가됩니다. 기존 설정에 `helpers = []`를 직접 지정했다면 해당 줄을 삭제하거나 두 이름을 넣어야 복사가 활성화됩니다. 기존 `AGENTS.md`와 풀이 파일은 유지합니다.
