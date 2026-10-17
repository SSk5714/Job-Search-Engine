# Phase 1 test results

Run on 2026-10-17 against PostgreSQL 16 and Redis 7 (Python 3.13, Node 22, Chromium 141).

| Suite | Result |
| --- | --- |
| Backend unit + integration (`pytest`) | 66 passed, 0 failed |
| Browser walkthrough (`tests/e2e`, live stack) | 1 passed |
| Frontend typecheck (`tsc --noEmit`) | clean |
| Frontend production build (`next build`) | clean, 8 routes |
| Alembic upgrade → downgrade → upgrade | clean |
| Docker images | not built (no Docker daemon in the build environment); `docker compose config` validates |

## Acceptance criteria status

| # | Criterion | Status | Test |
| --- | --- | --- | --- |
| 1 | Multiple jobs retrieved and normalized | ✅ | `test_multiple_jobs_retrieved_and_normalized`, `test_europe_wide_search_includes_other_countries` |
| 2 | No repeated duplicate inserts | ✅ | `test_running_the_same_search_twice_inserts_no_duplicates`, `unit/test_dedup.py` |
| 3 | Score, explanation, evidence on every match | ✅ for `rules-v0`; Claude in Phase 2 | `test_every_new_job_is_classified_with_score_explanation_and_evidence` |
| 4 | Documents use verified facts | Phase 3 | — |
| 5 | Unsupported claims flagged | Phase 3 (guard exists) | `test_guard_blocks_documents_ready_without_verified_documents` |
| 6 | Forms prepared for review | Phase 4 | — |
| 7 | Submit blocked without approval | ✅ (guard) | `test_submit_is_blocked_without_approval` |
| 8 | Changing approved content invalidates approval | ✅ (backend) | `test_editing_a_form_value_invalidates_the_approval`, `test_changed_document_makes_approval_stale` |
| 9 | Failures do not corrupt records | ✅ | `test_failed_operation_leaves_records_consistent`, `test_concurrent_transitions_apply_exactly_once`, `test_one_broken_source_does_not_stop_the_others` |
| 10 | Monitor detects simulated failures | Phase 5 | — |
| 11 | View, edit, export, recover records | ✅ view/edit/export; backup drill in Phase 6 | `test_tracker_csv_export_round_trip`, `test_tracker_follow_up_and_outcome_edit` |
| 12 | Scheduled searches run unattended | Phase 5 | — |
| 13 | UI usable without agent knowledge | ✅ | `e2e/test_ui_walkthrough.py` (screenshots in `docs/screenshots/`) |
| 14 | Missing integrations shown as missing | ✅ | `test_source_labels_are_honest`, `test_unimplemented_source_is_reported_not_faked`, `test_health_details_reports_missing_integrations` |

## All tests

