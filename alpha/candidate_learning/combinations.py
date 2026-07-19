from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
    rate,
)
from alpha.candidate_learning.raw_universe import (
    RawCandidateForwardOutcome,
    RawCandidateRecord,
    RawForwardWindowOutcome,
)

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")


@dataclass(frozen=True, slots=True)
class IndicatorCombinationEdge:
    combination: tuple[str, ...]
    market_regime: str
    sample_count: int
    completed_count: int
    win_count: int
    loss_count: int
    neutral_count: int
    target_1_hit_rate: Decimal | None
    stop_hit_rate: Decimal | None
    win_rate: Decimal | None
    average_return_pct: Decimal | None
    expectancy_pct: Decimal | None
    evidence_strength: str

    @property
    def label(self) -> str:
        return " + ".join(self.combination)


@dataclass(frozen=True, slots=True)
class IndicatorCombinationEdgeReport:
    total_records: int
    completed_windows: int
    minimum_sample_size: int
    strongest: tuple[IndicatorCombinationEdge, ...]
    weakest: tuple[IndicatorCombinationEdge, ...]
    by_regime: tuple[tuple[str, tuple[IndicatorCombinationEdge, ...]], ...]
    insufficient: tuple[IndicatorCombinationEdge, ...]


class IndicatorCombinationEdgeEngine:
    """
    Deterministically ranks indicator combinations using recorded forward outcomes.

    The engine intentionally does not infer performance from rule scores. Only
    completed forward windows with realized forward returns are used for edge
    statistics.
    """

    def __init__(
        self,
        *,
        minimum_sample_size: int = 30,
        max_combination_size: int = 4,
        min_combination_size: int = 2,
    ) -> None:
        if minimum_sample_size <= 0:
            raise ValueError("minimum_sample_size must be positive")
        if max_combination_size <= 0:
            raise ValueError("max_combination_size must be positive")
        if min_combination_size <= 0:
            raise ValueError("min_combination_size must be positive")
        if min_combination_size > max_combination_size:
            raise ValueError("min_combination_size cannot exceed max_combination_size")
        self.minimum_sample_size = minimum_sample_size
        self.max_combination_size = max_combination_size
        self.min_combination_size = min_combination_size

    def analyze(
        self,
        *,
        records: tuple[CandidateDecisionRecord, ...],
        outcomes: tuple[CandidateForwardOutcome, ...],
    ) -> IndicatorCombinationEdgeReport:
        outcome_by_id = {outcome.candidate_id: outcome for outcome in outcomes}
        grouped: dict[tuple[tuple[str, ...], str], list[_ObservedWindow]] = defaultdict(
            list
        )
        total_completed = 0

        for record in records:
            window = _primary_window(outcome_by_id.get(record.candidate_id))
            completed = (
                window is not None
                and window.outcome_label is not CandidateOutcomeLabel.DATA_MISSING
            )
            if completed:
                total_completed += 1
            regime = _regime(record)
            for combo in _indicator_combinations(
                record.indicators_active,
                min_size=self.min_combination_size,
                max_size=self.max_combination_size,
            ):
                grouped[(combo, regime)].append(_ObservedWindow(record, window))

        edges = tuple(
            _edge(
                combination=combination,
                market_regime=regime,
                observations=tuple(observations),
                minimum_sample_size=self.minimum_sample_size,
            )
            for (combination, regime), observations in grouped.items()
        )
        sufficient = tuple(
            edge for edge in edges if edge.completed_count >= self.minimum_sample_size
        )
        insufficient = tuple(
            sorted(
                (
                    edge
                    for edge in edges
                    if edge.completed_count < self.minimum_sample_size
                ),
                key=lambda edge: (
                    -edge.completed_count,
                    edge.market_regime,
                    edge.label,
                ),
            )
        )
        ranked = tuple(
            sorted(
                sufficient,
                key=lambda edge: (
                    edge.expectancy_pct or _ZERO,
                    edge.win_rate or _ZERO,
                    edge.completed_count,
                    edge.market_regime,
                    edge.label,
                ),
                reverse=True,
            )
        )
        by_regime = tuple(
            (regime, tuple(edge for edge in ranked if edge.market_regime == regime)[:5])
            for regime in sorted({edge.market_regime for edge in ranked})
        )

        return IndicatorCombinationEdgeReport(
            total_records=len(records),
            completed_windows=total_completed,
            minimum_sample_size=self.minimum_sample_size,
            strongest=ranked[:10],
            weakest=tuple(reversed(ranked[-10:])),
            by_regime=by_regime,
            insufficient=insufficient[:10],
        )


