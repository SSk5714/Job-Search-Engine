# Phase 4 test results

Run on 2026-10-18 against PostgreSQL 16, Redis 7 and Chromium 141 (Playwright 1.56), with the
mock application portal in `mock-portal/`.

| Suite | Result |
| --- | --- |
| Backend unit + integration (`pytest`) | 174 passed, 0 failed (136 after Phase 3) |
| Browser walkthrough (live stack: … → prepare form → answer → approve → submit → portal receives one application) | 1 passed |
| Frontend typecheck and production build | clean |
| Alembic `0004` upgrade / downgrade, `alembic check` | clean, no drift |

## Acceptance criteria

| # | Criterion | Status | Evidence |
| --- | --- | --- | --- |
| 6 | Application forms can be prepared for review | ✅ | `test_preparation_fills_only_safe_fields_and_never_submits` |
| 7 | Submission blocked without application-specific approval | ✅ | `test_full_submission_with_approval`, `test_manual_application_is_recorded_after_approval` |
| 8 | Changing approved documents or values invalidates approval | ✅ | `test_changing_a_value_after_approval_requires_new_approval`, Phase 3 document tests |
| 9 | Failed operations don't corrupt records; no duplicate submissions | ✅ | `test_retries_never_submit_twice`, `test_unclear_outcome_stops_until_you_check`, `test_server_error_is_unknown_not_failed`, `test_form_validation_failure_sends_nothing` |

## Safety behaviour verified

- Preparation never submits (the portal receives nothing).
- Salary, start date, work permit, sponsorship, consent, gender, disability, nationality and date of birth are never proposed or filled; German labels included (`test_field_classifier.py`).
- Only verified facts and verified documents are used; missing facts are left to you (no LinkedIn URL, so nothing invented).
- The submission attempt is recorded before the browser starts. One idempotency key means one attempt.
- An unclear result, including an HTTP 500 after posting, stops the workflow and raises a critical alert until you confirm what happened. The portal did store the 500 case, which is exactly why it is not retried.
- CAPTCHA, sign-in walls, off-site redirects and LinkedIn/StepStone/Indeed/XING become manual handoffs.
- Private network addresses and `file:` URLs are blocked unless explicitly allowed for the local mock portal.

## Not tested

- Real employer portals. Every portal differs; the mock covers the common patterns. Try a real one with your own review before submitting.
- The Docker image with Chromium (no Docker daemon in the build environment).

## All tests

