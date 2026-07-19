from __future__ import annotations

from alpha.decision_intelligence.engine import InstitutionalDecisionEngine
from alpha.decision_intelligence.models import InstitutionalDecisionReport


class InstitutionalDecisionService:
    def __init__(
        self,
        *,
        engine: InstitutionalDecisionEngine | None = None,
    ) -> None:
        self.engine = engine or InstitutionalDecisionEngine()

    def evaluate_runtime_result(
        self,
        runtime_result: object,
    ) -> InstitutionalDecisionReport:
        run = getattr(runtime_result, "intelligence_run")
        return self.engine.evaluate_recommendations(
            tuple(getattr(run, "recommendations")),
            allocation_plan=getattr(run, "allocation_plan"),
        )


__all__ = ["InstitutionalDecisionService"]
