# v0.2.0 회귀 검사 결과

제품 기준: `3246754` (`v0.2.0`). 테스트 재작성 중 제품 `src/ctfd_monitor/`는 수정하지 않았다.

- 테스트 메서드 실행: 83개
- 실패 단언: 24건 (subTest를 포함하므로 고유 결함 수가 아님)
- 처리되지 않은 테스트 오류: 0건
- skip / expectedFailure: 0건
- 판정: 배포 검증 실패
- 현재 프로세스 줄·분기 합산 coverage: 69.9% (PTY 자식 프로세스는 미합산)

공식 CTFd 3.8.9에서는 토큰·비밀번호의 개인전/팀전 인증과 조회가 통과했다. 무효·만료 토큰과 잘못된 비밀번호는 거부됐다. 원본 스크립트 fixture의 실제 tmux 4/10 pane, F2/F3 전환, 재접속 시 작업 보존은 통과했다. 이 결과는 배포본에 스크립트가 포함되었다는 증거가 아니다.

임시 소스에서 JSON 헤더·중복 다운로드 방지·백업·redirect 토큰 제거를 각각 삭제한 4개 mutation은 모두 테스트가 탐지했다.

## 실패 목록

- `test_contract_archives.ArchiveContracts.test_zip_duplicate_absolute_symlink_and_fifo (mode=4480)`
- `test_contract_assets.AssetContracts.test_checkout_contains_current_user_scripts (name='22.sh')`
- `test_contract_assets.AssetContracts.test_checkout_contains_current_user_scripts (name='25.sh')`
- `test_contract_assets.AssetContracts.test_default_requires_both_helpers`
- `test_contract_assets.AssetContracts.test_missing_helper_is_fatal_by_default`
- `test_contract_assets.AssetContracts.test_new_problem_has_agents_file_required_by_both_scripts`
- `test_contract_display.DisplayContracts.test_comparison_handles_standard_ctfd_scoreboard`
- `test_contract_display.DisplayContracts.test_countdown_valid_missing_malformed_expired_and_naive (value='2000-01-01T00:00:00')`
- `test_contract_distribution.DistributionContracts.test_git_ignores_secrets_but_tracks_helpers`
- `test_contract_distribution.DistributionContracts.test_sdist_contains_launcher_installer_and_required_helpers (name='22.sh')`
- `test_contract_distribution.DistributionContracts.test_sdist_contains_launcher_installer_and_required_helpers (name='25.sh')`
- `test_contract_distribution.DistributionContracts.test_wheel_contains_runtime_helpers_and_no_local_secrets`
- `test_contract_http.HttpContracts.test_api_absolute_external_url_is_rejected_before_credentials_leave`
- `test_contract_lifecycle.LifecycleContracts.test_attachment_name_collision_is_unique`
- `test_contract_lifecycle.LifecycleContracts.test_team_only_change_is_persisted_for_restart`
- `test_contract_runtime.RuntimeContracts.test_closed_contest_keeps_previously_downloaded_challenges_visible`
- `test_contract_runtime.RuntimeContracts.test_render_size_unicode_and_panel_matrix (columns=1, rows=1)`
- `test_contract_runtime.RuntimeContracts.test_server_text_cannot_inject_terminal_clipboard_control`
- `test_contract_setup.SetupContracts.test_setup_must_not_report_success_with_missing_required_assets`
- `test_contract_setup.SetupContracts.test_unexplained_forbidden_is_not_misreported_as_contest_start_wait`
- `test_contract_transfers.TransferContracts.test_archive_must_not_overwrite_itself`
- `test_contract_transfers.TransferContracts.test_extraction_symlink_escape_is_reported_not_marked_complete`
- `test_installer.InstallerTests.test_clone_setup_run_both_auth_modes_and_failed_reinstall (mode='1')`
- `test_installer.InstallerTests.test_clone_setup_run_both_auth_modes_and_failed_reinstall (mode='2')`

## 판정과 재현

필수 자산 누락, 첨부 이름 충돌, 빈 대회의 계정 상태 저장 누락, 압축 자기 덮어쓰기, 심볼릭 링크 대상 누락을 완료로 표시하는 문제, 일반 CTFd 점수 비교, 시간대 없는 시각 처리 등을 구분해서 재현한다. 작은 터미널·안전 경계 실패를 모두 원본 대비 회귀로 취급하지 않는다. 세부 기준은 [TEST-MATRIX.md](TEST-MATRIX.md)에 있다.

`python -m build` 후 `python -m coverage run --branch --source=ctfd_monitor tests/run_suite.py`를 실행하면 현재는 종료 코드 1이 정상적인 검사 결과다. `test-results/results.json`에 각 실패의 traceback과 실행 환경이 저장된다. CI의 `test-evidence-*` artifact에도 실패 결과를 보존한다.

제품 수정이나 실패 은폐를 하지 않았다. 테스트 브랜치를 main에 병합하거나 새 버전을 배포하지 않는다.
