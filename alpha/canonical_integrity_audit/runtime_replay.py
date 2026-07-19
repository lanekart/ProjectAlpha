from __future__ import annotations

from datetime import date

from alpha.canonical_integrity_audit.models import RuntimeReplayComparison
from alpha.canonical_universe_audit.canonical_runner import CanonicalAlphaRunner
from alpha.canonical_universe_audit.models import CanonicalUniverseAuditReport
from alpha.canonical_universe_audit.store import LegacyMarketDataStore


class RuntimeRepairReplayEngine:
    """Verify that the isolated adapter repair executes previously failed days."""

    def replay_failed_dates(
        self,
        *,
        store: LegacyMarketDataStore,
        dates: tuple[date, ...],
        before_scored_candidates: int = 0,
        before_approval_candidates: int = 0,
        before_institutional_approvals: int = 0,
    ) -> RuntimeReplayComparison:
        runner = CanonicalAlphaRunner(store=store)
        failures = 0
        affected = 0
        scored = 0
        approval_candidates = 0
        institutional = 0
        for observed_on in sorted(set(dates)):
            try:
                result = runner.run_day(observed_on)
            except (ArithmeticError, ValueError):
                failures += 1
                affected += 10
                continue
            scored += len(result.intelligence.recommendations)
            approval_candidates += sum(
                item.final_signal in {"BUY", "STRONG_BUY"}
                for item in result.intelligence.recommendations
            )
            institutional += sum(
                item.accepted for item in result.institutional.decisions
            )
        return RuntimeReplayComparison(
            before_failure_days=len(set(dates)),
            after_failure_days=failures,
            before_affected_candidates=len(set(dates)) * 10,
            after_affected_candidates=affected,
            before_scored_candidates=before_scored_candidates,
            after_scored_candidates=scored,
            before_approval_candidates=before_approval_candidates,
            after_approval_candidates=approval_candidates,
            before_institutional_approvals=before_institutional_approvals,
            after_institutional_approvals=institutional,
            repair=(
                "Bound fractional drawdown at the allocation handoff and exclude "
                "invalid OHLCV bars without substituting prices."
            ),
            repair_scope="CANONICAL_DIAGNOSTIC_ADAPTER_ONLY",
        )


def compare_acu_reports(
    before: CanonicalUniverseAuditReport,
    after: CanonicalUniverseAuditReport,
) -> RuntimeReplayComparison:
    return RuntimeReplayComparison(
        before_failure_days=before.executive.canonical_runtime_failure_days,
        after_failure_days=after.executive.canonical_runtime_failure_days,
        before_affected_candidates=(
            before.executive.canonical_runtime_failure_days * 10
        ),
        after_affected_candidates=after.executive.canonical_runtime_failure_days * 10,
        before_scored_candidates=before.executive.scored_candidates,
        after_scored_candidates=after.executive.scored_candidates,
        before_approval_candidates=before.executive.total_approval_candidates,
        after_approval_candidates=after.executive.total_approval_candidates,
        before_institutional_approvals=before.executive.total_institutional_approvals,
        after_institutional_approvals=after.executive.total_institutional_approvals,
        repair=(
            "Bound fractional drawdown at the allocation handoff and exclude "
            "invalid OHLCV bars without substituting prices."
        ),
        repair_scope="CANONICAL_DIAGNOSTIC_ADAPTER_ONLY",
    )


__all__ = ["RuntimeRepairReplayEngine", "compare_acu_reports"]
