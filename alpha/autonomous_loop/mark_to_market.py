from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal
from hashlib import sha256
from typing import Protocol

from alpha.autonomous_loop.models import (
    DecisionKind,
    DecisionMark,
    DecisionResolution,
    FrozenDecision,
    MarkToMarketSummary,
    ResolutionKind,
)
from alpha.autonomous_loop.registry import AutonomousLoopRegistry, canonical_json
from alpha.forward_validation.forward_validation_engine import (
    ForwardPriceSource,
    PersistedPriceSource,
)
from alpha.recommendation_intelligence.models import OHLCVBar


class DecisionPriceSource(Protocol):
    def bars(
        self, *, symbol: str, start_date: date, end_date: date
    ) -> tuple[OHLCVBar, ...]: ...

    def close(self) -> None: ...


class DecisionMarkToMarketEngine:
    """Append daily counterfactual marks and resolve only at a frozen horizon."""

    def __init__(
        self,
        *,
        registry: AutonomousLoopRegistry,
        price_source_factory: Callable[[], DecisionPriceSource] | None = None,
    ) -> None:
        self.registry = registry
        self.price_source_factory = price_source_factory or _persisted_source

    def update(self, *, as_of: date) -> MarkToMarketSummary:
        decisions = self.registry.decisions()
        existing_marks = self.registry.marks()
        existing_resolutions = self.registry.resolutions()
        resolved_ids = {item.decision_id for item in existing_resolutions}
        marks_by_decision: dict[str, list[DecisionMark]] = {}
        for mark in existing_marks:
            marks_by_decision.setdefault(mark.decision_id, []).append(mark)
        new_marks: list[DecisionMark] = []
        new_resolutions: list[DecisionResolution] = []
        missing_data = 0
        source = self.price_source_factory()
        try:
            for decision in decisions:
                if decision.decision_id in resolved_ids:
                    continue
                if decision.reference_price is None or decision.symbol.startswith(
                    "UNIVERSE:"
                ):
                    missing_data += 1
                    continue
                prior = tuple(
                    sorted(
                        marks_by_decision.get(decision.decision_id, []),
                        key=lambda item: item.observed_on,
                    )
                )
                start = (
                    prior[-1].observed_on + timedelta(days=1)
                    if prior
                    else decision.observed_on + timedelta(days=1)
                )
                bars = source.bars(
                    symbol=decision.symbol,
                    start_date=start,
                    end_date=as_of,
                )
                current = list(prior)
                for bar in sorted(bars, key=lambda item: item.observed_on):
                    if len(current) >= decision.markout_horizon_bars:
                        break
                    mark = _mark(decision, bar)
                    current.append(mark)
                    new_marks.append(mark)
                if not current and as_of > decision.observed_on:
                    missing_data += 1
                if len(current) >= decision.markout_horizon_bars:
                    terminal = current[decision.markout_horizon_bars - 1]
                    new_resolutions.append(
                        _resolution(
                            decision,
                            tuple(current[: decision.markout_horizon_bars]),
                            terminal,
                        )
                    )
        finally:
            source.close()
        marks_inserted = self.registry.append_marks(tuple(new_marks))
        resolutions_inserted = self.registry.append_resolutions(tuple(new_resolutions))
        final_resolved = {item.decision_id for item in self.registry.resolutions()}
        unresolved = sum(
            1 for item in decisions if item.decision_id not in final_resolved
        )
        return MarkToMarketSummary(
            decisions_checked=len(decisions),
            marks_inserted=marks_inserted,
            resolutions_inserted=resolutions_inserted,
            unresolved_count=unresolved,
            missing_data_count=missing_data,
        )


def _persisted_source() -> ForwardPriceSource:
    return PersistedPriceSource()


def _mark(decision: FrozenDecision, bar: OHLCVBar) -> DecisionMark:
    assert decision.reference_price is not None
    reference = decision.reference_price
    payload = {
        "decision_id": decision.decision_id,
        "symbol": decision.symbol,
        "observed_on": bar.observed_on.isoformat(),
        "open": str(bar.open_price),
        "high": str(bar.high_price),
        "low": str(bar.low_price),
        "close": str(bar.close_price),
        "volume": str(bar.volume),
    }
    source_hash = sha256(canonical_json(payload).encode()).hexdigest()
    mark_id = sha256(
        f"{decision.decision_id}|{bar.observed_on.isoformat()}|{source_hash}".encode()
    ).hexdigest()[:24]
    return DecisionMark(
        mark_id=mark_id,
        decision_id=decision.decision_id,
        symbol=decision.symbol,
        observed_on=bar.observed_on,
        close_price=bar.close_price,
        high_price=bar.high_price,
        low_price=bar.low_price,
        return_pct=_pct(bar.close_price, reference),
        favorable_excursion_pct=_pct(bar.high_price, reference),
        adverse_excursion_pct=_pct(bar.low_price, reference),
        source_hash=source_hash,
    )


def _resolution(
    decision: FrozenDecision,
    marks: tuple[DecisionMark, ...],
    terminal: DecisionMark,
) -> DecisionResolution:
    realised = terminal.return_pct
    kind = resolution_kind(decision, realised)
    payload = {
        "decision_id": decision.decision_id,
        "terminal_mark_id": terminal.mark_id,
        "kind": kind.value,
        "return": str(realised),
    }
    resolution_id = sha256(canonical_json(payload).encode()).hexdigest()[:24]
    return DecisionResolution(
        resolution_id=resolution_id,
        decision_id=decision.decision_id,
        resolved_at=datetime.combine(terminal.observed_on, time.min, tzinfo=UTC),
        resolution_kind=kind,
        realised_return_pct=realised,
        maximum_favorable_excursion_pct=max(
            item.favorable_excursion_pct for item in marks
        ),
        maximum_adverse_excursion_pct=min(item.adverse_excursion_pct for item in marks),
        bars_observed=len(marks),
        reason=(
            f"frozen {decision.markout_horizon_bars}-bar decision markout matured; "
            "this is not realized shadow trade P/L"
        ),
        terminal_mark_id=terminal.mark_id,
    )


def resolution_kind(
    decision: FrozenDecision, realised_return_pct: Decimal
) -> ResolutionKind:
    if (
        decision.decision_kind is DecisionKind.REJECTED
        and realised_return_pct > Decimal("1")
    ):
        return ResolutionKind.REJECTED_OPPORTUNITY
    if decision.decision_kind in {
        DecisionKind.NO_TRADE,
        DecisionKind.RISK_BLOCKED,
    } and realised_return_pct > Decimal("1"):
        return ResolutionKind.MISSED_OPPORTUNITY
    if decision.decision_kind is DecisionKind.APPROVED_TRADE:
        if realised_return_pct <= Decimal("-25"):
            return ResolutionKind.CATASTROPHIC_LOSS
        if realised_return_pct <= Decimal("-1"):
            return ResolutionKind.LOSER
        if realised_return_pct > Decimal("1"):
            return ResolutionKind.WINNER
    return ResolutionKind.FLAT


def _pct(value: Decimal, reference: Decimal) -> Decimal:
    return ((value - reference) / reference * Decimal("100")).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


__all__ = [
    "DecisionMarkToMarketEngine",
    "DecisionPriceSource",
    "resolution_kind",
]
