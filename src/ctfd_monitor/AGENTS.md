# 모니터 개발 안내

이 파일은 제품 소스를 수정하는 LLM용이다. 문제 풀이용 AGENTS.md 원문은
assets.py의 agents_markdown과 .github/tests/fixtures/original/AGENTS.md에 있으며
KOTH 기능 수정 중 그 지침을 변경하지 않는다.

## KOTH 추가 요청을 받은 경우

- 먼저 koth.py의 모듈 설명과 저장소 .github/USAGE.md의 KOTH 항목을 읽는다.
- 기본값은 koth=false다. 사용자 요청 없이 자동 감지·네트워크 조회·패널을 켜지 않는다.
- 실제 API 응답/인증 방식/점수 공식을 확인한 뒤 koth.py의 ADAPTERS에 어댑터를 등록한다.
- generic과 동일한 API·점수 공식이면 코드 수정 없이 프로필의 koth=true와 koth_sources로 연결한다.
- 대회명·문제 ID·최대 배점·전용 URL을 공통 코드에 하드코딩하지 않는다.
- app.py의 fetch_koth_metrics, refresh_koth, render_koth, render_team_comparison이 연결 지점이다.
- team_points에는 CTFd 계정 ID별 환산점수를 넣는다. 화면 총점에는 다시 합산하지 않는다.
- .github/tests/test_koth_extension.py의 기본 비활성·활성·오류·복구 계약과
  test_koth_layout.py의 승인된 디자인을 유지한다. 새 어댑터의 실제 응답 fixture도 검사한다.
- 변경 시 src/ctfd_monitor/__init__.py와 packaging/pyproject.toml의 버전을 함께 올린다.
