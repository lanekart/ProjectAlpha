from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from alpha.candidate_learning.models import CandidateDecisionRecord
from alpha.candidate_learning.raw_universe import RawCandidateRecord
from alpha.recommendation_intelligence.models import OHLCVBar

_ZERO = Decimal("0")
_TWO_PLACES = Decimal("0.01")
_FOUR_PLACES = Decimal("0.0001")


class EvidenceStrength(StrEnum):
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"


class WeightSuggestionDirection(StrEnum):
    INCREASE = "INCREASE"
    REDUCE = "REDUCE"
    HOLD = "HOLD"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"


@dataclass(frozen=True, slots=True)
class ReplayCandidateObservation:
    raw_candidate: RawCandidateRecord
    bars: tuple[OHLCVBar, ...]
    emitted_decision: CandidateDecisionRecord | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "bars",
            tuple(sorted(self.bars, key=lambda bar: bar.observed_on)),
        )
        if (
            self.emitted_decision is not None
            and self.emitted_decision.evaluation_date
            != self.raw_candidate.evaluation_date
        ):
            raise ValueError("emitted decision date must match raw candidate date")
        if (
            self.emitted_decision is not None
            and self.emitted_decision.symbol != self.raw_candidate.symbol
        ):
            raise ValueError("emitted decision symbol must match raw candidate symbol")


@dataclass(frozen=True, slots=True)
class ReplayRunRecord:
    replay_run_id: str
    replay_date: date
    symbols_scanned: int
    candidates_stored: int
    emitted_decisions: int
    approved_recommendations: int
    market_regime: str | None
    long_trade_permission: bool
    data_cutoff_date: date
    outcome_windows_available: tuple[str, ...]
    data_gaps: int
    runtime_seconds: Decimal
    created_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "replay_run_id": self.replay_run_id,
            "replay_date": self.replay_date.isoformat(),
            "symbols_scanned": self.symbols_scanned,
            "candidates_stored": self.candidates_stored,
            "emitted_decisions": self.emitted_decisions,
            "approved_recommendations": self.approved_recommendations,
            "market_regime": self.market_regime,
            "long_trade_permission": self.long_trade_permission,
            "data_cutoff_date": self.data_cutoff_date.isoformat(),
            "outcome_windows_available": list(self.outcome_windows_available),
            "data_gaps": self.data_gaps,
            "runtime_seconds": str(self.runtime_seconds),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> ReplayRunRecord:
        return cls(
            replay_run_id=str(payload["replay_run_id"]),
            replay_date=date.fromisoformat(str(payload["replay_date"])),
            symbols_scanned=int(payload["symbols_scanned"]),
            candidates_stored=int(payload["candidates_stored"]),
            emitted_decisions=int(payload["emitted_decisions"]),
            approved_recommendations=int(payload["approved_recommendations"]),
            market_regime=_optional_text(payload.get("market_regime")),
            long_trade_permission=bool(payload["long_trade_permission"]),
            data_cutoff_date=date.fromisoformat(str(payload["data_cutoff_date"])),
            outcome_windows_available=tuple(
                str(window) for window in payload.get("outcome_windows_available", ())
            ),
            data_gaps=int(payload["data_gaps"]),
            runtime_seconds=_decimal(payload["runtime_seconds"]),
            created_at=datetime.fromisoformat(str(payload["created_at"])),
        )


@dataclass(frozen=True, slots=True)
class ReplaySummary:
    total_runs: int
    symbols_scanned: int
    candidates_stored: int
    emitted_decisions: int
    approved_recommendations: int
    data_gaps: int
    first_replay_date: date | None
    last_replay_date: date | None


@dataclass(frozen=True, slots=True)
class EvidenceCubeCell:
    key: str
    dimension: str
    sample_size: int
    win_rate: Decimal | None
    average_gain_pct: Decimal | None
    average_loss_pct: Decimal | None
    expected_value_pct: Decimal | None
    expected_value_amount: Decimal | None
    profit_factor: Decimal | None
    max_drawdown: Decimal | None
    average_holding_period: Decimal | None
    false_positive_rate: Decimal | None
    false_negative_rate: Decimal | None
    missed_opportunity_rate: Decimal | None
    evidence_strength: EvidenceStrength


