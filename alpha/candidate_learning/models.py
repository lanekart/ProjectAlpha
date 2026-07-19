from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from types import MappingProxyType
from typing import Any

_ZERO = Decimal("0")
_TWO = Decimal("0.01")
_FOUR = Decimal("0.0001")


class CandidateOutcomeLabel(StrEnum):
    WOULD_HAVE_WON = "WOULD_HAVE_WON"
    WOULD_HAVE_LOST = "WOULD_HAVE_LOST"
    NEUTRAL = "NEUTRAL"
    DATA_MISSING = "DATA_MISSING"


class CandidateDecisionClassification(StrEnum):
    FALSE_POSITIVE = "FALSE_POSITIVE"
    FALSE_NEGATIVE = "FALSE_NEGATIVE"
    CORRECT_APPROVAL = "CORRECT_APPROVAL"
    CORRECT_REJECT = "CORRECT_REJECT"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True, slots=True)
class CandidateDecisionRecord:
    candidate_id: str
    run_id: str
    evaluation_date: date
    symbol: str
    final_verdict: str
    capital_action: str
    approved_for_deployment: bool
    rejection_reasons: tuple[str, ...]
    setup_type: str | None
    market_regime: str | None
    long_trade_permission: bool
    strategy_score: Decimal
    confidence: str
    data_quality: str
    entry_zone_low: Decimal | None
    entry_zone_high: Decimal | None
    confirmation_entry: Decimal | None
    risk_stop: Decimal | None
    target_1: Decimal | None
    target_2: Decimal | None
    target_3: Decimal | None
    trailing_stop_plan: str | None
    expected_holding_period: str | None
    indicators_active: tuple[str, ...]
    indicator_scores: MappingProxyType[str, str] | dict[str, str]
    evidence_layers: tuple[str, ...]
    explanation: str
    created_at: datetime
    company_name: str | None = None
    sector: str | None = None
    recommendation_id: str | None = None
    market_state_snapshot_id: str | None = None
    market_state_as_of: datetime | None = None
    market_state_fallback_applied: bool | None = None
    market_state_completeness: str | None = None
    classifier_version: str | None = None
    decision_provenance_id: str | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        candidate_id = self.candidate_id.strip()
        run_id = self.run_id.strip()
        if not symbol:
            raise ValueError("candidate symbol cannot be empty")
        if not candidate_id:
            raise ValueError("candidate_id cannot be empty")
        if not run_id:
            raise ValueError("run_id cannot be empty")
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "final_verdict", self.final_verdict.strip().upper())
        object.__setattr__(self, "capital_action", self.capital_action.strip().upper())
        object.__setattr__(
            self,
            "rejection_reasons",
            tuple(
                reason.strip() for reason in self.rejection_reasons if reason.strip()
            ),
        )
        object.__setattr__(self, "setup_type", _optional_text(self.setup_type))
        object.__setattr__(self, "market_regime", _optional_text(self.market_regime))
        object.__setattr__(self, "strategy_score", _decimal(self.strategy_score))
        object.__setattr__(self, "confidence", self.confidence.strip().upper())
        object.__setattr__(self, "data_quality", self.data_quality.strip().upper())
        for field_name in (
            "entry_zone_low",
            "entry_zone_high",
            "confirmation_entry",
            "risk_stop",
            "target_1",
            "target_2",
            "target_3",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_decimal(getattr(self, field_name)),
            )
        object.__setattr__(
            self,
            "trailing_stop_plan",
            _optional_text(self.trailing_stop_plan),
        )
        object.__setattr__(
            self,
            "expected_holding_period",
            _optional_text(self.expected_holding_period),
        )
        object.__setattr__(
            self,
            "indicators_active",
            tuple(
                dict.fromkeys(
                    indicator.strip().lower().replace("_", "-")
                    for indicator in self.indicators_active
                    if indicator.strip()
                )
            ),
        )
        object.__setattr__(
            self,
            "indicator_scores",
            MappingProxyType(
                {
                    str(key).strip(): str(value).strip()
                    for key, value in sorted(self.indicator_scores.items())
                    if str(key).strip()
                }
            ),
        )
        object.__setattr__(
            self,
            "evidence_layers",
            tuple(layer.strip() for layer in self.evidence_layers if layer.strip()),
        )
        explanation = self.explanation.strip()
        object.__setattr__(
            self,
            "explanation",
            explanation or "No explanation recorded.",
        )
        object.__setattr__(self, "created_at", _normalize_datetime(self.created_at))
        object.__setattr__(self, "company_name", _optional_text(self.company_name))
        object.__setattr__(self, "sector", _optional_text(self.sector))
        object.__setattr__(
            self,
            "recommendation_id",
            _optional_text(self.recommendation_id),
        )
        object.__setattr__(
            self,
            "market_state_snapshot_id",
            _optional_text(self.market_state_snapshot_id),
        )
        object.__setattr__(
            self,
            "market_state_as_of",
            (
                None
                if self.market_state_as_of is None
                else _normalize_datetime(self.market_state_as_of)
            ),
        )
        object.__setattr__(
            self,
            "market_state_completeness",
            _optional_text(self.market_state_completeness),
        )
        object.__setattr__(
            self,
            "classifier_version",
            _optional_text(self.classifier_version),
        )
        object.__setattr__(
            self,
            "decision_provenance_id",
            _optional_text(self.decision_provenance_id),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "run_id": self.run_id,
            "evaluation_date": self.evaluation_date.isoformat(),
            "symbol": self.symbol,
            "company_name": self.company_name,
            "sector": self.sector,
            "final_verdict": self.final_verdict,
            "capital_action": self.capital_action,
            "approved_for_deployment": self.approved_for_deployment,
            "rejection_reasons": list(self.rejection_reasons),
            "setup_type": self.setup_type,
            "market_regime": self.market_regime,
            "long_trade_permission": self.long_trade_permission,
            "strategy_score": str(self.strategy_score),
            "confidence": self.confidence,
            "data_quality": self.data_quality,
            "entry_zone_low": _text(self.entry_zone_low),
            "entry_zone_high": _text(self.entry_zone_high),
            "confirmation_entry": _text(self.confirmation_entry),
            "risk_stop": _text(self.risk_stop),
            "target_1": _text(self.target_1),
            "target_2": _text(self.target_2),
            "target_3": _text(self.target_3),
            "trailing_stop_plan": self.trailing_stop_plan,
            "expected_holding_period": self.expected_holding_period,
            "indicators_active": list(self.indicators_active),
            "indicator_scores": dict(self.indicator_scores),
            "evidence_layers": list(self.evidence_layers),
            "explanation": self.explanation,
            "created_at": self.created_at.isoformat(),
            "recommendation_id": self.recommendation_id,
            "market_state_snapshot_id": self.market_state_snapshot_id,
            "market_state_as_of": (
                None
                if self.market_state_as_of is None
                else self.market_state_as_of.isoformat()
            ),
            "market_state_fallback_applied": self.market_state_fallback_applied,
            "market_state_completeness": self.market_state_completeness,
            "classifier_version": self.classifier_version,
            "decision_provenance_id": self.decision_provenance_id,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CandidateDecisionRecord:
        return cls(
            candidate_id=str(payload["candidate_id"]),
            run_id=str(payload["run_id"]),
            evaluation_date=date.fromisoformat(str(payload["evaluation_date"])),
            symbol=str(payload["symbol"]),
            company_name=_payload_optional_text(payload.get("company_name")),
            sector=_payload_optional_text(payload.get("sector")),
            final_verdict=str(payload["final_verdict"]),
            capital_action=str(payload["capital_action"]),
            approved_for_deployment=bool(payload["approved_for_deployment"]),
            rejection_reasons=tuple(
                str(reason) for reason in payload.get("rejection_reasons", ())
            ),
            setup_type=_payload_optional_text(payload.get("setup_type")),
            market_regime=_payload_optional_text(payload.get("market_regime")),
            long_trade_permission=bool(payload["long_trade_permission"]),
            strategy_score=Decimal(str(payload["strategy_score"])),
            confidence=str(payload["confidence"]),
            data_quality=str(payload["data_quality"]),
            entry_zone_low=_payload_decimal(payload.get("entry_zone_low")),
            entry_zone_high=_payload_decimal(payload.get("entry_zone_high")),
            confirmation_entry=_payload_decimal(payload.get("confirmation_entry")),
            risk_stop=_payload_decimal(payload.get("risk_stop")),
            target_1=_payload_decimal(payload.get("target_1")),
            target_2=_payload_decimal(payload.get("target_2")),
            target_3=_payload_decimal(payload.get("target_3")),
            trailing_stop_plan=_payload_optional_text(
                payload.get("trailing_stop_plan")
            ),
            expected_holding_period=_payload_optional_text(
                payload.get("expected_holding_period")
            ),
            indicators_active=tuple(
                str(indicator) for indicator in payload.get("indicators_active", ())
            ),
            indicator_scores={
                str(key): str(value)
                for key, value in payload.get("indicator_scores", {}).items()
            },
            evidence_layers=tuple(
                str(layer) for layer in payload.get("evidence_layers", ())
            ),
            explanation=str(payload["explanation"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
            recommendation_id=_payload_optional_text(payload.get("recommendation_id")),
            market_state_snapshot_id=_payload_optional_text(
                payload.get("market_state_snapshot_id")
            ),
            market_state_as_of=(
                None
                if payload.get("market_state_as_of") is None
                else datetime.fromisoformat(str(payload["market_state_as_of"]))
            ),
            market_state_fallback_applied=(
                None
                if payload.get("market_state_fallback_applied") is None
                else bool(payload["market_state_fallback_applied"])
            ),
            market_state_completeness=_payload_optional_text(
                payload.get("market_state_completeness")
            ),
            classifier_version=_payload_optional_text(
                payload.get("classifier_version")
            ),
            decision_provenance_id=_payload_optional_text(
                payload.get("decision_provenance_id")
            ),
        )


@dataclass(frozen=True, slots=True)
class CandidateForwardWindowOutcome:
    window: str
    forward_open: Decimal | None
    forward_high: Decimal | None
    forward_low: Decimal | None
    forward_close: Decimal | None
    forward_return_pct_from_close: Decimal | None
    forward_return_pct_from_entry: Decimal | None
    max_favourable_excursion_pct: Decimal | None
    max_adverse_excursion_pct: Decimal | None
    target_1_touched: bool
    risk_stop_touched: bool
    outcome_label: CandidateOutcomeLabel

    def as_dict(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "forward_open": _text(self.forward_open),
            "forward_high": _text(self.forward_high),
            "forward_low": _text(self.forward_low),
            "forward_close": _text(self.forward_close),
            "forward_return_pct_from_close": _text(self.forward_return_pct_from_close),
            "forward_return_pct_from_entry": _text(self.forward_return_pct_from_entry),
            "max_favourable_excursion_pct": _text(self.max_favourable_excursion_pct),
            "max_adverse_excursion_pct": _text(self.max_adverse_excursion_pct),
            "target_1_touched": self.target_1_touched,
            "risk_stop_touched": self.risk_stop_touched,
            "outcome_label": self.outcome_label.value,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CandidateForwardWindowOutcome:
        return cls(
            window=str(payload["window"]),
            forward_open=_payload_decimal(payload.get("forward_open")),
            forward_high=_payload_decimal(payload.get("forward_high")),
            forward_low=_payload_decimal(payload.get("forward_low")),
            forward_close=_payload_decimal(payload.get("forward_close")),
            forward_return_pct_from_close=_payload_decimal(
                payload.get("forward_return_pct_from_close")
            ),
            forward_return_pct_from_entry=_payload_decimal(
                payload.get("forward_return_pct_from_entry")
            ),
            max_favourable_excursion_pct=_payload_decimal(
                payload.get("max_favourable_excursion_pct")
            ),
            max_adverse_excursion_pct=_payload_decimal(
                payload.get("max_adverse_excursion_pct")
            ),
            target_1_touched=bool(payload.get("target_1_touched", False)),
            risk_stop_touched=bool(payload.get("risk_stop_touched", False)),
            outcome_label=CandidateOutcomeLabel(str(payload["outcome_label"])),
        )


@dataclass(frozen=True, slots=True)
class CandidateForwardOutcome:
    candidate_id: str
    symbol: str
    evaluated_at: datetime
    windows: tuple[CandidateForwardWindowOutcome, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "symbol": self.symbol,
            "evaluated_at": self.evaluated_at.isoformat(),
            "windows": [window.as_dict() for window in self.windows],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> CandidateForwardOutcome:
        return cls(
            candidate_id=str(payload["candidate_id"]),
            symbol=str(payload["symbol"]),
            evaluated_at=datetime.fromisoformat(str(payload["evaluated_at"])),
            windows=tuple(
                CandidateForwardWindowOutcome.from_dict(window)
                for window in payload.get("windows", ())
            ),
        )


@dataclass(frozen=True, slots=True)
class CandidateDecisionQualitySummary:
    false_positive_count: int
    false_negative_count: int
    correct_approval_count: int
    correct_reject_count: int
    approval_precision: Decimal | None
    rejection_accuracy: Decimal | None
    missed_opportunity_rate: Decimal | None
    avoid_success_rate: Decimal | None
    watchlist_conversion_quality: Decimal | None


@dataclass(frozen=True, slots=True)
class LearningSummary:
    period: str
    generated_at: datetime
    total_candidates_evaluated: int
    approved_count: int
    rejected_count: int
    watchlist_count: int
    avoid_count: int
    sell_count: int
    completed_forward_windows: int
    quality: CandidateDecisionQualitySummary
    best_indicator_combinations: tuple[tuple[str, Decimal], ...]
    worst_indicator_combinations: tuple[tuple[str, Decimal], ...]
    best_setup_regime_combinations: tuple[tuple[str, Decimal], ...]
    worst_setup_regime_combinations: tuple[tuple[str, Decimal], ...]
    data_gaps: int
    sufficient_sample: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "generated_at": self.generated_at.isoformat(),
            "total_candidates_evaluated": self.total_candidates_evaluated,
            "approved_count": self.approved_count,
            "rejected_count": self.rejected_count,
            "watchlist_count": self.watchlist_count,
            "avoid_count": self.avoid_count,
            "sell_count": self.sell_count,
            "completed_forward_windows": self.completed_forward_windows,
            "quality": {
                "false_positive_count": self.quality.false_positive_count,
                "false_negative_count": self.quality.false_negative_count,
                "correct_approval_count": self.quality.correct_approval_count,
                "correct_reject_count": self.quality.correct_reject_count,
                "approval_precision": _text(self.quality.approval_precision),
                "rejection_accuracy": _text(self.quality.rejection_accuracy),
                "missed_opportunity_rate": _text(self.quality.missed_opportunity_rate),
                "avoid_success_rate": _text(self.quality.avoid_success_rate),
                "watchlist_conversion_quality": _text(
                    self.quality.watchlist_conversion_quality
                ),
            },
            "best_indicator_combinations": [
                [name, str(value)] for name, value in self.best_indicator_combinations
            ],
            "worst_indicator_combinations": [
                [name, str(value)] for name, value in self.worst_indicator_combinations
            ],
            "best_setup_regime_combinations": [
                [name, str(value)]
                for name, value in self.best_setup_regime_combinations
            ],
            "worst_setup_regime_combinations": [
                [name, str(value)]
                for name, value in self.worst_setup_regime_combinations
            ],
            "data_gaps": self.data_gaps,
            "sufficient_sample": self.sufficient_sample,
        }


def _decimal(value: Decimal) -> Decimal:
    return Decimal(str(value)).quantize(_TWO, rounding=ROUND_HALF_UP)


def _optional_decimal(value: Decimal | None) -> Decimal | None:
    return None if value is None else _decimal(value)


def _payload_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _payload_optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _optional_text(str(value))


def _normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def rate(numerator: int, denominator: int) -> Decimal | None:
    if denominator <= 0:
        return None
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        _FOUR,
        rounding=ROUND_HALF_UP,
    )


__all__ = [
    "CandidateDecisionClassification",
    "CandidateDecisionQualitySummary",
    "CandidateDecisionRecord",
    "CandidateForwardOutcome",
    "CandidateForwardWindowOutcome",
    "CandidateOutcomeLabel",
    "LearningSummary",
    "rate",
]
