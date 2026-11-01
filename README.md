# CTFd Monitor

CTFd 문제 공개·변경·풀이 상태를 보여주고 첨부파일을 자동으로 내려받습니다.

## 시작하기

Linux와 Python 3.12 이상이 필요합니다.

```sh
git clone https://github.com/Kredsya/ctfd-monitor.git
cd ctfd-monitor
python3 install.py
python3 ctfd-monitor.py
```

설치 시 대회 URL과 **CTFd 토큰** 또는 **아이디·비밀번호**를 입력합니다.
pip나 가상환경은 필요하지 않습니다. **Ctrl+C**로 종료하면 화면을 지웁니다.

## 사용하기

- 문제·첨부·작업 지침은 `workspace/`에 자동 생성됩니다.
- 문제 폴더의 `22.sh`는 4개, `25.sh`는 10개의 tmux 작업 창을 엽니다.
  창 분할에만 tmux가 필요합니다: `sudo apt install tmux`
- 설정·인증은 `.ctfd-monitor-local/`에 저장됩니다. 인증 파일을 공유하지 마세요.
- 설치 점검: `python3 ctfd-monitor.py doctor`
- 로컬 테스트 대회: `python3 lab.py` — Docker 필요. 메뉴에서 `start`로 시작합니다.

[상세 사용법·설정·개발 안내](https://github.com/Kredsya/ctfd-monitor/blob/main/.github/USAGE.md)
· [릴리스 내역](https://github.com/Kredsya/ctfd-monitor/releases)
