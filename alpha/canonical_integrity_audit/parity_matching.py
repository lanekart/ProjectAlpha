from __future__ import annotations

from datetime import date
from decimal import Decimal

from alpha.canonical_integrity_audit.models import (
    CanonicalTradeEvent,
    EvidenceClass,
    ParityClassification,
    PineAlphaTradeMatch,
    PineTrade,
    RuntimeFailureRecord,
)


def match_pine_trade(
    pine: PineTrade,
    candidates: tuple[CanonicalTradeEvent, ...],
    runtime_failures: tuple[RuntimeFailureRecord, ...] = (),
) -> PineAlphaTradeMatch:
    symbol_candidates = tuple(item for item in candidates if item.symbol == pine.symbol)
    same_day = tuple(
        item for item in symbol_candidates if item.observed_on == pine.entry_date
    )
    nearby = tuple(
        item
        for item in symbol_candidates
        if abs((item.observed_on - pine.entry_date).days) <= 5
    )
    runtime = any(
        item.symbol == pine.symbol
        and abs((item.trading_date - pine.entry_date).days) <= 5
        for item in runtime_failures
    )
    alpha = _closest(same_day or nearby, pine.entry_date)
    classification = _classification(pine, alpha, runtime=runtime)
    return PineAlphaTradeMatch(
        pine_trade_id=pine.trade_id,
        alpha_candidate_id=None if alpha is None else alpha.candidate_id,
        symbol=pine.symbol,
        classification=classification,
        pine_entry_date=pine.entry_date,
        alpha_candidate_date=None if alpha is None else alpha.observed_on,
        pine_score=pine.score,
        alpha_score=None if alpha is None else alpha.score,
        score_delta=_delta(pine.score, None if alpha is None else alpha.score),
        pine_setup=pine.setup_family,
        alpha_setup=None if alpha is None else alpha.setup,
        pine_strategy=pine.strategy_family,
        alpha_strategy=None if alpha is None else alpha.strategy,
        pine_entry=pine.entry_price,
        alpha_entry=None if alpha is None else alpha.entry,
        pine_stop=pine.stop_price,
        alpha_stop=None if alpha is None else alpha.stop,
        pine_targets=(pine.target_1, pine.target_2, pine.target_3),
        alpha_targets=(None, None, None) if alpha is None else alpha.targets,
        final_alpha_gate=None if alpha is None else alpha.final_gate,
        alpha_rejection_reason=None if alpha is None else alpha.rejection_reason,
        outcome_difference=None,
    )


def _classification(
    pine: PineTrade,
    alpha: CanonicalTradeEvent | None,
    *,
    runtime: bool,
) -> ParityClassification:
    if alpha is None:
        if runtime:
            return ParityClassification.ALPHA_RUNTIME_BLOCKED
        if pine.evidence_class is EvidenceClass.SCREENSHOT_DERIVED:
            return ParityClassification.PINE_APPROXIMATION
        return ParityClassification.ALPHA_SETUP_NOT_DETECTED
    if alpha.runtime_blocked:
        return ParityClassification.ALPHA_RUNTIME_BLOCKED
    if _normalized(pine.setup_family) != _normalized(alpha.setup):
        return ParityClassification.ALPHA_SETUP_NOT_DETECTED
    if pine.entry_date != alpha.observed_on:
        return ParityClassification.ALPHA_ENTRY_TIMING_DIFFERENCE
    if pine.score is not None and alpha.score is not None:
        if abs(pine.score - alpha.score) > Decimal("0.50"):
            return ParityClassification.ALPHA_CANDIDATE_DIFFERENT_SCORE
    if alpha.rejection_reason is not None:
        return ParityClassification.ALPHA_CANDIDATE_REJECTED
    if not _levels_match(pine.entry_price, alpha.entry) or not _levels_match(
        pine.stop_price, alpha.stop
    ):
        return ParityClassification.ALPHA_TRADE_PLAN_DIFFERENCE
    if pine.evidence_class is EvidenceClass.SCREENSHOT_DERIVED:
        return ParityClassification.PINE_APPROXIMATION
    if _exact_levels(pine, alpha):
        return ParityClassification.EXACT_MATCH
    return ParityClassification.SEMANTIC_MATCH


def _closest(
    candidates: tuple[CanonicalTradeEvent, ...],
    target: date,
) -> CanonicalTradeEvent | None:
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda item: (abs((item.observed_on - target).days), item.candidate_id),
    )


def _levels_match(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return True
    tolerance = max(Decimal("0.01"), abs(left) * Decimal("0.005"))
    return abs(left - right) <= tolerance


def _exact_levels(pine: PineTrade, alpha: CanonicalTradeEvent) -> bool:
    available = tuple(
        (left, right)
        for left, right in (
            (pine.entry_price, alpha.entry),
            (pine.stop_price, alpha.stop),
            (pine.target_1, alpha.targets[0]),
        )
        if left is not None and right is not None
    )
    return bool(available) and all(
        abs(left - right) <= Decimal("0.01") for left, right in available
    )


def _normalized(value: str) -> str:
    return "".join(character for character in value.upper() if character.isalnum())


def _delta(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    return None if left is None or right is None else left - right


__all__ = ["match_pine_trade"]
