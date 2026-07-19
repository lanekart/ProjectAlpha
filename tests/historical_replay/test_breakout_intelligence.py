from __future__ import annotations

import json
from datetime import date, timedelta

from typer.testing import CliRunner

from alpha.cli import app
from alpha.historical_replay import DirectionalObservation
from alpha.historical_replay.breakout_intelligence import (
    BreakoutClass,
    BreakoutEvidenceGroup,
    BreakoutPolicyName,
    BreakoutReasonCode,
    RetrospectiveBreakoutOutcome,
    build_breakout_intelligence_report,
    export_breakout_intelligence_csv,
    export_breakout_intelligence_json,
    group_breakout_report,
    render_breakout_intelligence_report,
)


def _observation(
    symbol: str,
    day: date,
    *,
    score: float = 0.74,
    timing: str = "CONFIRMATION",
    forward_return: float = 0.06,
    price: float = 103.0,
    resistance: float | None = 100.0,
    support: float = 80.0,
    volume: float | None = 0.70,
    relative_strength: float | None = 0.70,
    stop: float = 0.04,
    setup: str = "MOMENTUM_BREAKOUT",
    regime: str = "BULL",
    gap: float | None = None,
    completed: bool = True,
    upside_day: int | None = 2,
    downside_day: int | None = None,
) -> DirectionalObservation:
    feature_values = {
        "breakout": score,
        "breakout_confirmation": score,
        "liquidity": volume if volume is not None else 0.0,
        "price": price,
        "price_volume": score,
        "setup": score,
        "setup_quality": score,
        "stop_distance": stop,
        "support": support,
        "target": price * 1.08,
        "trade_plan": score,
    }
    if resistance is not None:
        feature_values["resistance"] = resistance
    if volume is not None:
        feature_values["volume"] = volume
    if relative_strength is not None:
        feature_values["relative_strength"] = relative_strength
    if gap is not None:
        feature_values["gap"] = gap
    return DirectionalObservation(
        symbol=symbol,
        observed_at=day,
        horizon_days=20,
        forward_return=forward_return,
        max_favorable_excursion=max(forward_return, 0.01) + 0.04,
        max_adverse_excursion=-stop,
        recommendation_score=score,
        price_component=score,
        setup_quality=score,
        entry_timing=timing,
        regime=regime,
        setup_type=setup,
        trade_plan_quality=score,
        stop_distance_pct=stop,
        expected_value=forward_return,
        confidence=score,
        completed=completed,
        upside_barrier_day=upside_day,
        downside_barrier_day=downside_day,
        sector="TEST_SECTOR",
        source="breakout-unit-test",
        feature_values=tuple(sorted(feature_values.items())),
    )


def _class_map(rows: tuple[DirectionalObservation, ...]) -> dict[str, BreakoutClass]:
    report = build_breakout_intelligence_report(rows)
    return {
        row.instrument: row.classification.ex_ante_class for row in report.observations
    }


def test_breakout_classification_covers_ex_ante_states() -> None:
    start = date(2024, 1, 1)
    rows = (
        _observation("NO", start, price=90.0),
        _observation("FORM", start + timedelta(days=1), price=98.0),
        _observation(
            "PRE",
            start + timedelta(days=2),
            score=0.42,
            timing="FORMING",
            price=100.5,
        ),
        _observation("HEALTHY", start + timedelta(days=3), price=103.0),
        _observation("WEAK", start + timedelta(days=4), price=103.0, volume=0.25),
        _observation(
            "UNCONF",
            start + timedelta(days=5),
            price=103.0,
            volume=None,
            relative_strength=None,
        ),
        _observation("GAP", start + timedelta(days=6), price=108.0, gap=0.07),
        _observation(
            "RETEST",
            start + timedelta(days=7),
            price=101.0,
            support=99.0,
            volume=0.45,
        ),
        _observation("LATE", start + timedelta(days=8), price=110.0),
        _observation("EXHAUSTED", start + timedelta(days=9), price=115.0, stop=0.12),
        _observation("FAILED", start + timedelta(days=10), price=99.0, support=101.0),
        _observation("MISSING", start + timedelta(days=11), resistance=None),
    )

    classes = _class_map(rows)

    assert classes == {
        "NO": BreakoutClass.NO_BREAKOUT,
        "FORM": BreakoutClass.BREAKOUT_FORMING,
        "PRE": BreakoutClass.PREMATURE_BREAKOUT,
        "HEALTHY": BreakoutClass.HEALTHY_BREAKOUT,
        "WEAK": BreakoutClass.WEAK_BREAKOUT,
        "UNCONF": BreakoutClass.UNCONFIRMED_BREAKOUT,
        "GAP": BreakoutClass.GAP_BREAKOUT,
        "RETEST": BreakoutClass.RETEST_BREAKOUT,
        "LATE": BreakoutClass.LATE_BREAKOUT,
        "EXHAUSTED": BreakoutClass.EXHAUSTED_BREAKOUT,
        "FAILED": BreakoutClass.FAILED_BREAKOUT,
        "MISSING": BreakoutClass.INSUFFICIENT_EVIDENCE,
    }


