from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal

from alpha.historical_replay.models import (
    EvidenceCube,
    EvidenceCubeCell,
    FeatureImportanceReport,
    HistoricalEvidenceSnapshot,
    ReplayRunRecord,
    ReplaySummary,
    SimulationResult,
    WalkForwardResult,
    WeightSuggestion,
)


def render_replay_run(runs: tuple[ReplayRunRecord, ...]) -> tuple[str, ...]:
    if not runs:
        return (
            "Historical Replay Run",
            "Replay observations processed: 0",
            "No replay observations were available; no edge was computed.",
        )
    return (
        "Historical Replay Run",
        f"Replay observations processed: {len(runs)}",
        f"Symbols scanned: {sum(run.symbols_scanned for run in runs)}",
        f"Raw candidates stored: {sum(run.candidates_stored for run in runs)}",
        f"Emitted decisions stored: {sum(run.emitted_decisions for run in runs)}",
        "Approved recommendations stored: "
        f"{sum(run.approved_recommendations for run in runs)}",
        f"Data gaps: {sum(run.data_gaps for run in runs)}",
    )


def render_replay_summary(summary: ReplaySummary) -> tuple[str, ...]:
    return (
        "Historical Replay Summary",
        f"Replay Runs: {summary.total_runs}",
        "Date Range: "
        f"{_date(summary.first_replay_date)} to {_date(summary.last_replay_date)}",
        f"Symbols Scanned: {summary.symbols_scanned}",
        f"Raw Candidates Stored: {summary.candidates_stored}",
        f"Emitted Decisions Stored: {summary.emitted_decisions}",
        f"Approved Recommendations Stored: {summary.approved_recommendations}",
        f"Data Gaps: {summary.data_gaps}",
    )


def render_evidence_report(cube: EvidenceCube, *, top: int = 10) -> tuple[str, ...]:
    lines = [
        "Evidence Cube Report",
        f"Evidence Cells: {len(cube.cells)}",
        "",
        "Best Setup/Regime/Filter Evidence:",
    ]
    lines.extend(_cell_lines(cube.best_cells(limit=top)))
    lines.extend(("", "Weakest Setup/Regime/Filter Evidence:"))
    lines.extend(_cell_lines(cube.weakest_cells(limit=top)))
    if not cube.cells:
        lines.append("Evidence cube: Not yet computed; insufficient sample.")
    return tuple(lines)


def render_feature_importance(report: FeatureImportanceReport) -> tuple[str, ...]:
    lines = ["Feature Importance", f"Features Ranked: {len(report.features)}"]
    if not report.features:
        lines.append("Feature importance: Not yet computed; insufficient sample.")
        return tuple(lines)
    for feature in report.features[:10]:
        lines.append(
            "- "
            f"{feature.feature}: EV lift {_metric(feature.ev_lift)}, "
            f"presence EV {_metric(feature.presence_ev)}, "
            f"absence EV {_metric(feature.absence_ev)}, "
            f"sample {feature.sample_size}, confidence {feature.confidence.value}"
        )
    return tuple(lines)


def render_weight_suggestions(
    suggestions: tuple[WeightSuggestion, ...],
) -> tuple[str, ...]:
    lines = ["Feature Weight Suggestions"]
    if not suggestions:
        lines.append("- Not yet computed")
        return tuple(lines)
    for suggestion in suggestions[:10]:
        lines.append(
            "- "
            f"{suggestion.feature}: {suggestion.direction.value.lower()} "
            f"from {suggestion.current_weight} to {suggestion.suggested_weight}; "
            f"reason: {suggestion.reason} sample {suggestion.sample_size}"
        )
    return tuple(lines)


def render_simulation_result(result: SimulationResult) -> tuple[str, ...]:
    params = result.parameters
    return (
        "Strategy Simulation",
        f"Parameter Set: setup={params.setup}, regime={params.regime}, "
        f"holding_period={params.holding_period}, stop_atr={params.stop_atr}",
        f"Trades: {result.trades}",
        f"Win Rate: {_metric(result.win_rate)}",
        f"EV %: {_metric(result.expected_value_pct)}",
        f"EV ₹: {_metric(result.expected_value_amount)}",
        f"Profit Factor: {_metric(result.profit_factor)}",
        f"Max Drawdown: {_metric(result.max_drawdown)}",
        f"Average Holding Period: {_metric(result.average_holding_period)}",
        f"Best Regime: {result.best_regime}",
        f"Worst Regime: {result.worst_regime}",
        f"Stability Score: {_metric(result.stability_score)}",
    )


