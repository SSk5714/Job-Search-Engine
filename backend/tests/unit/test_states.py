from jobpilot.domain.states import ACTIVE, INTERRUPTS, TERMINAL, Actor, State, find_rule, rules_from

MAIN_PATH = [
    State.DISCOVERED, State.CLASSIFIED, State.APPROVED_FOR_PREPARATION, State.DOCUMENTS_READY,
    State.FORM_PREPARED, State.AWAITING_USER_REVIEW, State.SUBMITTED, State.FOLLOW_UP, State.CLOSED,
]


def test_every_main_path_step_is_allowed():
    for a, b in zip(MAIN_PATH, MAIN_PATH[1:]):
        assert find_rule(a, b) is not None, f"{a} -> {b}"


def test_no_state_can_skip_to_submitted():
    for s in State:
        if s != State.AWAITING_USER_REVIEW:
            assert find_rule(s, State.SUBMITTED) is None, s


def test_only_orchestrator_marks_submitted_and_only_with_guard():
    rule = find_rule(State.AWAITING_USER_REVIEW, State.SUBMITTED)
    assert rule.actors == frozenset({Actor.ORCHESTRATOR})
    assert rule.guard == "submission_succeeded"


def test_user_approves_jobs_for_preparation_not_the_orchestrator():
    rule = find_rule(State.CLASSIFIED, State.APPROVED_FOR_PREPARATION)
    assert rule.actors == frozenset({Actor.USER})


def test_terminal_states_have_no_exits():
    for s in TERMINAL:
        assert rules_from(s) == [], s


def test_every_active_state_can_be_withdrawn_by_user():
    for s in ACTIVE:
        rule = find_rule(s, State.WITHDRAWN)
        assert rule is not None and Actor.USER in rule.actors, s


def test_interrupts_are_reachable_from_active_non_interrupt_states():
    for s in ACTIVE - INTERRUPTS:
        assert find_rule(s, State.NEEDS_MANUAL_INPUT) is not None
        assert find_rule(s, State.FAILED) is not None


def test_classified_cannot_jump_to_documents_ready():
    assert find_rule(State.CLASSIFIED, State.DOCUMENTS_READY) is None
