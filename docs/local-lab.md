# localhost 대회 운영·모니터 검증 환경

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

모니터의 일반 KOTH 연동 예:

```toml
[[koth_sources]]
challenge_id = 13
adapter = "generic"
url = "http://localhost:8001/api/games/13"
max_points = 1500
```

설정한 ID는 표준 CTFd 문제도 KOTH로 분류됩니다. `generic`은 위 JSON의 팀 ID와 원점수를 읽습니다. 명시적 외부 소스는 CTFd 토큰·쿠키를 전달하지 않는 공개 조회입니다. 다른 어댑터 이름은 `brick`, `neural`, `shift`, `battle`이며 URL은 각 서비스의 루트입니다. 인증이 필요한 기존 ACDC 서비스는 명시적 소스 없이 기존 문제 ID 7/9/16/17과 launch URL을 이용하는 호환 경로를 사용합니다. 비교 화면은 설정한 경기 목록을 사용하고 총점에 KOTH를 다시 더하지 않습니다.

비교 화면은 왼쪽의 순위·상대 점수 차이와 오른쪽의 문제별 풀이 표로 구성됩니다. KOTH 열도 절대점수가 아닌 우리 팀 대비 차이입니다. 상대 풀이와 경기별 점수를 조회할 수 없으면 `?`로 표시합니다. 일반 설치 프로필에는 `koth_sources`가 자동으로 추가되지 않으므로, 세 경기 비교를 보려면 lab이 생성한 프로필을 사용하거나 해당 설정을 복사하세요.

정상 프록시는 공식 응답 상태·본문을 그대로 전달합니다. `fault`를 명시적으로 켠 경우에만 연결 종료, 3초 지연, 429/503을 주입합니다. 429에는 Retry-After: 2를 붙입니다. CTFd 원본은 별도의 임의 localhost 포트에서 동작하며 관리자 제어는 이 원본을 사용하므로 장애를 해제할 수 있습니다.

공식 3.8.9는 닫힌 문제 API에서 오류 코드 없이 `403 {"message":"Local monitor lab has not started yet"}`를 반환합니다. 종료 시에는 `... has ended`입니다. 모니터는 문제 API의 정확한 문구만 기간 오류로 분류하며 일반 403은 STALE로 남깁니다. 비밀번호 로그인도 닫힌 `/challenges`로 리다이렉트되어 403이 될 수 있어 `/users/me` 성공으로 인증을 검증합니다.

`--scenario smoke`는 실제 두 모니터 프로세스를 실행하고 인증, 문제·첨부·스크립트 생성, 팀원 풀이, 수정, KOTH Award 중복 방지·공식 총점, 장애와 복구, 토큰 교체, 종료 후 마지막 데이터, 서버·모니터 재시작, 초기화를 검증합니다. **이 시나리오는 지정한 로컬 대회의 풀이와 점수를 초기화하므로** 보존할 실험 데이터가 있다면 `--data`로 별도 폴더를 지정하세요. 원본 기간 응답과 모니터 로그도 그 폴더에 남깁니다.

개발 회귀 테스트:

```sh
PYTHONPATH=src python3 tests/run_suite.py
```

lab 실행기는 외부 릴리스나 태그 생성을 수행하지 않습니다.