class RawIndicatorCombinationEdgeEngine:
    """
    Ranks indicator combinations from historical replay/raw universe outcomes.

    Raw candidate outcomes are the best source for 5-year pattern discovery
    because they include emitted recommendations and rejected candidates.
    """

    def __init__(
        self,
        *,
        minimum_sample_size: int = 30,
        max_combination_size: int = 4,
        min_combination_size: int = 2,
    ) -> None:
        if minimum_sample_size <= 0:
            raise ValueError("minimum_sample_size must be positive")
        if max_combination_size <= 0:
            raise ValueError("max_combination_size must be positive")
        if min_combination_size <= 0:
            raise ValueError("min_combination_size must be positive")
        if min_combination_size > max_combination_size:
            raise ValueError("min_combination_size cannot exceed max_combination_size")
        self.minimum_sample_size = minimum_sample_size
        self.max_combination_size = max_combination_size
        self.min_combination_size = min_combination_size

    def analyze(
        self,
        *,
        records: tuple[RawCandidateRecord, ...],
        outcomes: tuple[RawCandidateForwardOutcome, ...],
    ) -> IndicatorCombinationEdgeReport:
        outcome_by_id = {outcome.raw_candidate_id: outcome for outcome in outcomes}
        grouped: dict[tuple[tuple[str, ...], str], list[_RawObservedWindow]] = (
            defaultdict(list)
        )
        total_completed = 0

        for record in records:
            window = _raw_primary_window(outcome_by_id.get(record.raw_candidate_id))
            completed = (
                window is not None
                and window.outcome_label is not CandidateOutcomeLabel.DATA_MISSING
            )
            if completed:
                total_completed += 1
            regime = _raw_regime(record)
            for combo in _indicator_combinations(
                record.indicators_active,
                min_size=self.min_combination_size,
                max_size=self.max_combination_size,
            ):
                grouped[(combo, regime)].append(_RawObservedWindow(record, window))

        edges = tuple(
            _raw_edge(
                combination=combination,
                market_regime=regime,
                observations=tuple(observations),
                minimum_sample_size=self.minimum_sample_size,
            )
            for (combination, regime), observations in grouped.items()
        )
        sufficient = tuple(
            edge for edge in edges if edge.completed_count >= self.minimum_sample_size
        )
        insufficient = tuple(
            sorted(
                (
                    edge
                    for edge in edges
                    if edge.completed_count < self.minimum_sample_size
                ),
                key=lambda edge: (
                    -edge.completed_count,
                    edge.market_regime,
                    edge.label,
                ),
            )
        )
        ranked = tuple(
            sorted(
                sufficient,
                key=lambda edge: (
                    edge.expectancy_pct or _ZERO,
                    edge.win_rate or _ZERO,
                    edge.completed_count,
                    edge.market_regime,
                    edge.label,
                ),
                reverse=True,
            )
        )
        by_regime = tuple(
            (regime, tuple(edge for edge in ranked if edge.market_regime == regime)[:5])
            for regime in sorted({edge.market_regime for edge in ranked})
        )

        return IndicatorCombinationEdgeReport(
            total_records=len(records),
            completed_windows=total_completed,
            minimum_sample_size=self.minimum_sample_size,
            strongest=ranked[:10],
            weakest=tuple(reversed(ranked[-10:])),
            by_regime=by_regime,
            insufficient=insufficient[:10],
        )


