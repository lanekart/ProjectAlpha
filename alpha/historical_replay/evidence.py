from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal

from alpha.candidate_learning import LearningLedgerRepository
from alpha.candidate_learning.models import CandidateOutcomeLabel
from alpha.candidate_learning.raw_universe import (
    RawCandidateForwardOutcome,
    RawCandidateRecord,
    RawForwardWindowOutcome,
)
from alpha.historical_replay.models import (
    EvidenceCube,
    EvidenceCubeCell,
    EvidenceStrength,
    FeatureImportance,
    FeatureImportanceReport,
    HistoricalEvidenceSnapshot,
    SimulationParameters,
    SimulationResult,
    WeightSuggestion,
    WeightSuggestionDirection,
    quantize,
    ratio,
    strength,
)

_ZERO = Decimal("0")
_DEFAULT_WEIGHTS = {
    "relative-strength": Decimal("0.15"),
    "volume": Decimal("0.15"),
    "breakout": Decimal("0.12"),
    "pullback": Decimal("0.10"),
    "risk": Decimal("0.08"),
}


class EvidenceCubeBuilder:
    def __init__(self, *, repository: LearningLedgerRepository) -> None:
        self.repository = repository

    def build(self, *, minimum_sample_size: int = 30) -> EvidenceCube:
        records = self.repository.load_raw_records()
        outcomes = {
            outcome.raw_candidate_id: outcome
            for outcome in self.repository.load_raw_outcomes()
        }
        cells: list[EvidenceCubeCell] = []
        for dimension, groups in _groups(records).items():
            for key, group_records in groups.items():
                cells.append(
                    _cell(
                        dimension=dimension,
                        key=key,
                        records=tuple(group_records),
                        outcomes=outcomes,
                        minimum_sample_size=minimum_sample_size,
                    )
                )
        return EvidenceCube(generated_at=datetime.now(tz=UTC), cells=tuple(cells))


class FeatureImportanceEngine:
    def __init__(self, *, repository: LearningLedgerRepository) -> None:
        self.repository = repository

    def rank(
        self,
        *,
        minimum_sample_size: int = 30,
    ) -> FeatureImportanceReport:
        records = self.repository.load_raw_records()
        outcomes = {
            outcome.raw_candidate_id: outcome
            for outcome in self.repository.load_raw_outcomes()
        }
        features = sorted(
            {indicator for record in records for indicator in record.indicators_active}
        )
        ranked = tuple(
            sorted(
                (
                    _feature(
                        feature=feature,
                        records=records,
                        outcomes=outcomes,
                        minimum_sample_size=minimum_sample_size,
                    )
                    for feature in features
                ),
                key=lambda item: (
                    item.ev_lift or Decimal("-999"),
                    Decimal(item.sample_size),
                    _regime_stability(item.regime_specific_ev_lift),
                ),
                reverse=True,
            )
        )
        return FeatureImportanceReport(
            generated_at=datetime.now(tz=UTC),
            features=ranked,
        )


class BayesianWeightUpdater:
    def suggestions(
        self,
        *,
        report: FeatureImportanceReport,
        minimum_sample_size: int = 30,
    ) -> tuple[WeightSuggestion, ...]:
        suggestions: list[WeightSuggestion] = []
        for feature in report.features:
            current = _DEFAULT_WEIGHTS.get(feature.feature, Decimal("0.05"))
            if feature.sample_size < minimum_sample_size or feature.ev_lift is None:
                suggestions.append(
                    WeightSuggestion(
                        feature=feature.feature,
                        current_weight=current,
                        suggested_weight=current,
                        direction=WeightSuggestionDirection.INSUFFICIENT_SAMPLE,
                        confidence=EvidenceStrength.INSUFFICIENT_SAMPLE,
                        sample_size=feature.sample_size,
                        reason="Insufficient completed replay samples.",
                    )
                )
                continue
            if feature.ev_lift > Decimal("1.00"):
                direction = WeightSuggestionDirection.INCREASE
                suggested = min(Decimal("0.30"), current + Decimal("0.04"))
                reason = f"Positive EV lift of {feature.ev_lift}%."
            elif feature.ev_lift < Decimal("-1.00"):
                direction = WeightSuggestionDirection.REDUCE
                suggested = max(Decimal("0.01"), current - Decimal("0.04"))
                reason = f"Negative EV lift of {feature.ev_lift}%."
            else:
                direction = WeightSuggestionDirection.HOLD
                suggested = current
                reason = "EV lift is not strong enough to change weight."
            suggestions.append(
                WeightSuggestion(
                    feature=feature.feature,
                    current_weight=current,
                    suggested_weight=suggested,
                    direction=direction,
                    confidence=feature.confidence,
                    sample_size=feature.sample_size,
                    reason=reason,
                )
            )
        return tuple(suggestions)


