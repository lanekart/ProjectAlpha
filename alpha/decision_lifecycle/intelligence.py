from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from alpha.decision_intelligence.opportunity_pipeline import (
    OpportunityPipelineAction,
    OpportunityPipelineDecision,
)
from alpha.decision_lifecycle.lifecycle import (
    LifecycleConfidence,
    LifecycleEvidence,
    LifecycleState,
)


@dataclass(frozen=True, slots=True)
class LifecycleSeed:
    recommendation_id: str
    symbol: str
    state: LifecycleState
    reason: str
    evidence: tuple[LifecycleEvidence, ...]
    confidence: LifecycleConfidence
    production_influence: bool = False

    def __post_init__(self) -> None:
        recommendation_id = self.recommendation_id.strip()
        symbol = self.symbol.strip().upper()
        reason = self.reason.strip()
        if not recommendation_id:
            raise ValueError("recommendation_id cannot be empty")
        if not symbol:
            raise ValueError("symbol cannot be empty")
        if not reason:
            raise ValueError("seed reason cannot be empty")
        if not self.evidence:
            raise ValueError("lifecycle seed requires supporting evidence")
        if self.production_influence:
            raise ValueError("lifecycle seed cannot influence production execution")
        object.__setattr__(self, "recommendation_id", recommendation_id)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "state", LifecycleState(self.state))
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "confidence", LifecycleConfidence(self.confidence))


class OpportunityLifecycleAdapter:
    """Translate pipeline classification into a non-executable lifecycle seed."""

    def seed(
        self,
        decision: OpportunityPipelineDecision,
        *,
        recommendation_id: str,
    ) -> LifecycleSeed:
        candidate = decision.decision.candidate
        common = (
            LifecycleEvidence(
                "PIPELINE_ACTION",
                (
                    "Opportunity pipeline classified the candidate as "
                    f"{decision.action.value}."
                ),
            ),
            LifecycleEvidence(
                "DIRECTION",
                f"Directional verdict is {candidate.final_verdict}.",
            ),
        )
        if decision.action is OpportunityPipelineAction.BUY:
            return LifecycleSeed(
                recommendation_id=recommendation_id,
                symbol=decision.symbol,
                state=LifecycleState.READY,
                reason=(
                    "Institutional deployment gates passed; opportunity is ready for a "
                    "separate human-confirmed capital decision."
                ),
                evidence=common,
                confidence=LifecycleConfidence.HIGH,
            )
        if decision.action is OpportunityPipelineAction.WATCHLIST:
            watchlist_evidence = tuple(
                LifecycleEvidence(reason.value, reason.value.replace("_", " ").title())
                for reason in decision.watchlist_reasons
            )
            return LifecycleSeed(
                recommendation_id=recommendation_id,
                symbol=decision.symbol,
                state=LifecycleState.WATCHLIST,
                reason=decision.explanation,
                evidence=common + watchlist_evidence,
                confidence=LifecycleConfidence.MEDIUM,
            )
        return LifecycleSeed(
            recommendation_id=recommendation_id,
            symbol=decision.symbol,
            state=LifecycleState.AVOID,
            reason=decision.explanation,
            evidence=common,
            confidence=LifecycleConfidence.HIGH,
        )


@dataclass(frozen=True, slots=True)
class PositionReviewInput:
    symbol: str
    stop_broken: bool = False
    thesis_invalidated: bool = False
    severe_deterioration: bool = False
    trailing_stop_triggered: bool = False
    weakening_trend: bool = False
    poor_relative_strength: bool = False
    target_achieved: bool = False
    concentration_percent: Decimal | None = None
    maximum_concentration_percent: Decimal = Decimal("20")
    suggested_reduction_percent: int = 25

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol cannot be empty")
        if self.concentration_percent is not None and self.concentration_percent < 0:
            raise ValueError("concentration_percent cannot be negative")
        if self.maximum_concentration_percent <= 0:
            raise ValueError("maximum_concentration_percent must be positive")
        if not 1 <= self.suggested_reduction_percent <= 100:
            raise ValueError("suggested_reduction_percent must be between 1 and 100")
        object.__setattr__(self, "symbol", symbol)


