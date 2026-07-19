from __future__ import annotations

from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from alpha.canonical_integrity_audit.attribution import ZeroTradeAttributionEngine
from alpha.canonical_integrity_audit.case_studies import CaseStudyEngine
from alpha.canonical_integrity_audit.classification import economic_attribution
from alpha.canonical_integrity_audit.models import (
    CANONICAL_POLICY_ID,
    CanonicalIntegrityAuditReport,
    CoverageClassification,
    IntegrityAuditSummary,
    OpportunityDefinition,
    ParityClassification,
    PineExperimentMetadata,
    PineTrade,
    RuntimeReplayComparison,
)
from alpha.canonical_integrity_audit.opportunity_coverage import (
    MajorOpportunityCoverageEngine,
)
from alpha.canonical_integrity_audit.opportunity_events import (
    DEFAULT_OPPORTUNITY_DEFINITIONS,
    MajorOpportunityEventEngine,
)
from alpha.canonical_integrity_audit.parity_engine import TradingViewParityEngine
from alpha.canonical_integrity_audit.parity_inputs import (
    acu_funnel,
    failed_runtime_dates,
    frozen_policy_manifest,
    load_acu_outcomes,
    load_canonical_events,
)
from alpha.canonical_integrity_audit.pine_trade_import import PineTradeImporter
from alpha.canonical_integrity_audit.runtime_failures import (
    RuntimeFailureAuditEngine,
    group_runtime_failures,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore


class CanonicalIntegrityAuditEngine:
    """Run the integrated diagnostic without changing production policy."""

    def run(
        self,
        *,
        store: LegacyMarketDataStore,
        before_acu_directory: Path | str,
        after_acu_directory: Path | str,
        pine_directory: Path | str | None = None,
        start: date | None = None,
        end: date | None = None,
        symbol: str | None = None,
        definitions: tuple[
            OpportunityDefinition, ...
        ] = DEFAULT_OPPORTUNITY_DEFINITIONS,
        generated_at: datetime | None = None,
        source_commit: str | None = None,
    ) -> CanonicalIntegrityAuditReport:
        before_dates = failed_runtime_dates(before_acu_directory)
        runtime_failures = RuntimeFailureAuditEngine().audit_dates(
            store=store,
            dates=before_dates,
        )
        runtime_groups = group_runtime_failures(runtime_failures)
        before = acu_funnel(before_acu_directory)
        after = acu_funnel(after_acu_directory)
        replay = _replay_comparison(before, after, len(runtime_failures))
        candidates = load_canonical_events(after_acu_directory)
        outcomes = load_acu_outcomes(after_acu_directory)
        if pine_directory is None:
            pine_metadata: tuple[PineExperimentMetadata, ...] = ()
            pine_trades: tuple[PineTrade, ...] = ()
        else:
            pine_metadata, pine_trades = PineTradeImporter().import_directory(
                pine_directory
            )
        matches, divergences = TradingViewParityEngine().compare(
            pine_trades=pine_trades,
            alpha_events=candidates,
            runtime_failures=runtime_failures,
        )
        opportunities = MajorOpportunityEventEngine().construct(
            store=store,
            definitions=definitions,
            start=start,
            end=end,
            symbol=symbol,
        )
        sessions = store.trade_dates(start=start, end=end)
        coverage = MajorOpportunityCoverageEngine().classify(
            events=opportunities,
            candidates=candidates,
            outcomes=outcomes,
            runtime_failures=runtime_failures,
            sessions=sessions,
        )
        liquidity = store.liquidity_statistics()
        available_symbols = tuple(str(item) for item in liquidity["symbol"])
        zero_trades = ZeroTradeAttributionEngine().diagnose(
            symbols=available_symbols,
            sessions_examined=len(sessions),
            candidates=candidates,
            runtime_failures=runtime_failures,
        )
        studies = CaseStudyEngine().build(
            available_symbols=available_symbols,
            events=opportunities,
            coverage=coverage,
            candidates=candidates,
            runtime_failures=runtime_failures,
        )
        primary, secondary = economic_attribution(
            coverage=coverage,
            divergences=divergences,
            runtime_failures=runtime_failures,
        )
        counts = Counter(item.classification for item in coverage)
        exact_rate, semantic_rate = _parity_rates(matches)
        highest_missed = _highest_missed(opportunities, coverage)
        largest_divergence = (
            divergences[0].divergence_stage if divergences else "NOT_MEASURED"
        )
        summary = IntegrityAuditSummary(
            runtime_failure_days_before=replay.before_failure_days,
            runtime_failure_days_after=replay.after_failure_days,
            affected_candidates_before=replay.before_affected_candidates,
            affected_candidates_after=replay.after_affected_candidates,
            pine_trades_imported=len(pine_trades),
            exact_parity_rate=exact_rate,
            semantic_parity_rate=semantic_rate,
            major_opportunities=len(opportunities),
            captured=counts[CoverageClassification.CAPTURED],
            partially_captured=counts[CoverageClassification.PARTIALLY_CAPTURED],
            rejected=counts[CoverageClassification.REJECTED],
            missed=counts[CoverageClassification.MISSED],
            runtime_blocked=counts[CoverageClassification.RUNTIME_BLOCKED],
            data_blocked=counts[CoverageClassification.DATA_BLOCKED],
            largest_divergence_stage=largest_divergence,
            highest_value_missed_opportunity=highest_missed,
            primary_bottleneck=primary,
            secondary_bottlenecks=secondary,
        )
        manifest = frozen_policy_manifest(source_commit=source_commit)
        first = start or store.manifest().first_session
        last = end or store.manifest().last_session
        return CanonicalIntegrityAuditReport(
            audit_id=f"CIA-1|{CANONICAL_POLICY_ID}|{first}|{last}",
            generated_at=generated_at or datetime.now(tz=UTC),
            policy=manifest,
            runtime_failures=runtime_failures,
            runtime_groups=runtime_groups,
            runtime_replay=replay,
            pine_metadata=pine_metadata,
            pine_trades=pine_trades,
            parity_matches=matches,
            divergences=divergences,
            opportunities=opportunities,
            coverage=coverage,
            zero_trades=zero_trades,
            case_studies=studies,
            summary=summary,
        )


def _replay_comparison(
    before: dict[str, int],
    after: dict[str, int],
    reproduced_records: int,
) -> RuntimeReplayComparison:
    before_days = before.get("canonical_runtime_failure_days", 0)
    after_days = after.get("canonical_runtime_failure_days", 0)
    return RuntimeReplayComparison(
        before_failure_days=before_days,
        after_failure_days=after_days,
        before_affected_candidates=(reproduced_records or before_days * 10),
        after_affected_candidates=after_days * 10,
        before_scored_candidates=before.get("scored_candidates", 0),
        after_scored_candidates=after.get("scored_candidates", 0),
        before_approval_candidates=before.get("total_approval_candidates", 0),
        after_approval_candidates=after.get("total_approval_candidates", 0),
        before_institutional_approvals=before.get("total_institutional_approvals", 0),
        after_institutional_approvals=after.get("total_institutional_approvals", 0),
        repair=(
            "Bound fractional drawdown at the allocation handoff and exclude "
            "invalid OHLCV bars without substituting prices."
        ),
        repair_scope="CANONICAL_DIAGNOSTIC_ADAPTER_ONLY",
    )


def _parity_rates(matches: tuple[object, ...]) -> tuple[Decimal | None, Decimal | None]:
    if not matches:
        return None, None
    exact = sum(
        getattr(item, "classification") is ParityClassification.EXACT_MATCH
        for item in matches
    )
    semantic = sum(
        getattr(item, "classification")
        in {ParityClassification.EXACT_MATCH, ParityClassification.SEMANTIC_MATCH}
        for item in matches
    )
    total = Decimal(len(matches))
    return Decimal(exact) / total, Decimal(semantic) / total


def _highest_missed(
    opportunities: tuple[object, ...], coverage: tuple[object, ...]
) -> str:
    missed_ids = {
        getattr(item, "event_id")
        for item in coverage
        if getattr(item, "classification")
        in {
            CoverageClassification.MISSED,
            CoverageClassification.REJECTED,
            CoverageClassification.RUNTIME_BLOCKED,
        }
    }
    eligible = tuple(
        item for item in opportunities if getattr(item, "event_id") in missed_ids
    )
    if not eligible:
        return "UNAVAILABLE"
    event = max(eligible, key=lambda item: getattr(item, "forward_return"))
    return (
        f"{getattr(event, 'symbol')} {getattr(event, 'start_date')} "
        f"+{getattr(event, 'forward_return') * Decimal('100'):.2f}%"
    )


__all__ = ["CanonicalIntegrityAuditEngine"]