class SimulationLab:
    def __init__(self, *, repository: LearningLedgerRepository) -> None:
        self.repository = repository

    def run_strategy(self, *, parameters: SimulationParameters) -> SimulationResult:
        records = tuple(
            record
            for record in self.repository.load_raw_records()
            if parameters.from_date <= record.evaluation_date <= parameters.to_date
            and _matches_setup(record, parameters.setup)
            and _matches_text(record.market_regime, parameters.regime)
            and _passes_thresholds(record, parameters)
        )
        outcomes = {
            outcome.raw_candidate_id: outcome
            for outcome in self.repository.load_raw_outcomes()
        }
        returns = _returns_for_records(
            records=records,
            outcomes=outcomes,
            holding_period=parameters.holding_period,
        )
        by_regime = _returns_by_regime(
            records=records,
            outcomes=outcomes,
            holding_period=parameters.holding_period,
        )
        return SimulationResult(
            parameters=parameters,
            trades=len(returns),
            win_rate=ratio(sum(1 for value in returns if value > 0), len(returns)),
            expected_value_pct=_average(returns),
            expected_value_amount=None,
            profit_factor=_profit_factor(returns),
            max_drawdown=min(returns) if returns else None,
            average_holding_period=_holding_period_value(parameters.holding_period),
            best_regime=_best_key(by_regime),
            worst_regime=_worst_key(by_regime),
            stability_score=_stability(by_regime),
        )


class HistoricalEvidenceService:
    def __init__(self, *, repository: LearningLedgerRepository) -> None:
        self.repository = repository

    @classmethod
    def from_path(cls) -> HistoricalEvidenceService:
        return cls(repository=LearningLedgerRepository())

    def snapshot(
        self,
        *,
        setup_type: str | None = None,
        market_regime: str | None = None,
        minimum_sample_size: int = 30,
    ) -> HistoricalEvidenceSnapshot:
        records = tuple(
            record
            for record in self.repository.load_raw_records()
            if _matches_snapshot(
                record=record,
                setup_type=setup_type,
                market_regime=market_regime,
            )
        )
        outcomes = {
            outcome.raw_candidate_id: outcome
            for outcome in self.repository.load_raw_outcomes()
        }
        returns = _returns_for_records(
            records=records,
            outcomes=outcomes,
            holding_period="20d",
        )
        feature_report = FeatureImportanceEngine(repository=self.repository).rank(
            minimum_sample_size=minimum_sample_size
        )
        suggestions = BayesianWeightUpdater().suggestions(
            report=feature_report,
            minimum_sample_size=minimum_sample_size,
        )
        return HistoricalEvidenceSnapshot(
            replay_observations_available=len(self.repository.load_raw_records()),
            matching_historical_samples=len(returns),
            historical_ev=_average(returns),
            historical_win_rate=ratio(
                sum(1 for value in returns if value > 0),
                len(returns),
            ),
            best_holding_period=_best_holding_period(
                records=records,
                outcomes=outcomes,
            ),
            evidence_strength=strength(
                len(returns),
                minimum_sample_size=minimum_sample_size,
            ),
            feature_contribution_available=bool(feature_report.features),
            suggested_weight_changes_available=any(
                suggestion.direction
                is not WeightSuggestionDirection.INSUFFICIENT_SAMPLE
                for suggestion in suggestions
            ),
        )


def _groups(
    records: tuple[RawCandidateRecord, ...],
) -> dict[str, dict[str, list[RawCandidateRecord]]]:
    groups: dict[str, dict[str, list[RawCandidateRecord]]] = {
        "market_regime": defaultdict(list),
        "sector": defaultdict(list),
        "setup_type": defaultdict(list),
        "indicator_combination": defaultdict(list),
        "final_verdict": defaultdict(list),
        "exclusion_stage": defaultdict(list),
        "rejection_reason": defaultdict(list),
        "holding_period": defaultdict(list),
        "volatility_bucket": defaultdict(list),
        "liquidity_bucket": defaultdict(list),
        "confidence_bucket": defaultdict(list),
        "data_quality_bucket": defaultdict(list),
    }
    for record in records:
        groups["market_regime"][record.market_regime or "UNKNOWN"].append(record)
        groups["sector"][record.sector or "UNKNOWN"].append(record)
        setup = record.indicators_active[0] if record.indicators_active else "UNKNOWN"
        groups["setup_type"][setup].append(record)
        groups["indicator_combination"][
            "+".join(record.indicators_active) or "NONE"
        ].append(record)
        groups["final_verdict"][record.emitted_verdict or "NOT_EMITTED"].append(record)
        groups["exclusion_stage"][record.excluded_stage.value].append(record)
        groups["rejection_reason"][_first_reason(record.exclusion_reasons)].append(
            record
        )
        groups["holding_period"]["20d"].append(record)
        groups["volatility_bucket"][_bucket(record.volatility_score)].append(record)
        groups["liquidity_bucket"][_bucket(record.liquidity_score)].append(record)
        groups["confidence_bucket"][_bucket(record.final_strategy_score)].append(record)
        groups["data_quality_bucket"][_bucket(record.data_quality_score)].append(record)
    return groups