@dataclass(frozen=True, slots=True)
class EvidenceCube:
    generated_at: datetime
    cells: tuple[EvidenceCubeCell, ...]

    def best_cells(self, *, limit: int = 10) -> tuple[EvidenceCubeCell, ...]:
        return tuple(
            sorted(
                (cell for cell in self.cells if cell.expected_value_pct is not None),
                key=lambda cell: (
                    cell.expected_value_pct or _ZERO,
                    Decimal(cell.sample_size),
                ),
                reverse=True,
            )[:limit]
        )

    def weakest_cells(self, *, limit: int = 10) -> tuple[EvidenceCubeCell, ...]:
        return tuple(
            sorted(
                (cell for cell in self.cells if cell.expected_value_pct is not None),
                key=lambda cell: (
                    cell.expected_value_pct or _ZERO,
                    -Decimal(cell.sample_size),
                ),
            )[:limit]
        )


@dataclass(frozen=True, slots=True)
class FeatureImportance:
    feature: str
    sample_size: int
    presence_win_rate: Decimal | None
    absence_win_rate: Decimal | None
    presence_ev: Decimal | None
    absence_ev: Decimal | None
    ev_lift: Decimal | None
    false_positive_contribution: Decimal | None
    false_negative_contribution: Decimal | None
    regime_specific_ev_lift: tuple[tuple[str, Decimal], ...]
    confidence: EvidenceStrength


@dataclass(frozen=True, slots=True)
class FeatureImportanceReport:
    generated_at: datetime
    features: tuple[FeatureImportance, ...]


@dataclass(frozen=True, slots=True)
class WeightSuggestion:
    feature: str
    current_weight: Decimal
    suggested_weight: Decimal
    direction: WeightSuggestionDirection
    confidence: EvidenceStrength
    sample_size: int
    reason: str


@dataclass(frozen=True, slots=True)
class SimulationParameters:
    from_date: date
    to_date: date
    setup: str
    regime: str
    holding_period: str
    stop_atr: Decimal
    min_volume_ratio: Decimal
    min_relative_strength: Decimal
    require_sector_strength: bool
    require_volume_confirmation: bool
    top: int


@dataclass(frozen=True, slots=True)
class SimulationResult:
    parameters: SimulationParameters
    trades: int
    win_rate: Decimal | None
    expected_value_pct: Decimal | None
    expected_value_amount: Decimal | None
    profit_factor: Decimal | None
    max_drawdown: Decimal | None
    average_holding_period: Decimal | None
    best_regime: str
    worst_regime: str
    stability_score: Decimal | None


@dataclass(frozen=True, slots=True)
class WalkForwardSplit:
    train_start: date
    train_end: date
    validate_start: date
    validate_end: date


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    split: WalkForwardSplit
    observations: int
    in_sample_ev: Decimal | None
    out_of_sample_ev: Decimal | None
    degradation_pct: Decimal | None
    win_rate: Decimal | None
    profit_factor: Decimal | None
    drawdown: Decimal | None
    sample_confidence: EvidenceStrength
    overfitting_warning: str


@dataclass(frozen=True, slots=True)
class HistoricalEvidenceSnapshot:
    replay_observations_available: int
    matching_historical_samples: int
    historical_ev: Decimal | None
    historical_win_rate: Decimal | None
    best_holding_period: str | None
    evidence_strength: EvidenceStrength
    feature_contribution_available: bool
    suggested_weight_changes_available: bool


def quantize(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def ratio(numerator: int | Decimal, denominator: int | Decimal) -> Decimal | None:
    denominator_decimal = Decimal(str(denominator))
    if denominator_decimal <= _ZERO:
        return None
    return (Decimal(str(numerator)) / denominator_decimal).quantize(
        _FOUR_PLACES,
        rounding=ROUND_HALF_UP,
    )


def strength(sample_size: int, *, minimum_sample_size: int = 30) -> EvidenceStrength:
    if sample_size < minimum_sample_size:
        return EvidenceStrength.INSUFFICIENT_SAMPLE
    if sample_size < minimum_sample_size * 3:
        return EvidenceStrength.WEAK
    if sample_size < minimum_sample_size * 10:
        return EvidenceStrength.MODERATE
    return EvidenceStrength.STRONG


def _decimal(value: object) -> Decimal:
    return Decimal(str(value)).quantize(_TWO_PLACES, rounding=ROUND_HALF_UP)


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "EvidenceCube",
    "EvidenceCubeCell",
    "EvidenceStrength",
    "FeatureImportance",
    "FeatureImportanceReport",
    "HistoricalEvidenceSnapshot",
    "ReplayCandidateObservation",
    "ReplayRunRecord",
    "ReplaySummary",
    "SimulationParameters",
    "SimulationResult",
    "WalkForwardResult",
    "WalkForwardSplit",
    "WeightSuggestion",
    "WeightSuggestionDirection",
    "quantize",
    "ratio",
    "strength",
]