def render_walk_forward(result: WalkForwardResult) -> tuple[str, ...]:
    split = result.split
    return (
        "Walk-Forward Validation",
        "Training Period: "
        f"{split.train_start.isoformat()} to {split.train_end.isoformat()}",
        "Validation Period: "
        f"{split.validate_start.isoformat()} to {split.validate_end.isoformat()}",
        f"Observations: {result.observations}",
        f"In-Sample EV: {_metric(result.in_sample_ev)}",
        f"Out-of-Sample EV: {_metric(result.out_of_sample_ev)}",
        f"Degradation %: {_metric(result.degradation_pct)}",
        f"Win Rate: {_metric(result.win_rate)}",
        f"Profit Factor: {_metric(result.profit_factor)}",
        f"Drawdown: {_metric(result.drawdown)}",
        f"Sample Confidence: {result.sample_confidence.value}",
        f"Overfitting Warning: {result.overfitting_warning}",
        f"Validation Verdict: {_walk_forward_verdict(result)}",
    )


def render_historical_evidence_snapshot(
    snapshot: HistoricalEvidenceSnapshot,
) -> tuple[str, ...]:
    return (
        "Historical Evidence:",
        f"- Replay observations available: {snapshot.replay_observations_available}",
        f"- Matching historical samples: {snapshot.matching_historical_samples}",
        f"- Historical EV: {_computed_metric(snapshot.historical_ev, suffix='%')}",
        f"- Historical win rate: {_computed_metric(snapshot.historical_win_rate)}",
        "- Best historical holding period: "
        f"{snapshot.best_holding_period or 'Not yet computed'}",
        f"- Evidence strength: {snapshot.evidence_strength.value}",
        "- Feature contribution: "
        f"{_availability(snapshot.feature_contribution_available)}",
        "- Suggested weight changes: "
        f"{_availability(snapshot.suggested_weight_changes_available)}",
    )


def _cell_lines(cells: Iterable[EvidenceCubeCell]) -> list[str]:
    cell_tuple = tuple(cells)
    if not cell_tuple:
        return ["- unavailable"]
    return [
        "- "
        f"{cell.dimension}={cell.key}: sample {cell.sample_size}, "
        f"EV {_metric(cell.expected_value_pct)}, "
        f"win rate {_metric(cell.win_rate)}, "
        f"strength {cell.evidence_strength.value}"
        for cell in cell_tuple
    ]


def _metric(value: Decimal | None) -> str:
    return "unavailable" if value is None else str(value)


def _computed_metric(value: Decimal | None, *, suffix: str = "") -> str:
    if value is None:
        return "Not yet computed"
    return f"{value}{suffix}"


def _availability(value: bool) -> str:
    return "Available" if value else "Not yet computed"


def _date(value: date | None) -> str:
    return "unavailable" if value is None else value.isoformat()


def _walk_forward_verdict(result: WalkForwardResult) -> str:
    if result.observations <= 0:
        return "No validation sample yet; do not use this as evidence."
    if result.sample_confidence.value in {"INSUFFICIENT", "WEAK"}:
        return (
            "Evidence is early; require stronger live confirmation before "
            "increasing trade confidence."
        )
    if result.out_of_sample_ev is None:
        return "Out-of-sample expectancy is unavailable."
    if result.out_of_sample_ev <= Decimal("0"):
        return "Rejected until out-of-sample expectancy improves."
    if result.degradation_pct is not None and result.degradation_pct > Decimal("50"):
        return "Positive but unstable; reduce confidence for overfitting risk."
    return "Pass; out-of-sample evidence supports selective deployment."


__all__ = [
    "render_evidence_report",
    "render_feature_importance",
    "render_historical_evidence_snapshot",
    "render_replay_run",
    "render_replay_summary",
    "render_simulation_result",
    "render_walk_forward",
    "render_weight_suggestions",
]