@dataclass(frozen=True, slots=True)
class _ObservedWindow:
    record: CandidateDecisionRecord
    window: CandidateForwardWindowOutcome | None


@dataclass(frozen=True, slots=True)
class _RawObservedWindow:
    record: RawCandidateRecord
    window: RawForwardWindowOutcome | None


def render_indicator_combination_edge_report(
    report: IndicatorCombinationEdgeReport,
) -> tuple[str, ...]:
    lines = [
        "Indicator Combination Edge Report",
        f"Candidates Evaluated: {report.total_records}",
        f"Completed Forward Windows: {report.completed_windows}",
        f"Minimum Sample Size: {report.minimum_sample_size}",
        "",
        "Best Indicator Combinations:",
    ]
    lines.extend(_edge_lines(report.strongest))
    lines.extend(("", "Weakest Indicator Combinations:"))
    lines.extend(_edge_lines(report.weakest))
    lines.extend(("", "Best By Market Regime:"))
    if not report.by_regime:
        lines.append("- unavailable")
    for regime, edges in report.by_regime:
        lines.append(f"{regime}:")
        lines.extend(f"- {line}" for line in _edge_lines(edges))
    lines.extend(("", "Insufficient Evidence Watchlist:"))
    lines.extend(_edge_lines(report.insufficient, include_strength=True))
    if report.completed_windows < report.minimum_sample_size:
        lines.append(
            "Conclusion: insufficient completed outcomes; do not promote any "
            "combination to a decision rule yet."
        )
    return tuple(lines)


def _edge_lines(
    edges: tuple[IndicatorCombinationEdge, ...],
    *,
    include_strength: bool = False,
) -> list[str]:
    if not edges:
        return ["- unavailable"]
    lines: list[str] = []
    for edge in edges:
        strength = f", evidence {edge.evidence_strength}" if include_strength else ""
        lines.append(
            f"{edge.label} [{edge.market_regime}]: "
            f"samples {edge.completed_count}/{edge.sample_count}, "
            f"win rate {_percent(edge.win_rate)}, "
            f"expectancy {_pct(edge.expectancy_pct)}, "
            f"target1 {_percent(edge.target_1_hit_rate)}, "
            f"stop {_percent(edge.stop_hit_rate)}{strength}"
        )
    return lines


def _edge(
    *,
    combination: tuple[str, ...],
    market_regime: str,
    observations: tuple[_ObservedWindow, ...],
    minimum_sample_size: int,
) -> IndicatorCombinationEdge:
    completed = tuple(
        observation.window
        for observation in observations
        if observation.window is not None
        and observation.window.outcome_label is not CandidateOutcomeLabel.DATA_MISSING
    )
    wins = sum(
        1
        for window in completed
        if window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_WON
    )
    losses = sum(
        1
        for window in completed
        if window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_LOST
    )
    neutral = sum(
        1
        for window in completed
        if window.outcome_label is CandidateOutcomeLabel.NEUTRAL
    )
    returns = tuple(
        window.forward_return_pct_from_entry
        for window in completed
        if window.forward_return_pct_from_entry is not None
    )
    average_return = _average(returns)
    completed_count = len(completed)
    return IndicatorCombinationEdge(
        combination=combination,
        market_regime=market_regime,
        sample_count=len(observations),
        completed_count=completed_count,
        win_count=wins,
        loss_count=losses,
        neutral_count=neutral,
        target_1_hit_rate=rate(
            sum(1 for window in completed if window.target_1_touched),
            completed_count,
        ),
        stop_hit_rate=rate(
            sum(1 for window in completed if window.risk_stop_touched),
            completed_count,
        ),
        win_rate=rate(wins, wins + losses),
        average_return_pct=average_return,
        expectancy_pct=average_return,
        evidence_strength=_evidence_strength(completed_count, minimum_sample_size),
    )


