from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Protocol

from alpha.forward_validation.models import (
    CURRENT_POLICY_VERSION,
    DeploymentReadiness,
    DeploymentReadinessReport,
    ForwardPerformanceMetrics,
    ForwardUpdateSummary,
    ForwardValidationConfig,
    ForwardValidationReport,
    PolicyVersion,
    PositionEventDraft,
    PositionEventType,
    PositionJournalRow,
    PositionStatus,
    RecommendationSnapshot,
    ShadowPortfolioSnapshot,
)
from alpha.forward_validation.performance_tracker import PerformanceTracker
from alpha.forward_validation.policy_versioning import PolicyVersionRegistry
from alpha.forward_validation.position_tracker import PositionTracker
from alpha.forward_validation.recommendation_snapshot import (
    RecommendationSnapshotFactory,
)
from alpha.forward_validation.shadow_portfolio import ShadowPortfolio
from alpha.forward_validation.validation_registry import ForwardValidationRegistry
from alpha.market_truth.historical_service import market_bars
from alpha.market_truth.market_truth_engine import MarketTruthEngine
from alpha.recommendation_intelligence.models import OHLCVBar

if TYPE_CHECKING:
    from alpha.application.runtime_models import RuntimeResult


class ForwardPriceSource(Protocol):
    def bars(
        self,
        *,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> tuple[OHLCVBar, ...]: ...

    def close(self) -> None: ...


class PersistedPriceSource:
    """Read future bars exclusively through the Market Truth Engine."""

    def __init__(self, engine: MarketTruthEngine | None = None) -> None:
        self._engine = engine or MarketTruthEngine.default()

    def bars(
        self,
        *,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> tuple[OHLCVBar, ...]:
        truth = self._engine.historical.daily(
            symbols=(symbol,), start=start_date, end=end_date, as_of=end_date
        )
        if not truth.actionable:
            return ()
        return tuple(
            OHLCVBar(
                observed_on=row.observed_at.date(),
                open_price=row.open_price,
                high_price=row.high_price,
                low_price=row.low_price,
                close_price=row.close_price,
                volume=row.volume,
            )
            for row in market_bars(truth)
        )

    def close(self) -> None:
        return None


class ForwardValidationEngine:
    """Coordinate frozen capture, lifecycle tracking, and shadow accounting."""

    def __init__(
        self,
        *,
        registry: ForwardValidationRegistry | None = None,
        price_source_factory: Callable[[], ForwardPriceSource] | None = None,
        snapshot_factory: RecommendationSnapshotFactory | None = None,
        position_tracker: PositionTracker | None = None,
        shadow_portfolio: ShadowPortfolio | None = None,
        performance_tracker: PerformanceTracker | None = None,
        policy_registry: PolicyVersionRegistry | None = None,
    ) -> None:
        self.registry = registry or ForwardValidationRegistry()
        self.price_source_factory = price_source_factory or PersistedPriceSource
        self.snapshot_factory = snapshot_factory or RecommendationSnapshotFactory()
        self.position_tracker = position_tracker or PositionTracker()
        self.shadow_portfolio = shadow_portfolio or ShadowPortfolio()
        self.performance_tracker = performance_tracker or PerformanceTracker()
        self.policy_registry = policy_registry or PolicyVersionRegistry()

    def start(self, config: ForwardValidationConfig) -> bool:
        return self.registry.initialize(config)

    def capture_runtime(
        self,
        runtime_result: RuntimeResult,
        *,
        policy_version: PolicyVersion | None = None,
    ) -> tuple[tuple[RecommendationSnapshot, ...], int]:
        version = policy_version or PolicyVersion(CURRENT_POLICY_VERSION)
        snapshots = self.snapshot_factory.build(
            runtime_result,
            policy_version=version,
        )
        return snapshots, self.registry.append_snapshots(snapshots)

    def update(self, *, as_of: date) -> ForwardUpdateSummary:
        config = self.registry.load_config()
        snapshots = self.registry.load_snapshots()
        source = self.price_source_factory()
        missing_data = 0
        initial_event_count = len(self.registry.load_events())
        try:
            for snapshot in snapshots:
                if snapshot.policy_version != config.policy_version:
                    continue
                events = self.registry.load_events()
                relevant = tuple(
                    event
                    for event in events
                    if event.recommendation_id == snapshot.recommendation_id
                )
                bars = source.bars(
                    symbol=snapshot.symbol,
                    start_date=snapshot.generated_at.date(),
                    end_date=as_of,
                )
                if (
                    not bars
                    and as_of > snapshot.generated_at.date()
                    and snapshot.final_verdict in {"BUY", "STRONG_BUY"}
                    and snapshot.approved_deployment is not None
                ):
                    missing_data += 1
                approved_amount = snapshot.approved_deployment
                if not relevant and approved_amount is not None:
                    portfolio = self._portfolio(
                        config=config,
                        policy_version=snapshot.policy_version,
                        valued_at=datetime.combine(
                            as_of,
                            datetime.min.time(),
                            tzinfo=UTC,
                        ),
                    )
                    rejection = self.shadow_portfolio.risk_rejection(
                        portfolio=portfolio,
                        snapshot=snapshot,
                        approved_amount=approved_amount,
                        controls=config.risk_controls,
                    )
                    if rejection is not None:
                        self.registry.append_event(
                            PositionEventDraft(
                                recommendation_id=snapshot.recommendation_id,
                                symbol=snapshot.symbol,
                                occurred_at=snapshot.generated_at,
                                event_type=PositionEventType.RISK_BLOCKED,
                                reason=rejection,
                                metadata={
                                    "policy_version": snapshot.policy_version.value
                                },
                            )
                        )
                        continue
                drafts = self.position_tracker.evaluate(
                    snapshot=snapshot,
                    bars=bars,
                    existing_events=relevant,
                    approved_amount=approved_amount,
                )
                for draft in drafts:
                    self.registry.append_event(draft)
        finally:
            source.close()
        portfolios = tuple(
            self._portfolio(
                config=config,
                policy_version=version,
                valued_at=datetime.combine(
                    as_of,
                    datetime.min.time(),
                    tzinfo=UTC,
                ),
            )
            for version in _policy_versions(snapshots, config.policy_version)
        )
        events = self.registry.load_events()
        head_hash = events[-1].event_hash if events else "GENESIS"
        for portfolio in portfolios:
            self.registry.append_valuation(
                self.shadow_portfolio.valuation(
                    portfolio,
                    event_head_hash=head_hash,
                )
            )
        final_events = self.registry.load_events()
        new_events = final_events[initial_event_count:]
        return ForwardUpdateSummary(
            recommendations_checked=len(snapshots),
            new_events=len(new_events),
            newly_entered=sum(
                1 for event in new_events if event.event_type is PositionEventType.ENTRY
            ),
            newly_exited=sum(
                1
                for event in new_events
                if event.event_type
                in {
                    PositionEventType.STOP_HIT,
                    PositionEventType.TARGET_3_HIT,
                    PositionEventType.TRAILING_STOP_HIT,
                    PositionEventType.TIME_EXIT,
                    PositionEventType.INVALIDATED,
                }
                or event.metadata.get("terminal") == "true"
            ),
            still_active=sum(
                1
                for portfolio in portfolios
                for position in portfolio.positions
                if position.status is PositionStatus.ACTIVE
            ),
            missing_data_count=missing_data,
            portfolios=portfolios,
        )

    def portfolios(
        self, *, as_of: datetime | None = None
    ) -> tuple[ShadowPortfolioSnapshot, ...]:
        config = self.registry.load_config()
        snapshots = self.registry.load_snapshots()
        timestamp = as_of or datetime.now(tz=UTC)
        return tuple(
            self._portfolio(
                config=config,
                policy_version=version,
                valued_at=timestamp,
            )
            for version in _policy_versions(snapshots, config.policy_version)
        )

    def journal(self) -> tuple[PositionJournalRow, ...]:
        return self.performance_tracker.journal(
            snapshots=self.registry.load_snapshots(),
            events=self.registry.load_events(),
        )

    def performance(self) -> tuple[ForwardPerformanceMetrics, ...]:
        config = self.registry.load_config()
        snapshots = self.registry.load_snapshots()
        return tuple(
            self.performance_tracker.metrics(
                policy_version=version,
                snapshots=snapshots,
                events=self.registry.load_events(),
                valuations=self.registry.load_valuations(),
                initial_capital=config.initial_capital,
            )
            for version in _policy_versions(snapshots, config.policy_version)
        )

    def report(self) -> ForwardValidationReport:
        return self.performance_tracker.report(
            metrics=self.performance(),
            portfolios=self.portfolios(),
            journal=self.journal(),
        )

    def deployment_readiness(self) -> DeploymentReadinessReport:
        metrics = self.performance()
        snapshots = self.registry.load_snapshots()
        candidate_entry = next(
            (
                entry
                for entry in self.policy_registry.entries()
                if entry.get("stage") == "FORWARD_VALIDATION"
            ),
            None,
        )
        candidate = (
            PolicyVersion(candidate_entry["policy_version"])
            if candidate_entry is not None
            else None
        )
        if not snapshots:
            readiness = DeploymentReadiness.NOT_READY
            reason = "No immutable forward snapshots exist."
        else:
            readiness = DeploymentReadiness.FORWARD_VALIDATION
            reason = (
                "Forward validation is active. No evidence-governed promotion "
                "contract exists for limited or production capital."
            )
        missing = []
        if candidate is None:
            missing.append(
                "No offline-validated candidate policy is registered for "
                "forward validation."
            )
        elif not any(item.policy_version == candidate for item in metrics):
            missing.append(f"{candidate.value} has no frozen forward cohort.")
        if not any(item.completed_count for item in metrics):
            missing.append("No completed forward positions are available.")
        return DeploymentReadinessReport(
            generated_at=datetime.now(tz=UTC),
            readiness=readiness,
            policy_versions=tuple(item.policy_version for item in metrics),
            evidence_by_policy=metrics,
            candidate_policy=candidate,
            reason=reason,
            missing_evidence=tuple(missing),
        )

    def _portfolio(
        self,
        *,
        config: ForwardValidationConfig,
        policy_version: PolicyVersion,
        valued_at: datetime,
    ) -> ShadowPortfolioSnapshot:
        return self.shadow_portfolio.build(
            initial_capital=config.initial_capital,
            policy_version=policy_version,
            snapshots=self.registry.load_snapshots(),
            events=self.registry.load_events(),
            valuations=self.registry.load_valuations(),
            valued_at=valued_at,
        )


def _policy_versions(
    snapshots: tuple[RecommendationSnapshot, ...],
    configured: PolicyVersion,
) -> tuple[PolicyVersion, ...]:
    return tuple(
        sorted(
            {configured, *(snapshot.policy_version for snapshot in snapshots)},
            key=lambda item: item.number,
        )
    )


__all__ = [
    "ForwardPriceSource",
    "ForwardValidationEngine",
    "PersistedPriceSource",
]
