# 전체 회귀 검증 기준

감사 기준 구현: v0.2.0 (`3246754`), 현재 제품: v0.3.10. 감사에서 드러낸 계약을 유지하며 제품을 수정한다. 실패를 expectedFailure/skip으로 숨기지 않으며 통과 개수와 제품 완성도를 동일시하지 않는다. 수정 전 실패 목록은 [BASELINE.md](BASELINE.md)에 보존한다.

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
| 압축 | ZIP/TAR 정상, 경로 이탈·절대 경로·중복·symlink·hardlink·device·FIFO, 추출 함수의 선택적 한도·10000개 경계, 취소·손상 | test_contract_archives, test_archives |
| 압축 반영 | 새 버전·stale 정리·풀이 보존·부분 반영 차단·자기 archive 덮어쓰기·대상 symlink·staging 정리 | test_contract_transfers |
| 복구·동시성 | 손상 state/manifest, 부분 다운로드 청소, 풀이 파일 보존, 잠금 재획득, 이벤트 중복 방지 | test_contract_lifecycle, test_storage, test_integration |
| polling | 서버 장애→STALE→회복, backoff, 401 재인증, 대회 종료 시 마지막 정보, 빈 대회 | test_contract_runtime |
| 표시·종료 | 1×1/40×10/80×24/120×60/200×80, 한글·결합문자·이모지, countdown의 잘못된 시간대, 표준 점수판 차이, active/done/error 전송, 사건·badge 만료, 자원 graph 경계, terminal clipboard escape, PTY Ctrl-C, headless SIGTERM | test_contract_runtime, test_installer, test_integration |
| 보조 스크립트 실행 | 격리된 실제 tmux에서 4/10 pane, 실제 PTY F2/F3 전환·focus 복원, AGENTS/deploy 복사, 재접속 시 작업 보존 | test_contract_helpers_runtime |
| UI 보존 | Codex 활성 프로필의 일반·작은 화면, WAITING/UNAVAILABLE/STALE/크레딧, 분야 간격, KOTH 열 정렬, CPU·메모리 순간 최대값·만료와 막대/Peak 일치 | test_ui_preservation |
| 선택 통합 | 미설치 시 subprocess 금지, 미지원 KOTH, 4종 adapter의 점수/순위/페이지/라운드 fixture, Codex 바이너리 없음/응답 파싱/자식 종료 | test_contract_optional |
| v0.3 제품 경계 | 각 자산 누락·빈 파일·권한 오류 시 설정 보존, 사용자 지침·스크립트 우선순위, 저장 함수 실제 도달, 전체 압축 경로 선검사, 재시작 STALE, 일반 403, probe 실패 종료, 기본 화면의 ACDC 지표 제외, 출력 폭·제어문자 | test_v030, test_contract_setup |

## 기준 스크립트

사용자가 수정한 `/home/kredsya/ctf/22.sh`, `25.sh`의 스냅샷을 `fixtures/original/`에 보관한다. v0.3.0은 같은 내용의 파일을 clone 루트와 패키지에 포함한다. fixture는 내용 비교 기준이며 실제 tmux 검사는 배포할 루트 파일을 실행한다.

- 22.sh SHA-256: `a5b7623c614e45e13038d7d54f9dc94fec1d4e797ce1a7ef7a88116a8983b0f1`
- 25.sh SHA-256: `88aab2ef97e6b5ac3b3e2f8c81aa58e71bfefab2a3126aa96b73a48e79b93f7d`

스토리지·HTTP 테스트도 제품과 동일하게 두 필수 보조 스크립트를 준비합니다. 스크립트의 마지막 attach는 wrapper로 반환하고, 이후 별도 실제 PTY client를 연결해 F2/F3 키를 보낸다. tmux server/pane 생성과 모드 변화는 실제로 검사한다. `TMUX_TMPDIR`를 격리해 사용자의 tmux 서버에 접근하지 않는다.

## 실행과 증거

개발 환경에 tmux, build, coverage가 필요하다. 모니터 사용자의 설치 의존성과는 별개다.