- tests/e2e/test_ui_walkthrough.py::test_walkthrough — skipped (needs live stack; run separately)
- tests/integration/test_api.py::test_endpoints_require_login — passed
- tests/integration/test_api.py::test_wrong_password_is_rejected — passed
- tests/integration/test_api.py::test_writes_without_csrf_header_are_refused — passed
- tests/integration/test_api.py::test_seed_profile_is_unverified_and_has_blanks_for_eligibility — passed
- tests/integration/test_api.py::test_empty_fact_cannot_be_verified — passed
- tests/integration/test_api.py::test_profile_edit_creates_version_and_resets_changed_verification — passed
- tests/integration/test_api.py::test_skill_without_context_is_rejected — passed
- tests/integration/test_api.py::test_tracker_csv_export_round_trip — passed
- tests/integration/test_api.py::test_tracker_follow_up_and_outcome_edit — passed
- tests/integration/test_api.py::test_dashboard_counts — passed
- tests/integration/test_api.py::test_health_details_reports_missing_integrations — passed
- tests/integration/test_api.py::test_job_filters — passed
- tests/integration/test_discovery.py::test_multiple_jobs_retrieved_and_normalized — passed
- tests/integration/test_discovery.py::test_running_the_same_search_twice_inserts_no_duplicates — passed
- tests/integration/test_discovery.py::test_every_new_job_is_classified_with_score_explanation_and_evidence — passed
- tests/integration/test_discovery.py::test_one_broken_source_does_not_stop_the_others — passed
- tests/integration/test_discovery.py::test_unimplemented_source_is_reported_not_faked — passed
- tests/integration/test_discovery.py::test_source_labels_are_honest — passed
- tests/integration/test_discovery.py::test_overlapping_runs_for_the_same_search_are_blocked — passed
- tests/integration/test_discovery.py::test_europe_wide_search_includes_other_countries — passed
- tests/integration/test_workflow.py::test_user_approves_and_rejects_jobs_through_the_state_machine — passed
- tests/integration/test_workflow.py::test_invalid_transition_is_refused_and_changes_nothing — passed
- tests/integration/test_workflow.py::test_user_cannot_make_orchestrator_moves — passed
- tests/integration/test_workflow.py::test_guard_blocks_documents_ready_without_verified_documents — passed
- tests/integration/test_workflow.py::test_idempotent_replay_applies_once — passed
- tests/integration/test_workflow.py::test_reused_key_with_different_body_is_rejected — passed
- tests/integration/test_workflow.py::test_state_changes_require_an_idempotency_key — passed
- tests/integration/test_workflow.py::test_stale_version_is_refused — passed
- tests/integration/test_workflow.py::test_submit_is_blocked_without_approval — passed
- tests/integration/test_workflow.py::test_approval_requires_resolving_manual_fields_first — passed
- tests/integration/test_workflow.py::test_editing_a_form_value_invalidates_the_approval — passed
- tests/integration/test_workflow.py::test_changed_document_makes_approval_stale — passed
- tests/integration/test_workflow.py::test_failed_operation_leaves_records_consistent — passed
- tests/integration/test_workflow.py::test_concurrent_transitions_apply_exactly_once — passed
- tests/integration/test_workflow.py::test_only_one_active_application_per_job — passed
- tests/integration/test_workflow.py::test_interrupt_returns_to_previous_state — passed
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1-HTTP://WWW.Example.com/jobs/1/] — passed
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1-https://example.com/jobs/1?utm_source=x&utm_medium=y] — passed
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1-https://example.com/jobs/1#apply] — passed
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1?b=2&a=1-https://example.com/jobs/1?a=1&b=2&gclid=abc] — passed
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1-https://example.com:443//jobs//1] — passed
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1-https://example.com/jobs/1?trk=public_jobs&refId=123] — passed
- tests/unit/test_dedup.py::test_meaningful_query_parameters_are_kept — passed
- tests/unit/test_dedup.py::test_different_ports_and_paths_stay_distinct — passed
- tests/unit/test_dedup.py::test_fingerprint_ignores_legal_suffix_and_gender_tag — passed
- tests/unit/test_dedup.py::test_fingerprint_differs_by_city — passed
- tests/unit/test_scoring.py::test_weights_sum_to_100 — passed
- tests/unit/test_scoring.py::test_breakdown_sums_to_score_and_respects_caps — passed
- tests/unit/test_scoring.py::test_unverified_profile_scores_zero_on_skills — passed
- tests/unit/test_scoring.py::test_every_matched_skill_has_evidence_linked_to_a_fact — passed
- tests/unit/test_scoring.py::test_student_job_without_verified_enrolment_is_never_auto_recommended — passed
- tests/unit/test_scoring.py::test_verified_low_german_fails_mandatory_german — passed
- tests/unit/test_scoring.py::test_unverified_german_is_uncertain_not_rejected — passed
- tests/unit/test_scoring.py::test_high_score_with_work_authorization_doubt_is_review_not_apply — passed
- tests/unit/test_scoring.py::test_skill_extraction_prefers_specific_spring_term — passed
- tests/unit/test_scoring.py::test_german_level_is_taken_from_the_listing — passed
- tests/unit/test_scoring.py::test_verified_b2_meets_b2_but_not_c1 — passed
- tests/unit/test_scoring.py::test_senior_roles_are_low_priority_even_with_skill_match — passed
- tests/unit/test_states.py::test_every_main_path_step_is_allowed — passed
- tests/unit/test_states.py::test_no_state_can_skip_to_submitted — passed
- tests/unit/test_states.py::test_only_orchestrator_marks_submitted_and_only_with_guard — passed
- tests/unit/test_states.py::test_user_approves_jobs_for_preparation_not_the_orchestrator — passed
- tests/unit/test_states.py::test_terminal_states_have_no_exits — passed
- tests/unit/test_states.py::test_every_active_state_can_be_withdrawn_by_user — passed
- tests/unit/test_states.py::test_interrupts_are_reachable_from_active_non_interrupt_states — passed
- tests/unit/test_states.py::test_classified_cannot_jump_to_documents_ready — passed
- tests/e2e/test_ui_walkthrough.py::test_walkthrough — passed (live stack)
