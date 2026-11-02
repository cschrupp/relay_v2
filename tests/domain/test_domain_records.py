from decimal import Decimal

import pytest
from pydantic import BaseModel, ValidationError

from relay.domain import (
    STEER_DECISION,
    Accept,
    DriftCard,
    DriftFinding,
    LineEstimate,
    MakeRule,
    NetLines,
    Redirect,
    RunRecord,
)

CARD = DriftCard(
    base_sha="988b8b9",
    result_sha="1e0ade8",
    expected_lines=LineEstimate(source=300, tests=150),
    actual_lines=NetLines(source=382, tests=308),
    findings=(
        DriftFinding(kind="net_lines", message="source 382 vs 300 expected"),
        DriftFinding(
            kind="oversized_function",
            message="build_report is 92 lines",
            path="src/relay/drift/report.py",
            line=78,
        ),
    ),
)
RUN = RunRecord(
    model="anthropic/claude-sonnet-5-5",
    role="implementer",
    tier="cheap",
    input_tokens=12000,
    output_tokens=3400,
    cost_usd=Decimal("0.0871"),
    outcome="accepted",
)


@pytest.mark.parametrize("record", [CARD, RUN, *CARD.findings])
def test_records_round_trip_through_json(record: BaseModel) -> None:
    assert type(record).model_validate_json(record.model_dump_json()) == record


@pytest.mark.parametrize(
    "decision", [Accept(), Redirect(text="keep it in drift"), MakeRule(spec="no imports of loop")]
)
def test_steer_decisions_round_trip_by_kind(decision: Accept | Redirect | MakeRule) -> None:
    assert STEER_DECISION.validate_json(STEER_DECISION.dump_json(decision)) == decision


def test_steer_decision_kind_selects_the_type() -> None:
    decision = STEER_DECISION.validate_python({"kind": "redirect", "text": "smaller"})

    assert decision == Redirect(text="smaller")
    with pytest.raises(ValidationError):
        STEER_DECISION.validate_python({"kind": "redirect"})
    with pytest.raises(ValidationError):
        STEER_DECISION.validate_python({"kind": "shrug"})


def test_card_is_blocking_only_with_a_blocking_finding() -> None:
    edited = DriftFinding(kind="edited_test", message="tests/x.py edited", severity="blocking")

    assert not CARD.blocking
    assert CARD.model_copy(update={"findings": (*CARD.findings, edited)}).blocking


@pytest.mark.parametrize(
    "bad",
    [
        {"input_tokens": -1},
        {"cost_usd": Decimal("-0.01")},
        {"outcome": "maybe"},
        {"model": ""},
    ],
)
def test_run_record_validation(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RunRecord.model_validate({**RUN.model_dump(), **bad})


def test_finding_line_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        DriftFinding(kind="new_cycle", message="a <-> b", line=0)