- tests/e2e/test_ui_walkthrough.py::test_walkthrough SKIPPED (set JOBP...) [  0%]
- tests/integration/test_adapters.py::test_greenhouse_normalizes_and_filters — PASSED
- tests/integration/test_adapters.py::test_greenhouse_requires_board_configuration — PASSED
- tests/integration/test_adapters.py::test_greenhouse_availability — PASSED
- tests/integration/test_adapters.py::test_lever_eu_region_salary_and_lists — PASSED
- tests/integration/test_adapters.py::test_personio_xml_feed — PASSED
- tests/integration/test_adapters.py::test_personio_rejects_entity_expansion_attacks — PASSED
- tests/integration/test_adapters.py::test_ba_search_detail_and_api_key — PASSED
- tests/integration/test_adapters.py::test_ba_skips_detail_for_known_jobs — PASSED
- tests/integration/test_adapters.py::test_ba_only_searches_germany — PASSED
- tests/integration/test_adapters.py::test_retry_on_429_then_success — PASSED
- tests/integration/test_adapters.py::test_persistent_server_error_is_bounded — PASSED
- tests/integration/test_adapters.py::test_forbidden_is_not_retried — PASSED
- tests/integration/test_adapters.py::test_requests_identify_themselves — PASSED
- tests/integration/test_adapters.py::test_url_resolution[https://job-boards.greenhouse.io/examplemobility/jobs/7001001-greenhouse-True] — PASSED
- tests/integration/test_adapters.py::test_url_resolution[https://boards.greenhouse.io/acme/jobs/123?gh_src=x-greenhouse-True] — PASSED
- tests/integration/test_adapters.py::test_url_resolution[https://jobs.eu.lever.co/exampleauto/3f9c1a2e-1111-4a2b-9c3d-000000000001-lever-True] — PASSED
- tests/integration/test_adapters.py::test_url_resolution[https://acme.jobs.personio.de/job/1500001?language=en-personio-True] — PASSED
- tests/integration/test_adapters.py::test_url_resolution[https://www.arbeitsagentur.de/jobsuche/jobdetail/10001-1001234567-S-ba_jobsuche-True] — PASSED
- tests/integration/test_adapters.py::test_url_resolution[https://www.linkedin.com/jobs/view/4012345678-linkedin-False] — PASSED
- tests/integration/test_adapters.py::test_url_resolution[https://www.stepstone.de/stellenangebote--Android-Entwickler--123.html-stepstone-False] — PASSED
- tests/integration/test_adapters.py::test_url_resolution[https://de.indeed.com/viewjob?jk=abc-indeed-False] — PASSED
- tests/integration/test_adapters.py::test_url_resolution[https://careers.some-company.example/job/1-manual-False] — PASSED
- tests/integration/test_adapters.py::test_html_to_text_keeps_structure_and_drops_markup — PASSED
- tests/integration/test_api.py::test_endpoints_require_login — PASSED
- tests/integration/test_api.py::test_wrong_password_is_rejected — PASSED
- tests/integration/test_api.py::test_writes_without_csrf_header_are_refused — PASSED
- tests/integration/test_api.py::test_seed_profile_is_unverified_and_has_blanks_for_eligibility — PASSED
- tests/integration/test_api.py::test_empty_fact_cannot_be_verified — PASSED
- tests/integration/test_api.py::test_profile_edit_creates_version_and_resets_changed_verification — PASSED
- tests/integration/test_api.py::test_skill_without_context_is_rejected — PASSED
- tests/integration/test_api.py::test_tracker_csv_export_round_trip — PASSED
- tests/integration/test_api.py::test_tracker_follow_up_and_outcome_edit — PASSED
- tests/integration/test_api.py::test_dashboard_counts — PASSED
- tests/integration/test_api.py::test_health_details_reports_missing_integrations — PASSED
- tests/integration/test_api.py::test_job_filters — PASSED
- tests/integration/test_claude_matching.py::test_only_verified_facts_are_sent_and_posting_is_fenced — PASSED
- tests/integration/test_claude_matching.py::test_validation_discards_invented_facts_and_quotes — PASSED
- tests/integration/test_claude_matching.py::test_search_run_uses_claude_and_records_usage — PASSED
- tests/integration/test_claude_matching.py::test_injected_instructions_in_posting_do_not_change_the_score — PASSED
- tests/integration/test_claude_matching.py::test_ai_failure_falls_back_to_rules_visibly — PASSED
- tests/integration/test_claude_matching.py::test_per_run_ai_limit — PASSED
- tests/integration/test_claude_matching.py::test_daily_budget_stops_ai_calls — PASSED
- tests/integration/test_claude_matching.py::test_rules_matcher_setting_never_calls_claude — PASSED
- tests/integration/test_claude_matching.py::test_without_api_key_rules_are_used — PASSED
- tests/integration/test_claude_matching.py::test_claude_provider_uses_structured_outputs_and_prices_usage — PASSED
- tests/integration/test_claude_matching.py::test_claude_refusal_and_truncation_are_errors — PASSED
- tests/integration/test_claude_matching.py::test_claude_rate_limit_maps_to_retryable_error — PASSED
- tests/integration/test_claude_matching.py::test_unknown_model_costs_zero_rather_than_guessing — PASSED
- tests/integration/test_discovery.py::test_multiple_jobs_retrieved_and_normalized — PASSED
- tests/integration/test_discovery.py::test_running_the_same_search_twice_inserts_no_duplicates — PASSED
- tests/integration/test_discovery.py::test_every_new_job_is_classified_with_score_explanation_and_evidence — PASSED
- tests/integration/test_discovery.py::test_one_broken_source_does_not_stop_the_others — PASSED
- tests/integration/test_discovery.py::test_manual_only_sources_cannot_be_scheduled_for_automated_search — PASSED
- tests/integration/test_discovery.py::test_source_needing_configuration_reports_it — PASSED
- tests/integration/test_discovery.py::test_source_labels_are_honest — PASSED
- tests/integration/test_discovery.py::test_overlapping_runs_for_the_same_search_are_blocked — PASSED
- tests/integration/test_discovery.py::test_europe_wide_search_includes_other_countries — PASSED
- tests/integration/test_documents.py::test_template_documents_are_verified_rendered_and_advance_state — PASSED
- tests/integration/test_documents.py::test_unverified_facts_never_appear — PASSED
- tests/integration/test_documents.py::test_missing_name_blocks_ready — PASSED
- tests/integration/test_documents.py::test_claude_fabrication_is_caught_then_fixed_by_editing — PASSED
- tests/integration/test_documents.py::test_editing_after_approval_invalidates_it — PASSED
- tests/integration/test_documents.py::test_generation_requires_an_approved_job — PASSED
- tests/integration/test_documents.py::test_malformed_edit_is_rejected — PASSED
- tests/integration/test_documents.py::test_master_cv_and_profile_roundtrip — PASSED
- tests/integration/test_documents.py::test_import_never_marks_new_facts_verified — PASSED
- tests/integration/test_phase2_api.py::test_scoring_settings_validation_and_rescore — PASSED
- tests/integration/test_phase2_api.py::test_ai_settings_report_status — PASSED
- tests/integration/test_phase2_api.py::test_real_adapters_in_a_run_and_live_verification — PASSED
- tests/integration/test_phase2_api.py::test_import_from_api_backed_url — PASSED
- tests/integration/test_phase2_api.py::test_linkedin_urls_are_never_fetched — PASSED
- tests/integration/test_phase2_api.py::test_import_same_url_twice_is_a_duplicate — PASSED
- tests/integration/test_phase2_api.py::test_recheck_closed_listing_expires_application — PASSED
- tests/integration/test_phase2_api.py::test_approval_rechecks_availability_first — PASSED
- tests/integration/test_phase2_api.py::test_source_outage_is_reported_per_source — PASSED
- tests/integration/test_preparation.py::test_preparation_fills_only_safe_fields_and_never_submits — PASSED
- tests/integration/test_preparation.py::test_full_submission_with_approval — PASSED
- tests/integration/test_preparation.py::test_retries_never_submit_twice — PASSED
- tests/integration/test_preparation.py::test_unclear_outcome_stops_until_you_check — PASSED
- tests/integration/test_preparation.py::test_server_error_is_unknown_not_failed — PASSED
- tests/integration/test_preparation.py::test_form_validation_failure_sends_nothing — PASSED
- tests/integration/test_preparation.py::test_required_fields_cannot_be_skipped — PASSED
- tests/integration/test_preparation.py::test_invalid_option_is_rejected — PASSED
- tests/integration/test_preparation.py::test_changing_a_value_after_approval_requires_new_approval — PASSED
- tests/integration/test_preparation.py::test_human_only_pages_become_manual_handoffs[captcha-CAPTCHA] — PASSED
- tests/integration/test_preparation.py::test_human_only_pages_become_manual_handoffs[login-signing in] — PASSED
- tests/integration/test_preparation.py::test_human_only_pages_become_manual_handoffs[offsite-leave] — PASSED
- tests/integration/test_preparation.py::test_manual_application_is_recorded_after_approval — PASSED
- tests/integration/test_preparation.py::test_private_addresses_blocked_by_default — PASSED
- tests/integration/test_preparation.py::test_preparation_requires_verified_documents — PASSED
- tests/integration/test_workflow.py::test_user_approves_and_rejects_jobs_through_the_state_machine — PASSED
- tests/integration/test_workflow.py::test_invalid_transition_is_refused_and_changes_nothing — PASSED
- tests/integration/test_workflow.py::test_user_cannot_make_orchestrator_moves — PASSED
- tests/integration/test_workflow.py::test_guard_blocks_documents_ready_without_verified_documents — PASSED
- tests/integration/test_workflow.py::test_idempotent_replay_applies_once — PASSED
- tests/integration/test_workflow.py::test_reused_key_with_different_body_is_rejected — PASSED
- tests/integration/test_workflow.py::test_state_changes_require_an_idempotency_key — PASSED
- tests/integration/test_workflow.py::test_stale_version_is_refused — PASSED
- tests/integration/test_workflow.py::test_submit_is_blocked_without_approval — PASSED
- tests/integration/test_workflow.py::test_approval_requires_resolving_manual_fields_first — PASSED
- tests/integration/test_workflow.py::test_editing_a_form_value_invalidates_the_approval — PASSED
- tests/integration/test_workflow.py::test_changed_document_makes_approval_stale — PASSED
- tests/integration/test_workflow.py::test_failed_operation_leaves_records_consistent — PASSED
- tests/integration/test_workflow.py::test_concurrent_transitions_apply_exactly_once — PASSED
- tests/integration/test_workflow.py::test_only_one_active_application_per_job — PASSED
- tests/integration/test_workflow.py::test_interrupt_returns_to_previous_state — PASSED
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1-HTTP://WWW.Example.com/jobs/1/] — PASSED
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1-https://example.com/jobs/1?utm_source=x&utm_medium=y] — PASSED
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1-https://example.com/jobs/1#apply] — PASSED
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1?b=2&a=1-https://example.com/jobs/1?a=1&b=2&gclid=abc] — PASSED
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1-https://example.com:443//jobs//1] — PASSED
- tests/unit/test_dedup.py::test_url_variants_normalize_to_the_same_value[https://example.com/jobs/1-https://example.com/jobs/1?trk=public_jobs&refId=123] — PASSED
- tests/unit/test_dedup.py::test_meaningful_query_parameters_are_kept — PASSED
- tests/unit/test_dedup.py::test_different_ports_and_paths_stay_distinct — PASSED
- tests/unit/test_dedup.py::test_fingerprint_ignores_legal_suffix_and_gender_tag — PASSED
- tests/unit/test_dedup.py::test_fingerprint_differs_by_city — PASSED
- tests/unit/test_field_classifier.py::test_classification[Vorname-text-first_name-normal] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Nachname *-text-last_name-normal] — PASSED
- tests/unit/test_field_classifier.py::test_classification[E-Mail-Adresse-email-email-normal] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Lebenslauf hochladen-file-cv-normal] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Anschreiben-file-cover_letter-normal] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Gehaltsvorstellung (brutto/Jahr)-text-salary-sensitive] — PASSED
- tests/unit/test_field_classifier.py::test_classification[K\xfcndigungsfrist-text-notice_period-sensitive] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Fr\xfchester Eintrittstermin-date-notice_period-sensitive] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Besitzen Sie eine Arbeitserlaubnis f\xfcr Deutschland?-select-work_authorization-legal] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Do you need a visa sponsorship?-radio-sponsorship-legal] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Schwerbehinderung-select-disability-sensitive] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Geburtsdatum-date-diversity-sensitive] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Staatsangeh\xf6rigkeit-text-diversity-sensitive] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Ich habe die Datenschutzerkl\xe4rung gelesen und stimme zu-checkbox-consent-legal] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Please confirm you have the right to work in the EU-checkbox-work_authorization-legal] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Are you willing to relocate?-select-unknown-normal] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Deutschkenntnisse-select-german_level-normal] — PASSED
- tests/unit/test_field_classifier.py::test_classification[Wie sind Sie auf uns aufmerksam geworden?-select-referral-normal] — PASSED
- tests/unit/test_field_classifier.py::test_cv_label_on_a_text_box_is_not_a_file — PASSED
- tests/unit/test_field_classifier.py::test_protected_fields_get_a_hint_but_no_value — PASSED
- tests/unit/test_field_classifier.py::test_names_and_language_mapping — PASSED
- tests/unit/test_field_classifier.py::test_no_matching_option_is_left_to_you — PASSED
- tests/unit/test_field_classifier.py::test_files_only_when_document_is_verified — PASSED
- tests/unit/test_scoring.py::test_weights_sum_to_100 — PASSED
- tests/unit/test_scoring.py::test_breakdown_sums_to_score_and_respects_caps — PASSED
- tests/unit/test_scoring.py::test_unverified_profile_scores_zero_on_skills — PASSED
- tests/unit/test_scoring.py::test_every_matched_skill_has_evidence_linked_to_a_fact — PASSED
- tests/unit/test_scoring.py::test_student_job_without_verified_enrolment_is_never_auto_recommended — PASSED
- tests/unit/test_scoring.py::test_verified_low_german_fails_mandatory_german — PASSED
- tests/unit/test_scoring.py::test_unverified_german_is_uncertain_not_rejected — PASSED
- tests/unit/test_scoring.py::test_high_score_with_work_authorization_doubt_is_review_not_apply — PASSED
- tests/unit/test_scoring.py::test_skill_extraction_prefers_specific_spring_term — PASSED
- tests/unit/test_scoring.py::test_german_level_is_taken_from_the_listing — PASSED
- tests/unit/test_scoring.py::test_verified_b2_meets_b2_but_not_c1 — PASSED
- tests/unit/test_scoring.py::test_senior_roles_are_low_priority_even_with_skill_match — PASSED
- tests/unit/test_states.py::test_every_main_path_step_is_allowed — PASSED
- tests/unit/test_states.py::test_no_state_can_skip_to_submitted — PASSED
- tests/unit/test_states.py::test_only_orchestrator_marks_submitted_and_only_with_guard — PASSED
- tests/unit/test_states.py::test_user_approves_jobs_for_preparation_not_the_orchestrator — PASSED
- tests/unit/test_states.py::test_terminal_states_have_no_exits — PASSED
- tests/unit/test_states.py::test_every_active_state_can_be_withdrawn_by_user — PASSED
- tests/unit/test_states.py::test_interrupts_are_reachable_from_active_non_interrupt_states — PASSED
- tests/unit/test_states.py::test_classified_cannot_jump_to_documents_ready — PASSED
- tests/unit/test_verifier.py::test_supported_claim_passes — PASSED
- tests/unit/test_verifier.py::test_skill_not_in_cited_facts_is_flagged — PASSED
- tests/unit/test_verifier.py::test_rounded_up_duration_is_flagged — PASSED
- tests/unit/test_verifier.py::test_unknown_fact_ids_are_flagged — PASSED
- tests/unit/test_verifier.py::test_language_claim_needs_language_fact — PASSED
- tests/unit/test_verifier.py::test_availability_needs_eligibility_fact — PASSED
- tests/unit/test_verifier.py::test_promotion_needs_promotion_fact — PASSED
- tests/unit/test_verifier.py::test_seniority_words_need_support — PASSED
- tests/unit/test_verifier.py::test_learning_skill_cannot_be_sold_as_experience — PASSED
- tests/unit/test_verifier.py::test_uncited_experience_statement_is_flagged — PASSED
- tests/unit/test_verifier.py::test_job_title_and_company_may_be_named — PASSED
- tests/unit/test_verifier.py::test_common_words_are_not_mistaken_for_skills — PASSED
- tests/unit/test_verifier.py::test_month_arithmetic — PASSED
- tests/unit/test_verifier.py::test_native_code_is_not_a_language_claim — PASSED
- tests/unit/test_verifier.py::test_country_names_are_not_language_claims — PASSED
- tests/e2e/test_ui_walkthrough.py::test_walkthrough — PASSED (live stack + mock portal)