@dataclass(frozen=True, slots=True)
class PositionReviewDecision:
    state: LifecycleState
    reason: str
    evidence: tuple[LifecycleEvidence, ...]
    confidence: LifecycleConfidence
    reduction_percent: int | None = None
    production_influence: bool = False

    def __post_init__(self) -> None:
        state = LifecycleState(self.state)
        reason = self.reason.strip()
        allowed_states = {
            LifecycleState.HOLD,
            LifecycleState.REDUCE,
            LifecycleState.EXIT,
        }
        if state not in allowed_states:
            raise ValueError("position review may only recommend HOLD, REDUCE, or EXIT")
        if not reason:
            raise ValueError("position review reason cannot be empty")
        if not self.evidence:
            raise ValueError("position review requires supporting evidence")
        if self.production_influence:
            raise ValueError("position review cannot influence production execution")
        if state is LifecycleState.REDUCE:
            if self.reduction_percent is None or not 1 <= self.reduction_percent <= 100:
                raise ValueError("REDUCE requires reduction_percent between 1 and 100")
        elif self.reduction_percent is not None:
            raise ValueError("reduction_percent is valid only for REDUCE")
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "confidence", LifecycleConfidence(self.confidence))


class PositionReviewEngine:
    """Conservative, deterministic HOLD/REDUCE/EXIT interpretation layer."""

    def review(self, inputs: PositionReviewInput) -> PositionReviewDecision:
        exit_signals = (
            (
                inputs.stop_broken,
                "STOP_BROKEN",
                "The active risk stop has been broken.",
            ),
            (
                inputs.thesis_invalidated,
                "THESIS_INVALIDATED",
                "The recorded investment thesis is no longer valid.",
            ),
            (
                inputs.severe_deterioration,
                "SEVERE_DETERIORATION",
                "Multiple material risk signals show severe deterioration.",
            ),
            (
                inputs.trailing_stop_triggered,
                "TRAILING_STOP_TRIGGERED",
                "The governed trailing-stop condition has triggered.",
            ),
        )
        exit_evidence = tuple(
            LifecycleEvidence(code, detail)
            for active, code, detail in exit_signals
            if active
        )
        if exit_evidence:
            return PositionReviewDecision(
                state=LifecycleState.EXIT,
                reason="One or more hard exit conditions have triggered.",
                evidence=exit_evidence,
                confidence=LifecycleConfidence.HIGH,
            )

        reduce_evidence: list[LifecycleEvidence] = []
        if inputs.weakening_trend:
            reduce_evidence.append(
                LifecycleEvidence("WEAKENING_TREND", "Trend quality is weakening.")
            )
        if inputs.poor_relative_strength:
            reduce_evidence.append(
                LifecycleEvidence(
                    "POOR_RELATIVE_STRENGTH",
                    "Relative strength has deteriorated versus the relevant benchmark.",
                )
            )
        if inputs.target_achieved:
            reduce_evidence.append(
                LifecycleEvidence(
                    "TARGET_ACHIEVED",
                    "A governed profit target has been achieved.",
                )
            )
        if (
            inputs.concentration_percent is not None
            and inputs.concentration_percent > inputs.maximum_concentration_percent
        ):
            reduce_evidence.append(
                LifecycleEvidence(
                    "CONCENTRATION_EXCEEDED",
                    "Position concentration exceeds the configured portfolio limit.",
                )
            )
        if reduce_evidence:
            return PositionReviewDecision(
                state=LifecycleState.REDUCE,
                reason=(
                    "Risk/reward no longer supports retaining the full position "
                    "size."
                ),
                evidence=tuple(reduce_evidence),
                confidence=LifecycleConfidence.MEDIUM,
                reduction_percent=inputs.suggested_reduction_percent,
            )

        return PositionReviewDecision(
            state=LifecycleState.HOLD,
            reason="No hard exit or partial-reduction condition is currently present.",
            evidence=(
                LifecycleEvidence(
                    "THESIS_INTACT",
                    (
                        "Available position evidence does not invalidate the active "
                        "thesis."
                    ),
                ),
            ),
            confidence=LifecycleConfidence.MEDIUM,
        )
