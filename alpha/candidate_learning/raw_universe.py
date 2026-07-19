from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from hashlib import sha256
from types import MappingProxyType
from typing import Any

from alpha.candidate_learning.evaluator import WINDOWS
from alpha.candidate_learning.models import CandidateOutcomeLabel, rate
from alpha.recommendation_intelligence.models import OHLCVBar, RecommendationCandidate
from alpha.strategy_regime import setup_to_indicators

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_TWO = Decimal("0.01")
_ACTIVE_EVIDENCE_THRESHOLD = Decimal("0.60")


class ExclusionStage(StrEnum):
    UNIVERSE_SCAN = "UNIVERSE_SCAN"
    DATA_QUALITY_FILTER = "DATA_QUALITY_FILTER"
    LIQUIDITY_FILTER = "LIQUIDITY_FILTER"
    TECHNICAL_FILTER = "TECHNICAL_FILTER"
    SETUP_FILTER = "SETUP_FILTER"
    RISK_FILTER = "RISK_FILTER"
    REGIME_FILTER = "REGIME_FILTER"
    PORTFOLIO_FILTER = "PORTFOLIO_FILTER"
    FINAL_RECOMMENDATION = "FINAL_RECOMMENDATION"


@dataclass(frozen=True, slots=True)
class RawCandidateRecord:
    raw_candidate_id: str
    run_id: str
    evaluation_date: date
    symbol: str
    universe_source: str
    was_emitted_decision: bool
    emitted_verdict: str | None
    excluded_stage: ExclusionStage
    exclusion_reasons: tuple[str, ...]
    preliminary_score: Decimal
    data_quality_score: Decimal | None
    liquidity_score: Decimal | None
    trend_score: Decimal | None
    momentum_score: Decimal | None
    volume_score: Decimal | None
    volatility_score: Decimal | None
    relative_strength_score: Decimal | None
    setup_score: Decimal | None
    risk_score: Decimal | None
    regime_score: Decimal | None
    final_strategy_score: Decimal | None
    indicators_active: tuple[str, ...]
    indicator_scores: MappingProxyType[str, str]
    market_regime: str | None
    long_trade_permission: bool
    close_price: Decimal | None
    entry_candidate_price: Decimal | None
    risk_stop: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    created_at: datetime
    company_name: str | None = None
    sector: str | None = None
    raw_rank: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_candidate_id": self.raw_candidate_id,
            "run_id": self.run_id,
            "evaluation_date": self.evaluation_date.isoformat(),
            "symbol": self.symbol,
            "company_name": self.company_name,
            "sector": self.sector,
            "universe_source": self.universe_source,
            "was_emitted_decision": self.was_emitted_decision,
            "emitted_verdict": self.emitted_verdict,
            "excluded_stage": self.excluded_stage.value,
            "exclusion_reasons": list(self.exclusion_reasons),
            "raw_rank": self.raw_rank,
            "preliminary_score": str(self.preliminary_score),
            "data_quality_score": _text(self.data_quality_score),
            "liquidity_score": _text(self.liquidity_score),
            "trend_score": _text(self.trend_score),
            "momentum_score": _text(self.momentum_score),
            "volume_score": _text(self.volume_score),
            "volatility_score": _text(self.volatility_score),
            "relative_strength_score": _text(self.relative_strength_score),
            "setup_score": _text(self.setup_score),
            "risk_score": _text(self.risk_score),
            "regime_score": _text(self.regime_score),
            "final_strategy_score": _text(self.final_strategy_score),
            "indicators_active": list(self.indicators_active),
            "indicator_scores": dict(self.indicator_scores),
            "market_regime": self.market_regime,
            "long_trade_permission": self.long_trade_permission,
            "close_price": _text(self.close_price),
            "entry_candidate_price": _text(self.entry_candidate_price),
            "risk_stop": _text(self.risk_stop),
            "target_1": _text(self.target_1),
            "target_2": _text(self.target_2),
            "target_3": _text(self.target_3),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RawCandidateRecord:
        return cls(
            raw_candidate_id=str(payload["raw_candidate_id"]),
            run_id=str(payload["run_id"]),
            evaluation_date=date.fromisoformat(str(payload["evaluation_date"])),
            symbol=str(payload["symbol"]),
            company_name=_optional_text(payload.get("company_name")),
            sector=_optional_text(payload.get("sector")),
            universe_source=str(payload["universe_source"]),
            was_emitted_decision=bool(payload["was_emitted_decision"]),
            emitted_verdict=_optional_text(payload.get("emitted_verdict")),
            excluded_stage=ExclusionStage(str(payload["excluded_stage"])),
            exclusion_reasons=tuple(
                str(reason) for reason in payload.get("exclusion_reasons", ())
            ),
            raw_rank=payload.get("raw_rank"),
            preliminary_score=Decimal(str(payload["preliminary_score"])),
            data_quality_score=_decimal(payload.get("data_quality_score")),
            liquidity_score=_decimal(payload.get("liquidity_score")),
            trend_score=_decimal(payload.get("trend_score")),
            momentum_score=_decimal(payload.get("momentum_score")),
            volume_score=_decimal(payload.get("volume_score")),
            volatility_score=_decimal(payload.get("volatility_score")),
            relative_strength_score=_decimal(payload.get("relative_strength_score")),
            setup_score=_decimal(payload.get("setup_score")),
            risk_score=_decimal(payload.get("risk_score")),
            regime_score=_decimal(payload.get("regime_score")),
            final_strategy_score=_decimal(payload.get("final_strategy_score")),
            indicators_active=tuple(
                str(item) for item in payload.get("indicators_active", ())
            ),
            indicator_scores=MappingProxyType(
                {str(k): str(v) for k, v in payload.get("indicator_scores", {}).items()}
            ),
            market_regime=_optional_text(payload.get("market_regime")),
            long_trade_permission=bool(payload["long_trade_permission"]),
            close_price=_decimal(payload.get("close_price")),
            entry_candidate_price=_decimal(payload.get("entry_candidate_price")),
            risk_stop=_decimal(payload.get("risk_stop")),
            target_1=_decimal(payload.get("target_1")),
            target_2=_decimal(payload.get("target_2")),
            target_3=_decimal(payload.get("target_3")),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
        )