def _cell(
    *,
    dimension: str,
    key: str,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
    minimum_sample_size: int,
) -> EvidenceCubeCell:
    returns = _returns_for_records(
        records=records,
        outcomes=outcomes,
        holding_period="20d",
    )
    wins = tuple(value for value in returns if value > 0)
    losses = tuple(value for value in returns if value < 0)
    non_emitted = tuple(record for record in records if not record.was_emitted_decision)
    false_negatives = _label_count(
        records=non_emitted,
        outcomes=outcomes,
        label=CandidateOutcomeLabel.WOULD_HAVE_WON,
    )
    return EvidenceCubeCell(
        key=key,
        dimension=dimension,
        sample_size=len(returns),
        win_rate=ratio(len(wins), len(returns)),
        average_gain_pct=_average(wins),
        average_loss_pct=_average(losses),
        expected_value_pct=_average(returns),
        expected_value_amount=None,
        profit_factor=_profit_factor(returns),
        max_drawdown=min(returns) if returns else None,
        average_holding_period=Decimal("20") if returns else None,
        false_positive_rate=None,
        false_negative_rate=ratio(false_negatives, len(non_emitted)),
        missed_opportunity_rate=ratio(false_negatives, len(non_emitted)),
        evidence_strength=strength(
            len(returns),
            minimum_sample_size=minimum_sample_size,
        ),
    )


def _feature(
    *,
    feature: str,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
    minimum_sample_size: int,
) -> FeatureImportance:
    present = tuple(record for record in records if feature in record.indicators_active)
    absent = tuple(
        record for record in records if feature not in record.indicators_active
    )
    present_returns = _returns_for_records(
        records=present,
        outcomes=outcomes,
        holding_period="20d",
    )
    absent_returns = _returns_for_records(
        records=absent,
        outcomes=outcomes,
        holding_period="20d",
    )
    present_ev = _average(present_returns)
    absent_ev = _average(absent_returns)
    lift = (
        None
        if present_ev is None or absent_ev is None
        else quantize(present_ev - absent_ev)
    )
    return FeatureImportance(
        feature=feature,
        sample_size=len(present_returns),
        presence_win_rate=ratio(
            sum(1 for value in present_returns if value > 0),
            len(present_returns),
        ),
        absence_win_rate=ratio(
            sum(1 for value in absent_returns if value > 0),
            len(absent_returns),
        ),
        presence_ev=present_ev,
        absence_ev=absent_ev,
        ev_lift=lift,
        false_positive_contribution=None,
        false_negative_contribution=None,
        regime_specific_ev_lift=_regime_lift(
            feature=feature,
            records=records,
            outcomes=outcomes,
        ),
        confidence=strength(
            len(present_returns),
            minimum_sample_size=minimum_sample_size,
        ),
    )


def _returns_for_records(
    *,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
    holding_period: str,
) -> tuple[Decimal, ...]:
    values: list[Decimal] = []
    for record in records:
        outcome = outcomes.get(record.raw_candidate_id)
        if outcome is None:
            continue
        window = _window(outcome=outcome, holding_period=holding_period)
        if window is not None and window.forward_return_pct_from_close is not None:
            values.append(window.forward_return_pct_from_close)
    return tuple(values)


def _returns_by_regime(
    *,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
    holding_period: str,
) -> dict[str, Decimal]:
    grouped: dict[str, list[Decimal]] = defaultdict(list)
    for record in records:
        returns = _returns_for_records(
            records=(record,),
            outcomes=outcomes,
            holding_period=holding_period,
        )
        if returns:
            grouped[record.market_regime or "UNKNOWN"].append(returns[0])
    return {
        key: value
        for key, values in grouped.items()
        if (value := _average(tuple(values))) is not None
    }


