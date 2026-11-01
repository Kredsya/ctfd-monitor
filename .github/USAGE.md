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

문제가 공개되면 `workspace/<대회 이름>/<문제 이름>/`에 다음을 준비합니다.

```text
22.sh                 # tmux 창 4개
25.sh                 # tmux 창 10개
chall/
  AGENTS.md           # 기본 작업 지침 또는 사용자 템플릿
  README.md           # 최신 문제 설명
  deploy/             # 첨부 파일
```

문제 폴더에서 `./22.sh` 또는 `./25.sh`를 실행하면 `dist_1`, `dist_2`, …에 독립 작업 폴더를 만들고 창을 엽니다. F2는 동시 입력 전환, F3는 한 창 확대·복원입니다. 재접속 시 진행 중인 작업을 유지합니다. 스크립트는 셸을 열며 LLM을 자동 실행하지 않습니다. 창 분할에는 `tmux`가 필요합니다 (`sudo apt install tmux`). tmux 없이도 모니터와 다운로드는 사용할 수 있습니다.

새 문제의 `AGENTS.md`는 원문 지침으로 자동 생성합니다. 수정하지 않은 자동 생성본은 설명 변경 때 갱신하고 직접 편집한 파일은 보존합니다. 템플릿을 쓰려면 `agents_template`을 지정하세요. 보조 스크립트는 작업 폴더 루트 → 기존 clone 루트의 사용자 파일 → `helpers/` → 설치 패키지 순서로 찾습니다. 따라서 `helpers/22.sh`·`helpers/25.sh` 수정은 문제 폴더에 반영됩니다. 문제 폴더의 기존 스크립트 내용이 달라 교체할 때는 먼저 백업합니다. 다른 홈 디렉터리의 동명 파일을 자동으로 가져오지 않습니다.

## 실행과 종료

```sh
python3 ctfd-monitor.py          # 설치한 대회 모니터
python3 ctfd-monitor.py doctor   # 로컬 설정 검사
python3 ctfd-monitor.py probe    # API 접근 확인
python3 ctfd-monitor.py --headless  # JSON 상태 로그
```

터미널 출력이면 화면을 갱신하고, 파일로 리다이렉션하면 JSON 상태 로그를 출력합니다. Ctrl-C로 종료하면 화면을 지우고 색상과 커서를 복원합니다. headless 실행은 SIGTERM도 처리합니다. 실행 위치와 관계없이 스크립트 옆 설치 설정을 찾습니다. 설치 전 실행하면 설치 명령을 안내합니다.

`doctor`는 보조 스크립트의 실제 경로와 tmux 설치 여부를 출력합니다. `probe`는 인증되더라도 필수 API에 접근할 수 없으면 실패 종료 코드를 반환합니다. 빈 문제 목록은 성공한 조회와 구분해 상세 문제 검증이 아직 안 됐음을 표시합니다.

화면의 `LIVE`는 최근 조회 성공, `STALE`은 저장된 정보 표시, `UNAVAILABLE`은 서버가 알린 대회 접근 제한입니다. 명시적인 시작 전·종료 코드는 `PRE-START`·`ENDED`로 표시합니다. 장애나 종료 때문에 기존 문제·점수를 지우지 않으며, 재시작 직후에는 서버 조회가 성공할 때까지 `STALE`입니다. 일반 점수판에는 총점과 점수 차이를 표시하고 ACDC 전용 세부 점수는 기본 화면에서 제외합니다.

비교 패널은 원본의 구성을 유지합니다. 왼쪽에는 상위 상대 네 팀의 순위와 우리 팀 대비 총점·KOTH 점수 차이, 오른쪽에는 문제별 풀이 비교를 표시합니다. 표준 CTFd에서는 공개 풀이 API를 기본 10초 간격으로 조회하며, 비공개·조회 실패는 `?`로 구분합니다. 모두 푼 문제는 숨기고, 좁은 터미널에서는 두 영역을 위아래로 배치합니다. KOTH 열은 설정한 경기 목록을 사용합니다.

우리 팀도 실제 순위에 따라 행 위치가 바뀌며, 풀이 비교의 `US` 열도 같은 순서를 따릅니다. 비교 셀은 채도가 낮은 배경색을 사용합니다. 원본의 최소 창 크기 **109열 × 54행**보다 작으면 경고창을 표시합니다. 긴 문제 목록 때문에 CPU·RAM 그래프를 제거하지 않으며, 작은 창에서도 두 그래프를 압축해 유지하고 생략한 목록은 표시합니다.