@dataclass(frozen=True, slots=True)
class RawForwardWindowOutcome:
    window: str
    forward_return_pct_from_close: Decimal | None
    max_favourable_excursion_pct: Decimal | None
    max_adverse_excursion_pct: Decimal | None
    target_1_touched: bool
    risk_stop_touched: bool
    outcome_label: CandidateOutcomeLabel

    def as_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "forward_return_pct_from_close": _text(self.forward_return_pct_from_close),
            "max_favourable_excursion_pct": _text(self.max_favourable_excursion_pct),
            "max_adverse_excursion_pct": _text(self.max_adverse_excursion_pct),
            "target_1_touched": self.target_1_touched,
            "risk_stop_touched": self.risk_stop_touched,
            "outcome_label": self.outcome_label.value,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RawForwardWindowOutcome:
        return cls(
            window=str(payload["window"]),
            forward_return_pct_from_close=_decimal(
                payload.get("forward_return_pct_from_close")
            ),
            max_favourable_excursion_pct=_decimal(
                payload.get("max_favourable_excursion_pct")
            ),
            max_adverse_excursion_pct=_decimal(
                payload.get("max_adverse_excursion_pct")
            ),
            target_1_touched=bool(payload.get("target_1_touched", False)),
            risk_stop_touched=bool(payload.get("risk_stop_touched", False)),
            outcome_label=CandidateOutcomeLabel(str(payload["outcome_label"])),
        )