def _regime_lift(
    *,
    feature: str,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
) -> tuple[tuple[str, Decimal], ...]:
    regimes = sorted({record.market_regime or "UNKNOWN" for record in records})
    lifts: list[tuple[str, Decimal]] = []
    for regime in regimes:
        regime_records = tuple(
            record
            for record in records
            if (record.market_regime or "UNKNOWN") == regime
        )
        present = tuple(
            record for record in regime_records if feature in record.indicators_active
        )
        absent = tuple(
            record
            for record in regime_records
            if feature not in record.indicators_active
        )
        present_ev = _average(
            _returns_for_records(
                records=present,
                outcomes=outcomes,
                holding_period="20d",
            )
        )
        absent_ev = _average(
            _returns_for_records(
                records=absent,
                outcomes=outcomes,
                holding_period="20d",
            )
        )
        if present_ev is not None and absent_ev is not None:
            lifts.append((regime, quantize(present_ev - absent_ev)))
    return tuple(lifts)


def _window(
    *,
    outcome: RawCandidateForwardOutcome,
    holding_period: str,
) -> RawForwardWindowOutcome | None:
    if holding_period.upper() == "ALL":
        holding_period = "20d"
    return next(
        (window for window in outcome.windows if window.window == holding_period),
        None,
    )


def _label_count(
    *,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
    label: CandidateOutcomeLabel,
) -> int:
    return sum(
        1
        for record in records
        if (outcome := outcomes.get(record.raw_candidate_id)) is not None
        and (window := _window(outcome=outcome, holding_period="20d")) is not None
        and window.outcome_label is label
    )


def _matches_setup(record: RawCandidateRecord, setup: str) -> bool:
    normalized = setup.strip().lower()
    if normalized == "all":
        return True
    return normalized in record.indicators_active


def _matches_text(value: str | None, expected: str) -> bool:
    normalized = expected.strip().upper()
    return normalized == "ALL" or (value or "").upper() == normalized


def _matches_snapshot(
    *,
    record: RawCandidateRecord,
    setup_type: str | None,
    market_regime: str | None,
) -> bool:
    if setup_type is not None and setup_type not in record.indicators_active:
        return False
    return market_regime is None or record.market_regime == market_regime


def _passes_thresholds(
    record: RawCandidateRecord,
    parameters: SimulationParameters,
) -> bool:
    if (
        record.volume_score is not None
        and record.volume_score < parameters.min_volume_ratio
    ):
        return False
    if (
        record.relative_strength_score is not None
        and record.relative_strength_score < parameters.min_relative_strength
    ):
        return False
    if (
        parameters.require_volume_confirmation
        and "volume" not in record.indicators_active
    ):
        return False
    if parameters.require_sector_strength and record.sector in {None, "UNKNOWN"}:
        return False
    return True


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return quantize(sum(values, _ZERO) / Decimal(len(values)))


def _profit_factor(values: tuple[Decimal, ...]) -> Decimal | None:
    gains = sum((value for value in values if value > 0), _ZERO)
    losses = abs(sum((value for value in values if value < 0), _ZERO))
    if losses == _ZERO:
        return None if gains == _ZERO else quantize(gains)
    return quantize(gains / losses)


def _best_key(values: dict[str, Decimal]) -> str:
    if not values:
        return "unavailable"
    return sorted(values.items(), key=lambda item: item[1], reverse=True)[0][0]


def _worst_key(values: dict[str, Decimal]) -> str:
    if not values:
        return "unavailable"
    return sorted(values.items(), key=lambda item: item[1])[0][0]


def _stability(values: dict[str, Decimal]) -> Decimal | None:
    if not values:
        return None
    positives = sum(1 for value in values.values() if value > 0)
    return ratio(positives, len(values))


def _regime_stability(values: tuple[tuple[str, Decimal], ...]) -> Decimal:
    if not values:
        return _ZERO
    positives = sum(1 for _regime, value in values if value > 0)
    return ratio(positives, len(values)) or _ZERO


def _holding_period_value(value: str) -> Decimal | None:
    if value.upper() == "ALL":
        return None
    digits = "".join(character for character in value if character.isdigit())
    return Decimal(digits) if digits else None


def _bucket(value: Decimal | None) -> str:
    if value is None:
        return "UNKNOWN"
    if value < Decimal("0.33"):
        return "LOW"
    if value < Decimal("0.67"):
        return "MEDIUM"
    return "HIGH"


def _first_reason(reasons: tuple[str, ...]) -> str:
    return reasons[0] if reasons else "unavailable"


def _best_holding_period(
    *,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
) -> str | None:
    period_ev: dict[str, Decimal] = {}
    for period in ("1d", "3d", "5d", "10d", "20d", "60d"):
        returns = _returns_for_records(
            records=records,
            outcomes=outcomes,
            holding_period=period,
        )
        if (average := _average(returns)) is not None:
            period_ev[period] = average
    return _best_key(period_ev) if period_ev else None


__all__ = [
    "BayesianWeightUpdater",
    "EvidenceCubeBuilder",
    "FeatureImportanceEngine",
    "HistoricalEvidenceService",
    "SimulationLab",
]
