from __future__ import annotations

from datetime import UTC, date, datetime

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.runtime import ProjectAlphaRuntime
from alpha.application.runtime_models import (
    RuntimeMetadata,
    RuntimeMode,
    RuntimeResult,
    RuntimeStatus,
)
from alpha.autonomous_loop.models import UniverseDefinition, UniverseSource


class RegisteredUniverseRuntime:
    """Generate intelligence from the exact registered universe population."""

    def __init__(self, runtime: ProjectAlphaRuntime | None = None) -> None:
        self.runtime = runtime or ProjectAlphaRuntime()

    def run(self, *, universe: UniverseDefinition, as_of: date) -> RuntimeResult:
        if universe.source is UniverseSource.CANONICAL_RUNTIME:
            return self.runtime.run_intelligence(
                date_str=as_of.isoformat(),
                demo=False,
            )
        started_at = datetime.now(tz=UTC)
        market_analysis = self.runtime.historical_ingestion.load_analysis(
            as_of.isoformat()
        )
        frame = market_analysis.analysis.copy()
        normalized = frame["symbol"].astype(str).str.strip().str.upper()
        selected = frame.loc[normalized.isin(universe.symbols)].copy()
        if selected.empty:
            raise ValueError(
                f"registered universe {universe.universe_id} has no available rows"
            )
        service = IntelligenceApplicationService.from_analysis(
            analysis=selected,
            price_repository=self.runtime.historical_ingestion.ingestion.prices,
        )
        intelligence = service.run(observed_on=market_analysis.observed_on)
        completed_at = datetime.now(tz=UTC)
        return RuntimeResult(
            metadata=RuntimeMetadata(
                requested_on=market_analysis.requested_on,
                observed_on=market_analysis.observed_on,
                mode=RuntimeMode.LIVE,
                status=RuntimeStatus.SUCCESS,
                started_at=started_at,
                completed_at=completed_at,
                attributes={
                    "workflow": "autonomous",
                    "universe_id": universe.universe_id,
                    "universe_version": universe.version,
                },
            ),
            intelligence_run=intelligence,
            market_analysis=market_analysis,
        )


__all__ = ["RegisteredUniverseRuntime"]