def _raw_edge(
    *,
    combination: tuple[str, ...],
    market_regime: str,
    observations: tuple[_RawObservedWindow, ...],
    minimum_sample_size: int,
) -> IndicatorCombinationEdge:
    completed = tuple(
        observation.window
        for observation in observations
        if observation.window is not None
        and observation.window.outcome_label is not CandidateOutcomeLabel.DATA_MISSING
    )
    wins = sum(
        1
        for window in completed
        if window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_WON
    )
    losses = sum(
        1
        for window in completed
        if window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_LOST
    )
    neutral = sum(
        1
        for window in completed
        if window.outcome_label is CandidateOutcomeLabel.NEUTRAL
    )
    returns = tuple(
        window.forward_return_pct_from_close
        for window in completed
        if window.forward_return_pct_from_close is not None
    )
    average_return = _average(returns)
    completed_count = len(completed)
    return IndicatorCombinationEdge(
        combination=combination,
        market_regime=market_regime,
        sample_count=len(observations),
        completed_count=completed_count,
        win_count=wins,
        loss_count=losses,
        neutral_count=neutral,
        target_1_hit_rate=rate(
            sum(1 for window in completed if window.target_1_touched),
            completed_count,
        ),
        stop_hit_rate=rate(
            sum(1 for window in completed if window.risk_stop_touched),
            completed_count,
        ),
        win_rate=rate(wins, wins + losses),
        average_return_pct=average_return,
        expectancy_pct=average_return,
        evidence_strength=_evidence_strength(completed_count, minimum_sample_size),
    )


def _primary_window(
    outcome: CandidateForwardOutcome | None,
) -> CandidateForwardWindowOutcome | None:
    if outcome is None:
        return None
    preferred = ("20d", "10d", "5d", "3d", "1d", "60d")
    by_window = {window.window: window for window in outcome.windows}
    return next(
        (
            by_window[label]
            for label in preferred
            if label in by_window
            and by_window[label].outcome_label is not CandidateOutcomeLabel.DATA_MISSING
        ),
        outcome.windows[0] if outcome.windows else None,
    )


def _raw_primary_window(
    outcome: RawCandidateForwardOutcome | None,
) -> RawForwardWindowOutcome | None:
    if outcome is None:
        return None
    preferred = ("20d", "10d", "5d", "3d", "1d", "60d")
    by_window = {window.window: window for window in outcome.windows}
    return next(
        (
            by_window[label]
            for label in preferred
            if label in by_window
            and by_window[label].outcome_label is not CandidateOutcomeLabel.DATA_MISSING
        ),
        outcome.windows[0] if outcome.windows else None,
    )


def _indicator_combinations(
    indicators: tuple[str, ...],
    *,
    min_size: int,
    max_size: int,
) -> tuple[tuple[str, ...], ...]:
    clean = tuple(dict.fromkeys(indicator for indicator in indicators if indicator))
    if len(clean) < min_size:
        return ()
    upper = min(max_size, len(clean))
    return tuple(
        combo
        for size in range(min_size, upper + 1)
        for combo in combinations(clean, size)
    )


def _regime(record: CandidateDecisionRecord) -> str:
    return (record.market_regime or "UNKNOWN").strip().upper() or "UNKNOWN"


def _raw_regime(record: RawCandidateRecord) -> str:
    return (record.market_regime or "UNKNOWN").strip().upper() or "UNKNOWN"


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def _evidence_strength(completed_count: int, minimum_sample_size: int) -> str:
    if completed_count < minimum_sample_size:
        return "insufficient"
    if completed_count < minimum_sample_size * 2:
        return "weak"
    if completed_count < minimum_sample_size * 4:
        return "moderate"
    return "strong"


def _percent(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    return f"{(value * Decimal('100')).quantize(_TWO, rounding=ROUND_HALF_UP)}%"


def _pct(value: Decimal | None) -> str:
    if value is None:
        return "unavailable"
    sign = "+" if value > _ZERO else ""
    return f"{sign}{value}%"


__all__ = [
    "IndicatorCombinationEdge",
    "IndicatorCombinationEdgeEngine",
    "IndicatorCombinationEdgeReport",
    "RawIndicatorCombinationEdgeEngine",
    "render_indicator_combination_edge_report",
]
