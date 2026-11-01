# 전체 회귀 검증 기준

감사 기준 구현: v0.2.0 (`3246754`), 현재 제품: v0.3.1. 감사에서 드러낸 계약을 유지하며 제품을 수정한다. 실패를 expectedFailure/skip으로 숨기지 않으며 통과 개수와 제품 완성도를 동일시하지 않는다. 수정 전 실패 목록은 [BASELINE.md](BASELINE.md)에 보존한다.

## 판정 근거

- 원본 필수 동작: 22.sh·25.sh 존재 검사, 문제별 복사, 스크립트가 요구하는 chall/AGENTS.md·deploy 생성, 작업 디렉터리 및 기존 풀이 보존.
- v0.2.0 약속: 실제 대화형 설치, 두 인증 방식, JSON 토큰 헤더, 실패 시 설정 보존, 별도 pip 없는 실행, 안전한 인증 저장, 일반 CTFd 개인전·팀전.
- 데이터 보존 및 안전 조건: 충돌 없는 이름, 중단 복구, 요청 제한 준수, 불완전한 파일 비공개, 압축 경로·링크·용량 검사, 비밀정보 전송 범위, 터미널 제어문자 처리.
- 세 번째 범주의 실패는 모두 원본 대비 회귀라는 뜻은 아니다. 요구 안전조건을 충족하지 못한 실제 동작을 기록한다.

## 검사 범위

| 구간 | 조건 | 자동 검사 위치 |
| --- | --- | --- |
| 새 clone·배포 | 필수 스크립트 내용·실행 권한, Git 추적, sdist·wheel 포함, 비밀 파일 제외 | test_contract_assets, test_contract_distribution |
| 실제 배포 사용 | sdist를 풀어 두 인증 방식으로 PTY 설치·실행, 별도 경로에 pip 설치한 wheel에서 checkout 없이 작업 폴더 생성 | test_installer, test_contract_distribution |
| 설치 입력 | URL 정규화·하위 경로·포트·스킴·빈 값·자격정보 포함 URL, 취소 | test_contract_setup |
| 설치 저장 | 0600/0700, 잘못된 JSON·스키마·심볼릭 링크, 인증 실패, 저장 도중 디스크 실패, 이전 설정 보존 | test_contract_setup, test_installer |
| 실제 설치 흐름 | PTY에서 토큰/아이디·비밀번호 입력, 비밀 비표시, 실제 문제/첨부/AGENTS/보조 스크립트 산출물, 기본 실행·종료 | test_installer |
| 인증·API | 토큰 JSON 헤더, 폼 nonce·쿠키, 400/401/403/408/429/500/502/503, 404/405 fallback, 선택 경로 소멸, HTML·깨진 JSON·잘못된 루트형, 시간 초과 | test_contract_http, test_monitor, test_client |
| 인증 경계 | 다른 origin으로 이동하는 실제 redirect, 절대 외부 API URL로 토큰 전송, 숫자/HTTP-date Retry-After | test_contract_http |
| 실제 CTFd | 공식 3.8.9 고정 이미지에서 토큰/비밀번호, 문제 목록/상세, 개인 풀이, 팀 정보/팀 풀이 | stock_ctfd_smoke.py (별도 CI job) |
| 문제 생명주기 | 신규·동일·설명 변경·풀이·삭제·재시작, 한글/이모지/동명/이름 변경, signed URL 갱신, 계정만 바뀐 빈 대회 | test_contract_lifecycle |
| 다운로드 | 실제 HTTP 바이트·해시·manifest·재시작, 원본 변경과 로컬 수정 백업, 짧은 응답, 크기 초과, 시작 전·전송 중 취소, 실제 SIGKILL 후 재시작, replace 실패, 중복 예약 | test_contract_transfers |
| 압축 | ZIP/TAR 정상, 경로 이탈·절대 경로·중복·symlink·hardlink·device·FIFO, 합계 크기·10000개 경계, 취소·손상 | test_contract_archives, test_archives |
| 압축 반영 | 새 버전·stale 정리·풀이 보존·부분 반영 차단·자기 archive 덮어쓰기·대상 symlink·staging 정리 | test_contract_transfers |
| 복구·동시성 | 손상 state/manifest, 부분 다운로드 청소, 풀이 파일 보존, 잠금 재획득, 이벤트 중복 방지 | test_contract_lifecycle, test_storage, test_integration |
| polling | 서버 장애→STALE→회복, backoff, 401 재인증, 대회 종료 시 마지막 정보, 빈 대회 | test_contract_runtime |
| 표시·종료 | 1×1/40×10/80×24/120×60/200×80, 한글·결합문자·이모지, countdown의 잘못된 시간대, 표준 점수판 차이, active/done/error 전송, 사건·badge 만료, 자원 graph 경계, terminal clipboard escape, PTY Ctrl-C, headless SIGTERM | test_contract_runtime, test_installer, test_integration |
| 보조 스크립트 실행 | 격리된 실제 tmux에서 4/10 pane, 실제 PTY F2/F3 전환·focus 복원, AGENTS/deploy 복사, 재접속 시 작업 보존 | test_contract_helpers_runtime |
| 선택 통합 | 비활성 시 subprocess 금지, 미지원 KOTH, 4종 adapter의 점수/순위/페이지/라운드 fixture, Codex 바이너리 없음/응답 파싱/자식 종료 | test_contract_optional |
| v0.3 제품 경계 | 각 자산 누락·빈 파일·권한 오류 시 설정 보존, 사용자 지침·스크립트 우선순위, 저장 함수 실제 도달, 전체 압축 경로 선검사, 재시작 STALE, 일반 403, probe 실패 종료, 기본 화면의 ACDC 지표 제외, 출력 폭·제어문자 | test_v030, test_contract_setup |