```sh
python packaging/build.py
python -m coverage run --branch --source=ctfd_monitor .github/tests/run_suite.py
python .github/tests/mutation_smoke.py
python -m coverage report -m
python -m coverage xml -o test-results/coverage.xml
PYTHONPATH=src python3 .github/tests/stock_ctfd_smoke.py  # Docker 필요
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

## v0.3.3 추가 검증

- test_v033: 실행 중 KOTH 추가/삭제, Codex 미설치/로그인 실패/복구/제거, 팀·개인 전환, 폐기한 스위치와 바이트 한도 무효화, 자동 압축 해제·필수 helper, 120초 샘플 만료, 60초 배지와 시간 표시 제거, 0% 기준선, 우리 팀 배경.

## v0.3.4 추가 검증

- test_v034: 0/20/40/60/80/100% 눈금 중앙, 46.2/50% 높이, KOTH 접두사 제거·정수 표시·열 정렬·원본 값 보존, 종료 상태에서 공식 합산 총점의 지속 갱신·중복 합산 방지·점수판 실패 시 기존 값 보존.

## v0.3.5 추가 검증

- test_ui_preservation/test_v034: 시간 값 유지·라벨 제거, KOTH 원점수 숨김·환산점수 유지·열 정렬·내부 값 보존.

## v0.3.6 추가 검증

- test_resource_timeline: 실제 ResourceSampler의 연속 프레임에서 120초 원본 샘플 삭제와 왼쪽 막대 유지·정확한 퇴장, 여러 폭의 소수점 시간 경계와 일정한 이동, 활성 칸 비표시·완료 시 최대값, CPU/메모리 Peak 일치, 누락 구간·장시간 정지·시계 역행·재시작, 폭 변경 시 캐시 분리·크기 제한·반환값 변조 격리.
- KOTH 재배치 컬러 목업은 저장소 밖에서 관리하며 제품 레이아웃 및 배포 패키지에 포함하지 않는다.

## v0.3.7 추가 검증

- test_koth_layout: 승인한 두 줄 경기 카드·색상·정렬, 문제 개수 기준 좌우 선택·동률·KOTH 제외·시작 전 표시, 풀이 변경에 따른 이동, 실행 중 KOTH 추가/제거, 높이별 테두리·생략 표시, 혼잡한 화면의 그래프·Codex·KOTH·팀 비교 보존.
- test_resource_timeline: 홀수/짝수 10가지 창 너비의 연속 프레임에서 CPU·메모리의 동일 시간 칸과 동시 이동.
- test_ui_preservation/test_v034: 두 줄 카드에 맞춰 검사 위치를 바꾸고 기존 정수 점수·소수점 비교·원점수 숨김·열 정렬 검사를 유지. 한글 이름·여러 자릿수·조회 상태를 반 너비 패널에서도 확인.

## v0.3.8 추가 검증

- test_installer: checkout·sdist 설치 후 실제 PTY에서 SIGINT 종료 시 화면 삭제·색상 초기화·커서 위치 및 표시 복원 확인.

## v0.3.9 구조 정리

- 테스트·fixture는 `.github/tests/`에서 실행하며 사용자용 배포 파일에서는 제외한다.
- 루트 보조 스크립트를 유일한 배포 원본으로 사용하고 `setup.py`의 build_py 단계에서 wheel에 복사한다. 원본 비교 fixture는 유지한다.
- checkout·sdist 대화형 설치, sdist로부터 만든 wheel의 독립 실행·보조 스크립트 권한, 문서·예제·테스트 제외를 확인한다.

## v0.3.10 루트 정리

- 배포할 보조 스크립트는 `helpers/`, 빌드 설정·실행기는 `packaging/`에서 관리한다.
- clone·sdist 설치는 `helpers/`를 검증하며 문제 폴더에 복사하는 파일명은 그대로 유지한다.
- 빌드는 임시 디렉토리에서 수행하고 wheel·sdist만 지정한 출력 폴더에 남긴다.

## v0.3.11 원본 기능 재검토 (2026-11-01)

근거: 최초 사용자 요청 및 후속 수정 요청의 Codex history, 범용화 직전
2026-10-31 15:37~15:40 UTC 소스 출력, 최초 Git 커밋 `934430e`, 현재 코드.
기능명이 남아 있는지만 검사하지 않고 데이터 생성 → 저장 → 화면/worker 전달을 확인한다.

| 영역 | 검토 결과와 검증 |
| --- | --- |
| 문제별 AGENTS | 누락 복구. 최초 한국어 Rule 전체, 제목·분야·description, 사용자 요청의 분야별 Role, 기존 Files 안내. 원문 fixture와 전체 문자열 비교. |
| 기존 작업 공간 | 수정하지 않은 구형 영어 기본 문구는 백업 후 복구. 자동 생성 지침은 문제 변경·재시작 후 갱신. 사용자 편집 및 별도 템플릿은 보존. |
| KOTH 팀 비교 | 누락 복구. 실제 KOTH 문제/어댑터가 있을 때도 공식 `koth_score_detail` 비교 사용. 공식 데이터와 어댑터 데이터를 섞지 않음. 기존 코드는 신규 재현 테스트에서 실패함. |
| 문제 공개·변경·풀이·삭제 | lifecycle, 신규 hint 변경·raw snapshot 보관 검사. 이벤트 중복 방지, 파일/풀이 보존, 재시작 복구. |
| 병렬 다운로드·자동 압축 해제 | transfers/archives 및 두 HTTP 다운로드가 실제 겹치는지 검사. 진행도·모든 활성 작업 표시, DONE 5초 후 숨김. |
| RECENT EVENTS | 해결자 이름, 최신순 정렬, 재시작 후 보존을 추가 검사. |
| 22.sh / 25.sh | 사용자가 수정한 원본 fixture 일치 및 실제 tmux 4/10 pane·F2/F3·재접속 시 작업 보존. |
| CPU/RAM | 120초 샘플, 표시된 peak, 눈금 높이, 양 그래프 동시 이동, 왼쪽 만료, 창 크기 변경에 대한 기존 테스트 재실행. |
| Codex | 자동 감지·오류·회복·미설치, 주간 잔량, 0% 때 시작→현재 credits 표시, 12초 조회 코드 유지. 실제 계정 조회는 이번 검사에서 수행하지 않음. |
| 화면 | SOLVED/UNSOLVED 분야 묶음·간격, KOTH 작은 쪽 아래 배치, 우리 팀 순위 이동/배경, 작은 창 경고, 리사이즈 및 Ctrl+C 클리어 검사 유지. |
| 점수·시간·인증 | 공식 합산 총점 우선, 중복 합산 금지, 종료 후 갱신, 종료시각 탐지, 토큰·비밀번호·팀/개인 모드에 대한 기존 테스트 재실행. |

명시적으로 삭제·변경 요청받은 항목은 복원하지 않는다: 5분 배지는 60초,
배지 남은 시간·TIME REMAINING·PROJECTED·별도 KOTH 원점수 라벨 제거,
다운로드 크기 제한/기능 on-off 스위치 제거, 문서/예제/루트 파일 정리.

원본과 달라진 채 유지하는 동작도 있다. 새 문제 폴더는 동명 충돌을 피하는
`ID_문제명` 형식이고 저장된 폴더명은 유지한다. 기본 서버 조회 간격은 원본의
2초에서 현재 5초이며 profile로 변경 가능하다. 보조 스크립트는 임의의 홈 폴더를
탐색하지 않고 작업 폴더·checkout·패키지에서 찾는다. 프로세스 이름 검색 대신
작업 공간의 파일 잠금으로 중복 실행을 막는다.

한계: KOTH 존재 여부는 실행 중 탐지하지만 임의 대회의 독자적인 점수 API까지
자동 해석하지는 않는다. ACDC 어댑터 및 별도 `koth_sources` 설정 경로가 남아 있다.
이번 검사는 원본 기록·로컬 재현 기반이며 실제 ACDC 서버 재접속이나 새 stock CTFd
컨테이너 테스트 실행을 의미하지 않는다.

실행 결과: 임시 wheel 설치본 전체 165개 + 추가 audit 4개 통과. 전체 suite에서
실패·오류·skip 0. 원문 지침 삭제 및 활성 KOTH 비교 회귀를 포함한 mutation
6개 모두 탐지. 실제 tmux 및 checkout/sdist 설치 후 PTY 종료 검사 포함.
로그는 `/tmp/ctfd-recovery-audit-10prd86m/`에 보관하고 임시 코드·가상환경은 제거했다.


## v0.3.12 이름 기반 작업 경로

- 설치 시 대회 이름을 입력받아 `workspace/<대회명>/<문제명>/`을 사용한다.
- 대회·문제 이름의 공백/경로 구분자/셸 특수문자를 정규화하며 숨김 상태 폴더와 충돌하지 않게 한다.
- 문제 ID 접두사는 제거하고 동명·대소문자·정규화 충돌에는 `_2`, `_3` 순번만 붙인다.
- 이미 기록된 문제 경로와 기존 풀이 파일은 유지한다. 재시작/문제명 변경/목록 순서 변경에도 매핑이 유지되는지 검사한다.
- 22.sh·25.sh는 이미 디렉토리 이동만 하는 원본이다. 실제 tmux 호출 기록에서 pane당 `cd` 한 번만 전송하고 `c`·`/goal`을 입력하지 않는지, 4/10 pane의 실제 cwd도 검사한다.
- checkout/sdist 설치 테스트는 대회 이름 입력부터 이름 기반 경로의 실제 첨부 다운로드까지 확인한다.

검증 결과: v0.3.12 wheel 설치본에서 175개 전체 테스트 통과, 실패·오류·skip 0.
mutation 6개 모두 탐지. 홈 디렉토리의 별도 `~/22.sh`에 남아 있던 자동 c/goal
입력은 제거하고 격리된 호출 기록으로 cd 4회만 전송함을 확인했다.
증거: `/tmp/ctfd-v0312-qnnjyya4/` (임시 코드·가상환경 제거).

## v0.4.0 KOTH 분리와 기본 비활성

- KOTH는 `koth=false`가 기본이며 명시적 `koth=true`와 `koth_sources`가 모두 필요하다.
  기존 문제 ID·타입·카테고리·점수판 확장 필드·캐시만으로 켜지지 않는다.
- 비활성 때 KOTH 조회 스레드를 시작하지 않고 외부 요청·캐시 복원·카드·비교 열을 사용하지 않는다.
  해당 문제는 일반 목록에 남고 첨부 다운로드·공식 총점은 유지한다.
- 전용 문제 ID 7/9/16/17 매핑, 네 전용 API 어댑터·세션 인증, 고정 1500점,
  경기명 약칭과 전용 점수판 필드 해석을 제품에서 제거한다.
- koth.py의 ADAPTERS와 정규화된 응답 계약을 확장 지점으로 사용한다. generic은 명시적인
  공개 JSON 예제 프로토콜이며, 임의 대회 API나 점수 공식을 자동 추측하지 않는다.
- README → .github/USAGE.md#koth, src/ctfd_monitor/AGENTS.md → koth.py에
  다음 LLM이 수정할 위치·설정·응답 형식·검증 절차를 연결한다. 문제 풀이 지침은 변경하지 않는다.
- 기존 레이아웃 검사는 명시적으로 KOTH를 활성화해 유지한다. 제거된 전용 어댑터 검사는
  test_koth_extension의 기본 비활성·generic·등록형 어댑터·오류/복구·0점/동점/미참가 계약으로 대체한다.
- lab의 테스트 프로필은 generic + koth=true를 명시한다. 일반 설치는 koth=false다.
- test_koth_extension: 비활성 중 예전 ID 문제의 다운로드, 캐시 불변, 외부 요청 부재,
  활성화 후 계정 ID별 점수 차이와 공식 총점 비중복, 조회 장애·복구·소스 변경·재시작,
  잘못된 응답/설정 거부와 새 어댑터 등록을 검증한다.
- 기본값을 임의로 true로 바꾸는 mutation을 추가해 기본 비활성 계약의 탐지를 확인한다.
- 전체 테스트에서 재현한 첫 다운로드 강제 종료 복구 문제는 directories.json에 이름 매핑을
  선저장하여 수정한다. 첫 snapshot 이전 재시작·저장 실패 재시도·손상 상태 복구도 검사한다.

최종 검증: v0.4.0 wheel 설치본에서 179개 전체 테스트 통과, 실패·오류·skip 0.
mutation 6개 탐지. checkout/sdist 설치·PTY 종료·실제 tmux·로컬 HTTP 조회 포함.
실제 ACDC 접속 및 새 Docker CTFd 구동은 이번 검증에 포함하지 않는다.
패키지·로그: `/tmp/ctfd-v040-pkj0497c/` (임시 checkout·venv 제거).