KOTH는 `SOLVED`와 `UNSOLVED` 중 문제가 적은 열 아래에 표시하며, 개수가 같으면 `SOLVED` 아래에 놓습니다. 풀이 상태가 바뀌면 위치도 자동으로 바뀝니다. 경기별로 첫 줄에는 이름·순위·조회 상태, 둘째 줄에는 진행 막대·정수 환산점수를 표시합니다. 화면은 어두운 배경을 사용하며 우리 팀 행과 `US` 열은 연한 하늘색 계열로 강조합니다. 높이가 부족하면 그래프와 비교를 유지하면서 문제 목록의 생략을 표시합니다.

## 설정과 파일

설정은 `.ctfd-monitor-local/competition.toml`, 인증 정보는 같은 폴더의 `credentials-*.json`에 저장됩니다. 디렉터리는 `0700`, 파일은 `0600` 권한이며 Git에서 제외됩니다. 암호화 저장은 아니므로 이 폴더를 공유하지 마세요. 설치 도구를 다시 실행하면 검증 후 설정을 교체하고 이전 인증 파일을 삭제합니다.

설치 시 대회 이름을 입력하면 `workspace/<대회 이름>/`을 사용합니다. 공백과 경로에 쓸 수 없는 문자는 `_`로 바뀝니다. 같은 대회 이름은 같은 작업 폴더를 사용하므로 별도 작업 공간이 필요하면 다른 이름을 입력하세요. 문제 폴더에는 ID를 붙이지 않으며, 동명·정규화 충돌 때만 `_2`, `_3`을 붙입니다. 이미 상태에 저장된 문제 경로는 풀이 보존을 위해 유지합니다.

문제는 `<문제 이름>/chall/`, 첨부는 그 아래 `deploy/`, 문제 설명은 `README.md`에 저장합니다. 풀이 코드는 `deploy/` 밖에 두세요. 첨부를 교체할 때 기존 파일은 작업 폴더의 `.ctfd-monitor/<URL 해시>/archive/`에 보관합니다. 문제 ID와 폴더명의 연결은 다운로드 전에 숨김 상태 폴더의 `directories.json`에 저장해 첫 다운로드 도중 강제 종료되어도 같은 폴더로 복구합니다. 재시작 시 manifest와 이벤트를 읽어 중복 다운로드·이벤트를 줄입니다.

ZIP/TAR는 다운로드한 파일의 형식을 검사해 자동으로 압축을 해제합니다. 다운로드와 압축 해제의 고정 바이트 한도는 없습니다. 임시 디렉터리에서 링크·특수 파일·경로 이탈·중복 파일·원본 첨부 덮어쓰기·대상 심볼릭 링크를 검사하고, 10,000개 파일 한도와 취소 처리는 유지합니다. 전체 경로 검사 후 파일별로 반영하며 실패 시 완료로 기록하지 않고 재시도합니다. 첨부를 자동 실행하지 않습니다.

## 고급 설정

일반 사용에는 설정 편집이 필요하지 않습니다. 아래 옵션을 설치된 `.ctfd-monitor-local/competition.toml`에 추가할 수 있습니다.

| 키 | 의미 |
| --- | --- |
| `url`, `name` | 대회 루트 주소, 화면 제목 |
| `root`, `state` | 작업 폴더, 선택적 상태 폴더 (프로필 기준 상대 경로) |
| `poll_interval`, `max_workers` | 기본 5초, 다운로드 작업자 4개 |
| `contest_end` | 선택적 ISO 8601 종료 시각, 시간대 필수. 지정하면 서버 시각보다 우선 |
| `koth`, `koth_sources` | 기본 false. KOTH를 추가할 때만 명시적으로 활성화·어댑터·URL·배점 지정 |
| `agents_template` | 새 문제의 사용자 지침 템플릿. 생략하면 기본 지침 생성 |

기존 환경변수 프로필도 `--config`로 지정할 수 있습니다. `CTFD_MONITOR_URL/ROOT/STATE`는 프로필보다 우선합니다. `CTFD_MONITOR_TOKEN` 또는 `CTFD_MONITOR_USER/PASSWORD` 중 인증 환경변수가 하나라도 지정되어 있으면 저장된 인증 대신 환경변수 세트를 사용합니다. 기존 환경변수가 남아 있으면 먼저 해제하세요. 저장된 비밀번호·토큰을 TOML에 직접 넣지 마세요.

