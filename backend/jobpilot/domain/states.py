"""The application state machine: the single source of truth for allowed moves.

Each rule names who may make the move and which guard must pass. Guards live in
`transitions.py` so they can query the database.
"""

from dataclasses import dataclass
from enum import StrEnum


class State(StrEnum):
    DISCOVERED = "discovered"
    CLASSIFIED = "classified"
    APPROVED_FOR_PREPARATION = "approved_for_preparation"
    DOCUMENTS_READY = "documents_ready"
    FORM_PREPARED = "form_prepared"
    AWAITING_USER_REVIEW = "awaiting_user_review"
    SUBMITTED = "submitted"
    FOLLOW_UP = "follow_up"
    CLOSED = "closed"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    NEEDS_MANUAL_INPUT = "needs_manual_input"


class Actor(StrEnum):
    USER = "user"
    ORCHESTRATOR = "orchestrator"
    # "I applied on the employer's site myself": only the dedicated /my/jobs/{id}/applied action uses it,
    # so the generic transition endpoint can never jump to submitted.
    USER_RECORD = "user_record"


TERMINAL = {State.CLOSED, State.REJECTED, State.WITHDRAWN, State.EXPIRED}
INACTIVE = TERMINAL  # matches the partial unique index on applications
ACTIVE = set(State) - INACTIVE
# Interrupt states return to the state they interrupted.
INTERRUPTS = {State.NEEDS_MANUAL_INPUT, State.FAILED}


@dataclass(frozen=True)
class Rule:
    to: State
    actors: frozenset[Actor]
    guard: str | None = None  # name of a guard function in transitions.GUARDS


U = frozenset({Actor.USER})
O = frozenset({Actor.ORCHESTRATOR})
UO = frozenset({Actor.USER, Actor.ORCHESTRATOR})
R = frozenset({Actor.USER_RECORD})
APPLIED_YOURSELF = Rule(State.SUBMITTED, R, "no_open_submission")

_MAIN: dict[State, list[Rule]] = {
    State.DISCOVERED: [Rule(State.CLASSIFIED, O, "has_evaluation")],
    State.CLASSIFIED: [
        Rule(State.APPROVED_FOR_PREPARATION, U, "job_available"),
        Rule(State.REJECTED, UO),
        APPLIED_YOURSELF,
    ],
    State.APPROVED_FOR_PREPARATION: [Rule(State.DOCUMENTS_READY, O, "documents_verified"), APPLIED_YOURSELF],
    State.DOCUMENTS_READY: [
        Rule(State.FORM_PREPARED, O, "form_fields_resolved"),
        Rule(State.AWAITING_USER_REVIEW, O, "manual_apply_source"),
        APPLIED_YOURSELF,
    ],
    State.FORM_PREPARED: [Rule(State.AWAITING_USER_REVIEW, O), APPLIED_YOURSELF],
    State.AWAITING_USER_REVIEW: [
        Rule(State.SUBMITTED, O, "submission_succeeded"),
        APPLIED_YOURSELF,
        Rule(State.APPROVED_FOR_PREPARATION, U),  # sent back for document changes
    ],
    State.SUBMITTED: [Rule(State.FOLLOW_UP, UO, "follow_up_set"), Rule(State.CLOSED, U, "outcome_set")],
    State.FOLLOW_UP: [Rule(State.CLOSED, U, "outcome_set")],
}


def rules_from(state: State) -> list[Rule]:
    rules = list(_MAIN.get(state, []))
    if state in ACTIVE and state not in INTERRUPTS:
        rules += [
            Rule(State.NEEDS_MANUAL_INPUT, O),
            Rule(State.FAILED, O),
            Rule(State.EXPIRED, O),
        ]
    if state not in TERMINAL:
        rules.append(Rule(State.WITHDRAWN, U))
    # Interrupt states: the return move is resolved dynamically ("previous state").
    return rules


def find_rule(from_state: State, to_state: State, actor: Actor | None = None) -> Rule | None:
    """The rule for this move; when several exist, the one this actor may use."""
    matches = [r for r in rules_from(from_state) if r.to == to_state]
    if actor is not None:
        for r in matches:
            if actor in r.actors:
                return r
    return matches[0] if matches else None