## 기준 스크립트

사용자가 수정한 `/home/kredsya/ctf/22.sh`, `25.sh`의 스냅샷을 `fixtures/original/`에 보관한다. v0.3.0은 같은 내용의 파일을 clone 루트와 패키지에 포함한다. fixture는 내용 비교 기준이며 실제 tmux 검사는 배포할 루트 파일을 실행한다.

- 22.sh SHA-256: `a5b7623c614e45e13038d7d54f9dc94fec1d4e797ce1a7ef7a88116a8983b0f1`
- 25.sh SHA-256: `88aab2ef97e6b5ac3b3e2f8c81aa58e71bfefab2a3126aa96b73a48e79b93f7d`

스토리지·HTTP 단독 테스트는 `helpers=[]`를 명시해 검사 대상을 격리한다. 기본 설정·설치·배포·신규 문제 계약 테스트에는 이 우회를 적용하지 않는다. 스크립트의 마지막 attach는 wrapper로 반환하고, 이후 별도 실제 PTY client를 연결해 F2/F3 키를 보낸다. tmux server/pane 생성과 모드 변화는 실제로 검사한다. `TMUX_TMPDIR`를 격리해 사용자의 tmux 서버에 접근하지 않는다.

## 실행과 증거

개발 환경에 tmux, build, coverage가 필요하다. 모니터 사용자의 설치 의존성과는 별개다.

```sh
python -m build
python -m coverage run --branch --source=ctfd_monitor tests/run_suite.py
python tests/mutation_smoke.py
python -m coverage report -m
python -m coverage xml -o test-results/coverage.xml
PYTHONPATH=src python3 tests/stock_ctfd_smoke.py  # Docker 필요
```

`test-results/results.json`에 제품 버전·import된 패키지 경로·커밋·작업 트리 변경 여부·테스트 ID·실패 trace·오류·skip을 저장한다. 실패가 하나라도 있으면 종료 코드 1이다. CI는 실패해도 test-evidence artifact를 업로드한다. 과거 v0.2.0 release와 감사 커밋은 유지한다. 새 태그의 전체 CI 성공을 배포 조건으로 삼는다.

## 판정 한계

- 상태·입력 유형의 동등 클래스와 경계값을 검사한다. 무한한 모든 바이트열, 모든 OS/CTFd 버전·플러그인 조합을 검사했다는 뜻이 아니다.
- 공식 CTFd 실서버 검증과 fixture 응답 테스트를 구분한다. KOTH/Codex의 외부 운영 서비스와 실제 계정은 이번 테스트에서 접속하지 않는다.
- tmux의 실제 F2/F3 키 입력은 검증하지만 마우스 드래그·시스템 클립보드의 사용자 상호작용은 이번 자동 검사로 보장하지 않는다.
- 단일 프로세스 coverage는 PTY 자식 프로세스의 실행을 합산하지 않는다. 줄 커버리지 100%를 달성하기 위해 단언 없는 호출을 추가하지 않는다.
- 필수 계약 테스트가 실패하면 배포하지 않는다. 배포 시에도 위의 미검사 범위는 함께 명시한다.


## 테스트 감도 검사

`mutation_smoke.py`는 임시 소스 복사본에서 다음 보호 장치를 하나씩 제거한다. 수정 전 해당 테스트의 통과를 확인하고, 수정 후 실제 테스트가 실패해야 감도 검사를 통과한다. 원본 제품 소스는 수정하지 않는다.

- GET 토큰 인증의 JSON Content-Type
- 동일 파일 동시 예약 방지
- 기존 다운로드 파일 백업
- 외부 redirect의 Authorization 제거

## v0.3.1 추가 검증

- test_comparison: 원본 좌우 구성, 총점·KOTH 차이와 색상, 풀이 비교·모두 풀이 필터, 공개 풀이 조회 캐시, 비공개 정보, 동명 계정, 좁은 화면.
- test_lab: 경기 점수와 공동 순위, 명시적 KOTH 소스·인증 격리, 공식 기간 오류·비밀번호 로그인, 포트 충돌, Award 동기화 실패와 재시도.
- lab-smoke CI: 별도 데이터 폴더의 실제 CTFd와 두 모니터를 실행해 문제·첨부·풀이·KOTH·장애·토큰 교체·재시작·초기화를 검사한다. 기존 사용자 lab 데이터는 사용하지 않는다.
- sdist에 lab 실행기·컨테이너 제어 코드·문서·기간 응답 fixture가 포함되고 lab 인증·DB가 제외되는지 검사한다.