@dataclass(frozen=True, slots=True)
class RawCandidateForwardOutcome:
    raw_candidate_id: str
    symbol: str
    evaluated_at: datetime
    windows: tuple[RawForwardWindowOutcome, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_candidate_id": self.raw_candidate_id,
            "symbol": self.symbol,
            "evaluated_at": self.evaluated_at.isoformat(),
            "windows": [window.as_dict() for window in self.windows],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> RawCandidateForwardOutcome:
        return cls(
            raw_candidate_id=str(payload["raw_candidate_id"]),
            symbol=str(payload["symbol"]),
            evaluated_at=datetime.fromisoformat(str(payload["evaluated_at"])),
            windows=tuple(
                RawForwardWindowOutcome.from_dict(window)
                for window in payload.get("windows", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class RawFilterQualitySummary:
    exclusion_stage: str
    exclusion_reason: str
    candidates_excluded: int
    average_forward_returns: tuple[tuple[str, Decimal | None], ...]
    false_negative_count: int
    false_negative_rate: Decimal | None
    correct_reject_count: int
    correct_reject_rate: Decimal | None
    missed_return_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class RawUniverseLearningSummary:
    total_raw_candidates: int
    emitted_decisions: int
    non_emitted_candidates: int
    false_negatives: int
    correct_rejects: int
    missed_opportunity_rate: Decimal | None
    average_return_emitted: Decimal | None
    average_return_non_emitted: Decimal | None
    filter_value_added: Decimal | None
    top_exclusion_stage: str
    data_gaps: int
    sufficient_sample: bool
    best_filters: tuple[tuple[str, Decimal], ...]
    weakest_filters: tuple[tuple[str, Decimal], ...]
    filter_quality: tuple[RawFilterQualitySummary, ...] = ()


def raw_record_from_candidate(
    *,
    candidate: RecommendationCandidate,
    run_id: str,
    created_at: datetime,
    emitted_verdict_by_symbol: dict[str, str],
    raw_rank: int | None = None,
) -> RawCandidateRecord:
    emitted_verdict = emitted_verdict_by_symbol.get(candidate.symbol)
    was_emitted = emitted_verdict is not None
    indicators = _candidate_indicators(candidate)
    return RawCandidateRecord(
        raw_candidate_id=_raw_id(run_id=run_id, symbol=candidate.symbol),
        run_id=run_id,
        evaluation_date=candidate.observed_on,
        symbol=candidate.symbol,
        company_name=candidate.metadata.get("company_name"),
        sector=candidate.metadata.get("sector"),
        universe_source=candidate.metadata.get("universe_source", "runtime"),
        was_emitted_decision=was_emitted,
        emitted_verdict=emitted_verdict,
        excluded_stage=ExclusionStage.FINAL_RECOMMENDATION
        if was_emitted
        else _excluded_stage(candidate),
        exclusion_reasons=()
        if was_emitted
        else (candidate.metadata.get("exclusion_reason", "Not emitted"),),
        raw_rank=raw_rank,
        preliminary_score=candidate.strategy_score,
        data_quality_score=_score_from_quality(candidate.metadata.get("data_quality")),
        liquidity_score=candidate.liquidity_score,
        trend_score=candidate.trend_structure_score,
        momentum_score=candidate.momentum_confirmation_score,
        volume_score=candidate.volume_confirmation_score,
        volatility_score=Decimal("1") - candidate.risk_score,
        relative_strength_score=candidate.relative_strength_score,
        setup_score=candidate.breakout_setup_score,
        risk_score=candidate.risk_score,
        regime_score=candidate.market_regime_score,
        final_strategy_score=candidate.strategy_score,
        indicators_active=indicators,
        indicator_scores=MappingProxyType(
            {
                "strategy": str(candidate.strategy_score),
                "liquidity": str(candidate.liquidity_score),
                "risk": str(candidate.risk_score),
                "trend": _score_text(candidate.trend_structure_score),
                "momentum": _score_text(candidate.momentum_confirmation_score),
                "volume": _score_text(candidate.volume_confirmation_score),
                "relative_strength": _score_text(candidate.relative_strength_score),
                "breakout": _score_text(candidate.breakout_setup_score),
                "retracement": str(candidate.retracement_score),
                "market_regime": _score_text(candidate.market_regime_score),
            }
        ),
        market_regime=candidate.market_regime,
        long_trade_permission=candidate.action.value == "BUY",
        close_price=candidate.current_price,
        entry_candidate_price=candidate.current_price,
        risk_stop=candidate.swing_low or candidate.support_level,
        target_1=candidate.recent_high or candidate.swing_high,
        target_2=None,
        target_3=None,
        created_at=created_at,
    )


def _candidate_indicators(candidate: RecommendationCandidate) -> tuple[str, ...]:
    indicators: list[str] = list(setup_to_indicators(candidate.setup_type or ""))
    score_labels: tuple[tuple[str, Decimal | None], ...] = (
        ("trend", candidate.trend_structure_score),
        ("momentum", candidate.momentum_confirmation_score),
        ("volume", candidate.volume_confirmation_score),
        ("relative-strength", candidate.relative_strength_score),
        ("breakout", candidate.breakout_setup_score),
        ("retracement", candidate.retracement_score),
        ("market-regime", candidate.market_regime_score),
        ("sector", candidate.sector_strength_score),
        ("liquidity", candidate.liquidity_score),
        ("risk", Decimal("1") - candidate.risk_score),
    )
    for label, score in score_labels:
        bucket = _score_bucket(score)
        if bucket is not None:
            indicators.append(f"{label}-{bucket}")

    if candidate.breakout_attempt:
        indicators.append("breakout-attempt")
    if candidate.higher_highs_higher_lows:
        indicators.append("higher-high-higher-low")
    if candidate.lower_highs_lower_lows:
        indicators.append("lower-high-lower-low")
    if candidate.breakdown_attempt:
        indicators.append("breakdown-attempt")
    if (
        candidate.volume_confirmation_score is not None
        and candidate.volume_confirmation_score < Decimal("0.40")
    ):
        indicators.append("weak-volume")
    if (
        candidate.distribution_score is not None
        and candidate.distribution_score >= _ACTIVE_EVIDENCE_THRESHOLD
    ):
        indicators.append("distribution-warning")
    if (
        candidate.selloff_volume_penalty is not None
        and candidate.selloff_volume_penalty >= _ACTIVE_EVIDENCE_THRESHOLD
    ):
        indicators.append("selloff-volume-warning")

    if not indicators:
        indicators.append("unlabeled-evidence")
    return tuple(dict.fromkeys(indicators))


def _score_bucket(score: Decimal | None) -> str | None:
    if score is None:
        return None
    if score >= Decimal("0.75"):
        return "strong"
    if score >= _ACTIVE_EVIDENCE_THRESHOLD:
        return "constructive"
    if score <= Decimal("0.25"):
        return "weak"
    if score <= Decimal("0.40"):
        return "poor"
    return None


def _score_text(score: Decimal | None) -> str:
    return "unavailable" if score is None else str(score)


class RawCandidateForwardOutcomeEvaluator:
    def evaluate(
        self,
        *,
        record: RawCandidateRecord,
        bars: tuple[OHLCVBar, ...],
    ) -> RawCandidateForwardOutcome:
        future = tuple(
            sorted(
                (bar for bar in bars if bar.observed_on > record.evaluation_date),
                key=lambda bar: bar.observed_on,
            )
        )
        return RawCandidateForwardOutcome(
            raw_candidate_id=record.raw_candidate_id,
            symbol=record.symbol,
            evaluated_at=datetime.now(tz=UTC),
            windows=tuple(
                _window(record=record, bars=future, label=label, size=size)
                for label, size in WINDOWS
            ),
        )


class RawUniverseLearningAggregator:
    def summarize(
        self,
        *,
        records: tuple[RawCandidateRecord, ...],
        outcomes: tuple[RawCandidateForwardOutcome, ...],
        minimum_sample_size: int = 30,
    ) -> RawUniverseLearningSummary:
        by_id = {outcome.raw_candidate_id: outcome for outcome in outcomes}
        primary = {
            record.raw_candidate_id: _primary_window(by_id.get(record.raw_candidate_id))
            for record in records
        }
        non_emitted = tuple(
            record for record in records if not record.was_emitted_decision
        )
        false_negative_count = sum(
            1
            for record in non_emitted
            if (window := primary.get(record.raw_candidate_id)) is not None
            and window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_WON
        )
        correct_reject_count = sum(
            1
            for record in non_emitted
            if (window := primary.get(record.raw_candidate_id)) is not None
            and window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_LOST
        )
        emitted_returns = _returns(
            (record for record in records if record.was_emitted_decision),
            primary,
        )
        non_emitted_returns = _returns(non_emitted, primary)
        filter_returns = _stage_returns(records=records, primary=primary)
        filter_quality = _filter_quality(records=records, outcomes=by_id)
        best_filters = tuple(
            sorted(filter_returns.items(), key=lambda item: item[1], reverse=True)[:5]
        )
        weakest_filters = tuple(
            sorted(filter_returns.items(), key=lambda item: item[1])[:5]
        )
        top_stage = Counter(
            record.excluded_stage.value for record in records
        ).most_common(1)
        return RawUniverseLearningSummary(
            total_raw_candidates=len(records),
            emitted_decisions=sum(
                1 for record in records if record.was_emitted_decision
            ),
            non_emitted_candidates=len(non_emitted),
            false_negatives=false_negative_count,
            correct_rejects=correct_reject_count,
            missed_opportunity_rate=rate(false_negative_count, len(non_emitted)),
            average_return_emitted=_average(emitted_returns),
            average_return_non_emitted=_average(non_emitted_returns),
            filter_value_added=_difference(
                _average(emitted_returns),
                _average(non_emitted_returns),
            ),
            top_exclusion_stage=top_stage[0][0] if top_stage else "unavailable",
            data_gaps=_data_gap_count(records=records, primary=primary),
            sufficient_sample=len(records) >= minimum_sample_size,
            best_filters=best_filters,
            weakest_filters=weakest_filters,
            filter_quality=filter_quality,
        )


def _window(
    *,
    record: RawCandidateRecord,
    bars: tuple[OHLCVBar, ...],
    label: str,
    size: int,
) -> RawForwardWindowOutcome:
    if len(bars) < size or record.close_price is None:
        return RawForwardWindowOutcome(
            window=label,
            forward_return_pct_from_close=None,
            max_favourable_excursion_pct=None,
            max_adverse_excursion_pct=None,
            target_1_touched=False,
            risk_stop_touched=False,
            outcome_label=CandidateOutcomeLabel.DATA_MISSING,
        )
    selected = bars[:size]
    close = selected[-1].close_price
    high = max(bar.high_price for bar in selected)
    low = min(bar.low_price for bar in selected)
    target_touched = record.target_1 is not None and high >= record.target_1
    stop_touched = record.risk_stop is not None and low <= record.risk_stop
    forward_return = _return(record.close_price, close)
    return RawForwardWindowOutcome(
        window=label,
        forward_return_pct_from_close=forward_return,
        max_favourable_excursion_pct=_return(record.close_price, high),
        max_adverse_excursion_pct=_return(record.close_price, low),
        target_1_touched=target_touched,
        risk_stop_touched=stop_touched,
        outcome_label=_label(target_touched, stop_touched, forward_return),
    )


def _label(
    target_touched: bool,
    stop_touched: bool,
    forward_return: Decimal,
) -> CandidateOutcomeLabel:
    if stop_touched:
        return CandidateOutcomeLabel.WOULD_HAVE_LOST
    if target_touched or forward_return >= Decimal("3"):
        return CandidateOutcomeLabel.WOULD_HAVE_WON
    if forward_return <= Decimal("-2"):
        return CandidateOutcomeLabel.WOULD_HAVE_LOST
    return CandidateOutcomeLabel.NEUTRAL


def _primary_window(
    outcome: RawCandidateForwardOutcome | None,
) -> RawForwardWindowOutcome | None:
    if outcome is None:
        return None
    by_window = {window.window: window for window in outcome.windows}
    return by_window.get("20d") or by_window.get("10d") or outcome.windows[0]


def _returns(
    records: Iterable[RawCandidateRecord],
    primary: dict[str, RawForwardWindowOutcome | None],
) -> tuple[Decimal, ...]:
    return tuple(
        window.forward_return_pct_from_close
        for record in records
        if (window := primary.get(record.raw_candidate_id)) is not None
        and window.forward_return_pct_from_close is not None
    )


def _stage_returns(
    *,
    records: tuple[RawCandidateRecord, ...],
    primary: dict[str, RawForwardWindowOutcome | None],
) -> dict[str, Decimal]:
    grouped: dict[str, list[Decimal]] = defaultdict(list)
    for record in records:
        window = primary.get(record.raw_candidate_id)
        if window is None or window.forward_return_pct_from_close is None:
            continue
        grouped[record.excluded_stage.value].append(
            window.forward_return_pct_from_close
        )
    return {
        stage: _average(tuple(values)) or _ZERO for stage, values in grouped.items()
    }


def _filter_quality(
    *,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
) -> tuple[RawFilterQualitySummary, ...]:
    grouped: dict[tuple[str, str], list[RawCandidateRecord]] = defaultdict(list)
    for record in records:
        if record.was_emitted_decision:
            continue
        grouped[
            (record.excluded_stage.value, _first_reason(record.exclusion_reasons))
        ].append(record)

    summaries: list[RawFilterQualitySummary] = []
    for (stage, reason), candidates in grouped.items():
        candidate_tuple = tuple(candidates)
        primary_windows = tuple(
            window
            for record in candidate_tuple
            if (window := _primary_window(outcomes.get(record.raw_candidate_id)))
            is not None
        )
        false_negative_count = sum(
            1
            for window in primary_windows
            if window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_WON
        )
        correct_reject_count = sum(
            1
            for window in primary_windows
            if window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_LOST
        )
        missed_returns = tuple(
            window.forward_return_pct_from_close
            for window in primary_windows
            if window.outcome_label is CandidateOutcomeLabel.WOULD_HAVE_WON
            and window.forward_return_pct_from_close is not None
        )
        summaries.append(
            RawFilterQualitySummary(
                exclusion_stage=stage,
                exclusion_reason=reason,
                candidates_excluded=len(candidate_tuple),
                average_forward_returns=_average_returns_by_window(
                    records=candidate_tuple,
                    outcomes=outcomes,
                ),
                false_negative_count=false_negative_count,
                false_negative_rate=rate(false_negative_count, len(candidate_tuple)),
                correct_reject_count=correct_reject_count,
                correct_reject_rate=rate(correct_reject_count, len(candidate_tuple)),
                missed_return_pct=_average(missed_returns),
            )
        )
    return tuple(
        sorted(
            summaries,
            key=lambda summary: (
                summary.exclusion_stage,
                summary.exclusion_reason,
            ),
        )
    )


def _average_returns_by_window(
    *,
    records: tuple[RawCandidateRecord, ...],
    outcomes: dict[str, RawCandidateForwardOutcome],
) -> tuple[tuple[str, Decimal | None], ...]:
    values: dict[str, list[Decimal]] = defaultdict(list)
    for record in records:
        outcome = outcomes.get(record.raw_candidate_id)
        if outcome is None:
            continue
        for window in outcome.windows:
            if window.forward_return_pct_from_close is not None:
                values[window.window].append(window.forward_return_pct_from_close)
    return tuple(
        (label, _average(tuple(values.get(label, ())))) for label, _size in WINDOWS
    )


def _first_reason(reasons: tuple[str, ...]) -> str:
    return reasons[0] if reasons else "unavailable"


def _data_gap_count(
    *,
    records: tuple[RawCandidateRecord, ...],
    primary: dict[str, RawForwardWindowOutcome | None],
) -> int:
    gaps = 0
    for record in records:
        window = primary.get(record.raw_candidate_id)
        if window is None or window.outcome_label is CandidateOutcomeLabel.DATA_MISSING:
            gaps += 1
    return gaps


def _excluded_stage(candidate: RecommendationCandidate) -> ExclusionStage:
    data_quality = candidate.metadata.get("data_quality", "").upper()
    if data_quality not in {"", "COMPLETE", "GOOD"}:
        return ExclusionStage.DATA_QUALITY_FILTER
    if candidate.liquidity_score < Decimal("0.35"):
        return ExclusionStage.LIQUIDITY_FILTER
    if candidate.risk_score < Decimal("0.35"):
        return ExclusionStage.RISK_FILTER
    if candidate.strategy_score < Decimal("0.50"):
        return ExclusionStage.SETUP_FILTER
    return ExclusionStage.FINAL_RECOMMENDATION


def _score_from_quality(value: str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal("1") if value.upper() in {"COMPLETE", "GOOD"} else Decimal("0.25")


def _raw_id(*, run_id: str, symbol: str) -> str:
    return sha256(f"{run_id}|raw|{symbol.upper()}".encode()).hexdigest()[:24]


def _return(start: Decimal, end: Decimal) -> Decimal:
    if start <= _ZERO:
        return _ZERO
    return ((end - start) / start * _HUNDRED).quantize(_TWO, rounding=ROUND_HALF_UP)


def _average(values: tuple[Decimal, ...]) -> Decimal | None:
    if not values:
        return None
    return (sum(values, _ZERO) / Decimal(len(values))).quantize(
        _TWO,
        rounding=ROUND_HALF_UP,
    )


def _difference(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return (left - right).quantize(_TWO, rounding=ROUND_HALF_UP)


def _decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


__all__ = [
    "ExclusionStage",
    "RawCandidateForwardOutcome",
    "RawCandidateForwardOutcomeEvaluator",
    "RawCandidateRecord",
    "RawForwardWindowOutcome",
    "RawUniverseLearningAggregator",
    "RawUniverseLearningSummary",
    "raw_record_from_candidate",
]
