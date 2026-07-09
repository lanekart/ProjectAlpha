from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from alpha.application.historical_ingestion import HistoricalIngestionService
from alpha.application.intelligence import (
    IntelligenceApplicationService,
    IntelligenceInputProvider,
)
from alpha.application.runtime_models import (
    RuntimeMetadata,
    RuntimeMode,
    RuntimeResult,
    RuntimeStatus,
)


@dataclass(frozen=True, slots=True)
class ProjectAlphaRuntime:
    """
    Canonical runtime orchestrator for Project Alpha product workflows.

    The runtime owns execution order only. It does not implement market
    analysis, recommendation logic, portfolio construction, explainability,
    rendering, exporting, or CLI behavior.
    """

    historical_ingestion: HistoricalIngestionService
    demo_input_provider: IntelligenceInputProvider | None = None

    def __init__(
        self,
        *,
        historical_ingestion: HistoricalIngestionService | None = None,
        demo_input_provider: IntelligenceInputProvider | None = None,
    ) -> None:
        object.__setattr__(
            self,
            "historical_ingestion",
            historical_ingestion or HistoricalIngestionService(),
        )
        object.__setattr__(self, "demo_input_provider", demo_input_provider)

    def run_daily(
        self,
        *,
        date_str: str = "today",
        demo: bool = False,
    ) -> RuntimeResult:
        """
        Execute the daily Project Alpha investment workflow.

        This is the operator-facing runtime path for live use. It currently
        activates the canonical data, analysis, intelligence, recommendation,
        portfolio-intelligence, allocation, and explainability flow through the
        existing intelligence workflow.
        """

        return self._run_intelligence_workflow(
            date_str=date_str,
            demo=demo,
            workflow="daily",
        )

    def run_intelligence(
        self,
        *,
        date_str: str = "today",
        demo: bool = False,
    ) -> RuntimeResult:
        """
        Execute the canonical intelligence runtime workflow.

        Demo mode preserves deterministic fixture behavior. Live mode loads the
        canonical market-analysis frame through HistoricalIngestionService and
        passes it into IntelligenceApplicationService.
        """

        return self._run_intelligence_workflow(
            date_str=date_str,
            demo=demo,
            workflow="intelligence",
        )

    def _run_intelligence_workflow(
        self,
        *,
        date_str: str,
        demo: bool,
        workflow: str,
    ) -> RuntimeResult:
        started_at = _now_utc()
        requested_on = _parse_runtime_date(date_str)

        if demo:
            service = IntelligenceApplicationService(
                input_provider=self.demo_input_provider
            )
            intelligence_run = service.run(observed_on=requested_on)
            completed_at = _now_utc()

            return RuntimeResult(
                metadata=RuntimeMetadata(
                    requested_on=requested_on,
                    observed_on=requested_on,
                    mode=RuntimeMode.DEMO,
                    status=RuntimeStatus.SUCCESS,
                    started_at=started_at,
                    completed_at=completed_at,
                    attributes={"workflow": workflow},
                ),
                intelligence_run=intelligence_run,
                market_analysis=None,
            )

        market_analysis = self.historical_ingestion.load_analysis(date_str)
        service = IntelligenceApplicationService.from_analysis(
            analysis=market_analysis.analysis,
            price_repository=self.historical_ingestion.ingestion.prices,
        )
        intelligence_run = service.run(observed_on=market_analysis.observed_on)
        completed_at = _now_utc()

        return RuntimeResult(
            metadata=RuntimeMetadata(
                requested_on=market_analysis.requested_on,
                observed_on=market_analysis.observed_on,
                mode=RuntimeMode.LIVE,
                status=RuntimeStatus.SUCCESS,
                started_at=started_at,
                completed_at=completed_at,
                attributes={"workflow": workflow},
            ),
            intelligence_run=intelligence_run,
            market_analysis=market_analysis,
        )


def _parse_runtime_date(date_str: str) -> date:
    if date_str == "today":
        return date.today()
    return date.fromisoformat(date_str)


def _now_utc() -> datetime:
    return datetime.now(UTC)


__all__ = ["ProjectAlphaRuntime"]
