from __future__ import annotations

from alpha.institutional_gate_truth.models import RejectionClassification
from alpha.institutional_gate_truth.rejection_outcomes import RejectionOutcomeEngine
from tests.institutional_gate_truth.conftest import bars, candidate


def test_target_before_stop_is_false_rejection() -> None:
    item = candidate()
    assessment = RejectionOutcomeEngine().evaluate(
        candidates=(item,),
        future_bars=bars(
            item.candidate_id,
            (
                ("2024-01-02", "100", "105", "95", "102"),
                ("2024-01-03", "102", "121", "101", "120"),
            ),
        ),
    )[0]
    assert assessment.classification is RejectionClassification.FALSE_REJECTION
    assert assessment.planned_outcome.target_reached is True
    assert assessment.planned_outcome.stop_before_target is False
    assert assessment.planned_outcome.realized_r is not None
    assert assessment.horizon_20d.horizon_sessions == 20
    assert assessment.horizon_60d.horizon_sessions == 60
    assert assessment.horizon_120d.horizon_sessions == 120


def test_same_bar_stop_and_target_resolves_stop_first() -> None:
    item = candidate(holding=1)
    assessment = RejectionOutcomeEngine().evaluate(
        candidates=(item,),
        future_bars=bars(
            item.candidate_id,
            (("2024-01-02", "100", "121", "89", "110"),),
        ),
    )[0]
    assert assessment.classification is RejectionClassification.CORRECT_REJECTION
    assert assessment.planned_outcome.stop_before_target is True
    assert assessment.planned_outcome.ambiguity_count == 1
    assert assessment.planned_outcome.exit_price == item.prospective_stop


def test_not_triggered_is_marginal_when_window_is_complete() -> None:
    item = candidate(holding=2)
    assessment = RejectionOutcomeEngine().evaluate(
        candidates=(item,),
        future_bars=bars(
            item.candidate_id,
            (
                ("2024-01-02", "95", "99", "94", "98"),
                ("2024-01-03", "98", "99", "96", "97"),
            ),
        ),
    )[0]
    assert assessment.classification is RejectionClassification.MARGINAL
    assert assessment.planned_outcome.exit_reason == "NOT_TRIGGERED"


def test_incomplete_outcome_remains_data_uncertain() -> None:
    item = candidate(holding=2)
    assessment = RejectionOutcomeEngine().evaluate(
        candidates=(item,),
        future_bars=bars(
            item.candidate_id,
            (("2024-01-02", "95", "99", "94", "98"),),
        ),
    )[0]
    assert assessment.classification is RejectionClassification.DATA_UNCERTAIN
    assert assessment.planned_outcome.complete is False
