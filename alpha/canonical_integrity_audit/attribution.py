from __future__ import annotations

from collections import Counter, defaultdict

from alpha.canonical_integrity_audit.models import (
    CanonicalTradeEvent,
    RuntimeFailureRecord,
    ZeroTradeDiagnostic,
    ZeroTradeReason,
)


class ZeroTradeAttributionEngine:
    def diagnose(
        self,
        *,
        symbols: tuple[str, ...],
        sessions_examined: int,
        candidates: tuple[CanonicalTradeEvent, ...],
        runtime_failures: tuple[RuntimeFailureRecord, ...] = (),
    ) -> tuple[ZeroTradeDiagnostic, ...]:
        by_symbol: dict[str, list[CanonicalTradeEvent]] = defaultdict(list)
        for item in candidates:
            by_symbol[item.symbol].append(item)
        runtime = Counter(item.symbol for item in runtime_failures)
        rows = []
        for symbol in sorted(
            {item.strip().upper() for item in symbols if item.strip()}
        ):
            records = tuple(by_symbol.get(symbol, ()))
            buy = tuple(
                item for item in records if item.final_signal in {"BUY", "STRONG_BUY"}
            )
            timing = tuple(
                item for item in buy if item.setup_state in {"ENTRY_READY", "ACTIVE"}
            )
            plans = tuple(item for item in timing if _valid_plan(item))
            approved = tuple(item for item in plans if item.rejection_reason is None)
            if approved:
                continue
            reason, primary, secondary = _reason(
                records=records,
                buy=buy,
                timing=timing,
                plans=plans,
                runtime_failures=runtime[symbol],
            )
            rows.append(
                ZeroTradeDiagnostic(
                    symbol=symbol,
                    sessions_examined=sessions_examined,
                    potential_setup_count=len(records),
                    technical_candidate_count=len(records),
                    scored_candidate_count=sum(
                        item.score is not None for item in records
                    ),
                    buy_strong_buy_count=len(buy),
                    timing_valid_count=len(timing),
                    trade_plan_valid_count=len(plans),
                    institutional_approval_count=0,
                    runtime_failures=runtime[symbol],
                    primary_blocker=primary,
                    secondary_blocker=secondary,
                    explanation=reason,
                )
            )
        return tuple(rows)


def _reason(
    *,
    records: tuple[CanonicalTradeEvent, ...],
    buy: tuple[CanonicalTradeEvent, ...],
    timing: tuple[CanonicalTradeEvent, ...],
    plans: tuple[CanonicalTradeEvent, ...],
    runtime_failures: int,
) -> tuple[ZeroTradeReason, str, str | None]:
    if not records:
        if runtime_failures:
            return (
                ZeroTradeReason.NO_TRADES_BECAUSE_RUNTIME_FAILURE,
                "CANONICAL_RUNTIME_ERROR",
                None,
            )
        return (
            ZeroTradeReason.NO_TRADES_BECAUSE_NO_SETUP,
            "NO_TECHNICAL_CANDIDATE",
            None,
        )
    if not buy:
        return ZeroTradeReason.NO_TRADES_BECAUSE_WEAK_SCORE, "WEAK_VERDICT", None
    if not timing:
        return ZeroTradeReason.NO_TRADES_BECAUSE_TIMING, "PENDING_ENTRY_TRIGGER", None
    if not plans:
        return ZeroTradeReason.NO_TRADES_BECAUSE_TRADE_PLAN, "MISSING_TRADE_PLAN", None
    gates = Counter(
        item.final_gate for item in plans if item.rejection_reason is not None
    )
    blocker = gates.most_common(1)[0][0] if gates else "INSTITUTIONAL_GATE"
    return (
        ZeroTradeReason.NO_TRADES_BECAUSE_INSTITUTIONAL_GATE,
        blocker,
        None,
    )


def _valid_plan(candidate: CanonicalTradeEvent) -> bool:
    return (
        candidate.entry is not None
        and candidate.stop is not None
        and candidate.targets[0] is not None
        and candidate.stop < candidate.entry < candidate.targets[0]
    )


__all__ = ["ZeroTradeAttributionEngine"]