## 지원 범위와 검증

표준 CTFd v1 API와 사용자 토큰·일반 로그인, 일부 ACDC v2 경로를 지원합니다. SSO/MFA/CAPTCHA 로그인, 사이트 비밀번호, 모든 플러그인 자동 설정, Windows/macOS는 지원하지 않습니다. 임의 API 형식에 맞춰 코드를 자동 생성하거나 LLM을 호출하지 않습니다.

```sh
python packaging/build.py
PYTHONPATH=src python3 .github/tests/run_suite.py
```

검증 코드는 `.github/tests/`에 보관하고 GitHub Actions에서 실행합니다. clone에는 포함되며 사용자용 wheel·소스 배포에는 포함하지 않습니다. [테스트 매트릭스](https://github.com/Kredsya/ctfd-monitor/blob/main/.github/tests/TEST-MATRIX.md)와 [감사 기록](https://github.com/Kredsya/ctfd-monitor/blob/main/.github/tests/BASELINE.md), [릴리스 내역](https://github.com/Kredsya/ctfd-monitor/releases)을 참고하세요.

테스트는 JSON 헤더가 빠진 토큰 요청을 거부하는 서버, 폼 로그인, 다운로드·재시작, 대화형 설치의 두 인증 방식, 비밀 입력 비표시, 설정 파일 권한과 실패 시 기존 설정 보존을 검증합니다. GitHub Actions는 Python 3.12/3.13에서 wheel/sdist를 빌드하고 설치하여 검사합니다. 별도 작업에서는 공식 CTFd 3.8.9 이미지(고정 digest)로 토큰·비밀번호 인증, 문제 목록·상세 및 풀이 API를 검증합니다.

개발자가 패키지 배포 파일을 만들 때만 `build` 패키지가 필요합니다. `packaging/setup.py`는 빌드 전용이며, `helpers/22.sh`·`helpers/25.sh`를 wheel 안에 복사합니다. `packaging/build.py`는 임시 디렉토리에 소스와 빌드 설정을 모아 빌드하므로 현재 clone에 `.egg-info`를 만들지 않습니다. 표준 소스 배포에는 재빌드에 필요한 설정 파일이 루트에 포함되며, 해당 압축파일은 `python -m build`로 다시 빌드할 수 있습니다. 소스 디렉토리에는 스크립트 사본을 두지 않습니다. 일반 사용자 설치·실행에는 외부 패키지가 없습니다.

## v0.2.0에서 업데이트

모니터를 종료하고 `git pull --ff-only`로 업데이트한 뒤 `python3 ctfd-monitor.py doctor`, `python3 ctfd-monitor.py`를 실행하세요. 기존 설치 설정·인증·작업 폴더는 그대로 사용할 수 있으며 재설치가 필요하지 않습니다. 두 보조 스크립트는 항상 준비하며, 작업 폴더나 설치본에서 수정한 파일을 우선 사용합니다. 기존 `AGENTS.md`와 풀이 파일은 유지합니다.

로컬 CTFd 운영·검증 방법은 아래의 로컬 테스트 서버 안내를 참고하세요.

종료 시각은 대회 전용 config API 또는 기본 CTFd 공개 페이지의 `window.init.end`에서 읽고 10초 간격으로 갱신합니다. 토큰 인증만으로도 가능하며 별도 웹 로그인이 필요하지 않습니다. 종료 시각이 없는 대회는 `NO LIMIT`, 아직 정보를 얻지 못했으면 `WAITING`으로 표시합니다.

Codex 실행 파일 유무와 계정 사용량 조회 결과를 12초마다 확인해 자동으로 표시합니다. 설치·로그인·조회 실패·복구를 실행 중 다시 판단합니다. 일반 화면과 작은 화면 모두 자원 패널에 표시하며, 최초 조회 실패는 `UNAVAILABLE`, 이전 값이 있는 조회 실패는 `STALE`로 구분합니다.

CPU·메모리 막대는 각 시간 칸의 최대 측정값이며, `Peak`는 화면에 표시된 120초 구간의 막대 중 최댓값입니다. 완료된 시간 칸만 표시하므로 최신 측정값은 다음 칸 갱신 때 반영됩니다. 그래프의 시간 구간은 현재보다 최대 한 칸만큼 늦습니다(칸 길이 = 120초 ÷ 막대 개수). CPU와 메모리는 창 너비가 홀수여도 같은 개수의 막대와 시간 경계를 사용해 함께 이동합니다. 원본 샘플은 120초까지만 보관하고, 이미 완성된 막대 값은 화면 밖으로 이동할 때까지 고정합니다. 따라서 오래된 샘플이 삭제되어도 왼쪽 막대가 먼저 낮아지거나 사라지지 않습니다. 실행 이후 전체의 최대값은 아닙니다. 각 눈금 숫자가 있는 셀의 중앙을 해당 퍼센트로 사용합니다. 예를 들어 40%는 40% 행의 반 블록(`▄`), 50%는 같은 행의 꽉 찬 블록(`█`)입니다. 0% 기준선도 셀 중앙에 놓고 막대는 그 위쪽 절반부터 시작합니다. 터미널 폰트 자체의 줄 간격은 프로그램에서 제어할 수 없습니다. 분야 사이 간격은 화면 높이와 관계없이 한 줄로 유지합니다.

v0.4.0부터 KOTH는 기본 비활성입니다. 문제 ID·카테고리·서버 메타데이터·과거 캐시만으로 켜지지 않습니다. 비활성 상태에서는 해당 문제도 일반 문제 목록에 표시합니다. 사용자가 요청해 설정한 KOTH만 별도 카드와 비교 열로 분리합니다. 팀·개인 모드는 사용자·팀 API 응답으로 갱신합니다.

v0.3.3부터 `codex_usage`, `auto_extract`, `account_mode`, `helpers`, `max_download_bytes`는 설정 항목에서 제거했습니다. 기존 프로필에 남아 있는 정상 형식의 값은 호환 목적으로 읽되 무시합니다. 신규 설치 프로필에는 기록하지 않습니다. `koth`는 v0.4.0에서 명시적 비활성/활성 설정으로 다시 도입했습니다. NEW·UPDATED 배지는 60초간 종류만 표시하며 남은 시간은 표시하지 않습니다. 팀 비교의 우리 팀 행·US 열에는 옅은 하늘색 배경을 사용합니다.

KOTH 패널은 원점수 열을 생략하고 순위·진행 막대·환산점수·합계를 표시합니다. 환산점수와 합계는 정수로 반올림해 표시합니다. 내부 점수와 팀 비교 차이의 정밀도는 유지합니다. 상단에는 남은 시간의 라벨 없이 값만 표시합니다. 상단 총점은 CTFd 공식 점수판을 기준으로 표시하며 별도의 KOTH 점수를 중복 가산하지 않습니다. 대회 시작 전·종료 후에도 공식 점수판이 공개되어 있으면 총점과 순위를 계속 갱신합니다.

## KOTH

기본값은 `koth=false`입니다. KOTH 조회 스레드·외부 요청·캐시 복원·카드·비교 열이 비활성이고,
문제 파일 다운로드와 공식 총점은 계속 동작합니다. ACDC 전용 ID, API, 인증 세션, 경기명과
1,500점 고정 배점은 제거했습니다. 과거 `brick`, `neural`, `shift`, `battle` 어댑터 설정은
지원하지 않으며 오류 메시지가 이 안내로 연결됩니다.

**KOTH 화면 추가를 맡은 LLM의 시작점:** `src/ctfd_monitor/koth.py`와 같은 디렉토리의 `AGENTS.md`.
문제 풀이용 `chall/AGENTS.md`를 수정하는 작업이 아닙니다.

1. 사용자가 제공한 해당 대회의 API 응답, 인증 요구, CTFd 계정 ID 매핑, 순위·환산 공식과 최대 배점을 확인합니다.
2. 아래 generic 계약과 정확히 같으면 프로필만 설정합니다. 다르면 `koth.py`에
   `adapter(source, account_id)` 함수를 작성하고 `ADAPTERS`에 등록합니다.
3. 프로필에 `koth=true`와 필요한 `[[koth_sources]]`만 명시하고 모니터를 재시작합니다.
4. 기본 비활성, 정상 응답, 미참가, 동점/0점, 오류→회복, 재시작, 상대팀 비교를 테스트합니다.
   `.github/tests/test_koth_extension.py`, `test_koth_layout.py`가 기준입니다.

```toml
koth = true  # [[koth_sources]]보다 위의 최상위 설정

[[koth_sources]]
challenge_id = 42
adapter = "generic"
url = "https://scores.example.org/standings.json"
max_points = 1000
```

`generic`은 CTFd 표준 API가 아닌 다음 공개 JSON 예제 계약입니다.

```json
{"round": 1, "teams": [{"team_id": 7, "raw_score": 20}, {"team_id": 9, "raw_score": 10}]}
```

`team_id`는 공식 점수판의 계정 ID입니다. 이름으로 연결하지 않습니다. 환산은
`floor(max_points × raw_score / leader_score)`이며 전원 0점이면 0점, 동점은 공동 순위입니다.
미참가 계정의 점수·순위는 알 수 없음으로 유지합니다. 다른 점수 공식은 별도 어댑터를 사용합니다.

어댑터 반환값: `rank`, `teams`, `score`, `leader_score`, `points`, `max_points`,
`team_points`(문자열 계정 ID → 환산점수), 선택적 `rounds`.
`fetch()`가 형식을 검사합니다. 외부 요청에 CTFd 토큰·쿠키를 자동 전달하지 않습니다.
별도 인증이 필요한 대회는 그 요구를 확인하고 해당 어댑터에만 구현합니다.

연결 위치는 `app.py`의 `fetch_koth_metrics`(계정 조회), `refresh_koth`(수집·오류·캐시),
`render_koth`(카드), `render_team_comparison`(환산점수 차이)입니다.
최대 배점은 프로필 값이며, 공식 총점에 어댑터 점수를 다시 더하지 않습니다.
기존 좌우 배치·카드·색상·정렬 디자인은 유지합니다. 미설정 경기의 타입이나 이름을 보고
임의로 KOTH를 활성화하거나 전용 API를 추측하지 않습니다.

## 로컬 테스트 서버


저장소 루트에서 Python 3.12 이상과 Docker를 준비하고 실행합니다.

```sh
python3 lab.py
```

공식 CTFd 3.8.9 이미지를 digest로 고정합니다. 이미지가 없으면 내려받습니다. Docker 소켓에 접근할 수 없으면 `sudo -n docker`를 사용하며, 이것도 실패하면 오류를 표시합니다. CTFd와 KOTH는 localhost:8000, localhost:8001입니다. 포트가 사용 중이면 해당 프로세스를 건드리지 않습니다.

```sh
python3 lab.py --port 18000 --koth-port 18001
python3 lab.py --scenario smoke --seed 2026
```

실행기는 사용자 팀(팀원 2명), 상대 팀 5개, 관리자, 일반 문제 12개와 KOTH 3개를 만듭니다. 데이터는 `.ctfd-lab/`에 보존됩니다. 계정·토큰은 이 환경 전용으로 무작위 생성되며 메뉴에 표시됩니다. 일반 문제 설명에 제출할 플래그가 있습니다. 단일/복수 첨부, ZIP, TAR, 한글 파일명을 포함합니다.

매번 닫힌 대회로 시작합니다. `start`를 입력하면 실제 CTFd 시간 설정이 변경됩니다. Ctrl-C, EOF, `quit`는 해당 환경의 컨테이너만 중지하고 데이터를 보존합니다. 다른 대회 폴더나 이미 실행된 모니터는 수정하거나 종료하지 않습니다. 같은 데이터 폴더는 잠금으로 중복 실행을 막습니다. `--data PATH`로 독립 대회를 만들 수 있습니다.

메뉴는 명령어 입력 방식입니다. 팀·문제 ID는 `status`로 확인합니다. 주요 예:

```text
start 3600
remaining 1200
close
end
solve
solve lab-0-1 2
opponent
wrong
new Newly released challenge
hide 3
show 3
describe 3 Updated description
hint 3 Updated hint
files 3 add
files 3 replace
files 3 delete
koth random
koth set 13 1 800
koth round
koth zero
koth sync
fault ctfd offline
fault ctfd 429
fault ctfd 503
fault ctfd delay
fault ctfd normal
fault koth 503
fault koth normal
token revoke
token renew
auto start
auto stop
status
reset
quit
```

`solve`는 실제 사용자 토큰으로 제출 API를 호출합니다. 팀 단위로 이미 푼 문제는 무작위 후보에서 제외합니다. 대회가 닫혀 있으면 서버의 거부 응답을 그대로 표시합니다. `reset`은 `RESET` 입력을 요구하며 풀이·오답·KOTH 점수를 지우고 대회를 닫습니다. 계정, 토큰, 문제 변경과 작업 파일은 유지합니다. `new`는 추가 일반 문제를 공개합니다. 자동 이벤트는 5초 간격으로 정답 제출 또는 KOTH 라운드를 생성하며 고정 seed와 선택 결과를 `events.jsonl`에 기록합니다.

KOTH 원점수와 라운드는 `koth.json`에 먼저 저장하고 경기·팀별 Award 하나를 갱신합니다. 실패하면 성공을 표시하지 않습니다. 5초 간격으로 저장된 결과의 동기화를 재시도하며 `koth sync` 또는 재실행으로도 다시 맞출 수 있습니다. 선두가 0이면 전원 0점이고, 동점은 공동 순위이며 팀 ID로 표시 순서를 고정합니다. 공식 CTFd Award가 정수이므로 `1500 * 원점수 / 선두점수`의 소수 부분은 버립니다. 총점은 공식 점수판 값을 사용합니다.

KOTH 홈은 세 경기 링크를 제공하며, 각 경기의 `/13` 같은 경로에서 웹 순위표를 봅니다. `/api/games/13` JSON은 `challenge_id`, `round`, `updated_at`, `teams`를 포함하며 팀별 `team_id`, `raw_score`, `points`, `rank`를 제공합니다. 경기 ID는 해당 CTFd 문제 ID입니다.

실행기는 `token.toml`, `password.toml`, 0600 인증 파일을 생성하고 별도 터미널에 붙여 넣을 모니터 명령을 표시합니다. 이 명령은 기존 CTFD_MONITOR 인증·경로 환경변수를 해제해 로컬 프로필을 사용합니다. 모니터는 자동 실행하지 않습니다. 두 프로필은 각자 별도 작업·상태 폴더를 사용합니다. `python3 install.py`로 실제 설치 흐름을 시험할 때는 메뉴의 URL, 테스트 계정 또는 토큰을 입력하면 됩니다. 설치 대상은 별도의 비어 있는 폴더를 사용하세요.

lab이 생성하는 프로필은 테스트용 generic 어댑터와 `koth=true`를 명시합니다.
일반 설치 프로필은 `koth=false`이므로 lab URL로 설치했더라도 KOTH 화면은 자동으로 켜지지 않습니다.

정상 프록시는 공식 응답 상태·본문을 그대로 전달합니다. `fault`를 명시적으로 켠 경우에만 연결 종료, 3초 지연, 429/503을 주입합니다. 429에는 Retry-After: 2를 붙입니다. CTFd 원본은 별도의 임의 localhost 포트에서 동작하며 관리자 제어는 이 원본을 사용하므로 장애를 해제할 수 있습니다.

공식 3.8.9는 닫힌 문제 API에서 오류 코드 없이 `403 {"message":"Local monitor lab has not started yet"}`를 반환합니다. 종료 시에는 `... has ended`입니다. 모니터는 문제 API의 정확한 문구만 기간 오류로 분류하며 일반 403은 STALE로 남깁니다. 비밀번호 로그인도 닫힌 `/challenges`로 리다이렉트되어 403이 될 수 있어 `/users/me` 성공으로 인증을 검증합니다.

`--scenario smoke`는 실제 두 모니터 프로세스를 실행하고 인증, 문제·첨부·스크립트 생성, 팀원 풀이, 수정, KOTH Award 중복 방지·공식 총점, 장애와 복구, 토큰 교체, 종료 후 마지막 데이터, 서버·모니터 재시작, 초기화를 검증합니다. **이 시나리오는 지정한 로컬 대회의 풀이와 점수를 초기화하므로** 보존할 실험 데이터가 있다면 `--data`로 별도 폴더를 지정하세요. 원본 기간 응답과 모니터 로그도 그 폴더에 남깁니다.

개발 회귀 테스트:

```sh
PYTHONPATH=src python3 .github/tests/run_suite.py
```

lab 실행기는 외부 릴리스나 태그 생성을 수행하지 않습니다.