def test_ex_ante_classification_is_separate_from_retrospective_outcome() -> None:
    row = _observation(
        "FAIL_AFTER_HEALTHY",
        date(2024, 2, 1),
        price=103.0,
        forward_return=-0.05,
        upside_day=None,
        downside_day=3,
    )

    report = build_breakout_intelligence_report((row,))
    observation = report.observations[0]

    assert observation.classification.ex_ante_class is BreakoutClass.HEALTHY_BREAKOUT
    assert (
        observation.retrospective_outcome
        is RetrospectiveBreakoutOutcome.FAILED_WITHIN_3_SESSIONS
    )
    assert observation.classification.reason_code is (
        BreakoutReasonCode.RESISTANCE_CLEARED_WITH_CONFIRMATION
    )


def test_evidence_lineage_and_production_isolation_are_preserved() -> None:
    report = build_breakout_intelligence_report(
        (
            _observation(
                "LINEAGE",
                date(2024, 3, 1),
                price=103.0,
                volume=0.25,
                relative_strength=0.70,
            ),
        )
    )
    observation = report.observations[0]

    assert report.production_influence is False
    assert observation.production_influence is False
    assert observation.classification.production_influence is False
    assert observation.classification.contradicting_evidence
    assert observation.classification.point_in_time_boundary == date(2024, 3, 1)
    groups = {item.group for item in observation.classification.feature_lineage}
    assert BreakoutEvidenceGroup.PRICE_STRUCTURE_EVIDENCE in groups
    assert BreakoutEvidenceGroup.VOLUME_EVIDENCE in groups
    assert all(
        item.point_in_time_safe for item in observation.classification.feature_lineage
    )


def test_transitions_performance_overlap_and_policy_frontier() -> None:
    start = date(2024, 4, 1)
    rows = (
        _observation(
            "PATH",
            start,
            score=0.60,
            timing="FORMING",
            price=98.0,
            forward_return=0.05,
        ),
        _observation(
            "PATH",
            start + timedelta(days=1),
            score=0.78,
            timing="CONFIRMATION",
            price=103.0,
            forward_return=0.07,
        ),
        _observation(
            "WEAKRS",
            start + timedelta(days=2),
            price=103.0,
            volume=0.70,
            relative_strength=0.30,
            forward_return=-0.05,
            upside_day=None,
            downside_day=2,
        ),
    )

    report = build_breakout_intelligence_report(rows)

    assert any(
        transition.prior_class is BreakoutClass.BREAKOUT_FORMING
        and transition.new_class is BreakoutClass.HEALTHY_BREAKOUT
        for transition in report.transitions
    )
    assert report.transition_matrix
    assert report.class_performance
    assert report.independence_audit.overlap_table
    assert report.best_policy.policy in set(BreakoutPolicyName)
    assert report.breakout_layer_value.value
    assert report.policy_conclusion.value


def test_filtering_grouping_and_exports(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rows = (
        _observation("FILTERA", date(2024, 5, 1), price=103.0),
        _observation("FILTERB", date(2024, 5, 2), price=103.0, volume=0.25),
    )
    report = build_breakout_intelligence_report(
        rows,
        breakout_class="healthy-breakout",
        policy="healthy-only",
    )

    assert {row.classification.ex_ante_class for row in report.observations} == {
        BreakoutClass.HEALTHY_BREAKOUT
    }
    assert [item.policy for item in report.class_frontier] == [
        BreakoutPolicyName.HEALTHY_ONLY
    ]
    assert group_breakout_report(report, "breakout-class")
    lines = render_breakout_intelligence_report(report)
    assert "PRODUCTION_INFLUENCE=false" in lines

    json_path = tmp_path / "breakout.json"
    csv_path = tmp_path / "breakout.csv"
    export_breakout_intelligence_json(report, json_path)
    export_breakout_intelligence_csv(report, csv_path)

    payload = json.loads(json_path.read_text())
    assert payload["production_influence"] is False
    assert "ex_ante_breakout_class" in csv_path.read_text()


def test_breakout_cli_commands_render_text_and_grouping() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["replay", "breakout-intelligence"])
    assert result.exit_code == 0, result.output
    assert "Breakout Intelligence Engine" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output

    grouped = runner.invoke(
        app,
        [
            "replay",
            "breakout-classification-audit",
            "--group-by",
            "breakout-class",
        ],
    )
    assert grouped.exit_code == 0, grouped.output
    assert "Breakout Classification Audit Grouped By breakout-class" in grouped.output

    frontier = runner.invoke(app, ["replay", "breakout-class-frontier"])
    assert frontier.exit_code == 0, frontier.output
    assert "Breakout Class Policy Frontier" in frontier.output
