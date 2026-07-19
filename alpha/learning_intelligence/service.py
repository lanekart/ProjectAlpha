from __future__ import annotations

from pathlib import Path

from alpha.learning_intelligence.engine import AdaptiveLearningEngine
from alpha.learning_intelligence.fingerprints import fingerprint_from_ledger_entry
from alpha.learning_intelligence.rendering import (
    render_learning_explain,
    render_learning_report,
)
from alpha.performance_intelligence.ledger import RecommendationLedgerRepository
from alpha.performance_intelligence.service import resolve_ledger_path


class AdaptiveLearningService:
    def __init__(
        self,
        *,
        repository: RecommendationLedgerRepository,
        engine: AdaptiveLearningEngine | None = None,
    ) -> None:
        self.repository = repository
        self.engine = engine or AdaptiveLearningEngine()

    @classmethod
    def from_path(
        cls,
        ledger_path: Path | str | None = None,
    ) -> AdaptiveLearningService:
        return cls(
            repository=RecommendationLedgerRepository(resolve_ledger_path(ledger_path))
        )

    def report_lines(self) -> tuple[str, ...]:
        report = self.engine.build_report(
            entries=self.repository.load_entries(),
            outcomes=self.repository.load_outcomes(),
        )
        return render_learning_report(report)

    def explain_lines(self, *, symbol: str) -> tuple[str, ...]:
        normalized = symbol.strip().upper()
        entries = tuple(
            entry
            for entry in self.repository.load_entries()
            if entry.symbol == normalized
        )
        if not entries:
            return render_learning_explain(
                symbol=normalized,
                assessment=None,
                missing_reason="No recommendation found in the ledger for this symbol.",
            )
        latest = max(entries, key=lambda entry: entry.generated_at)
        assessment = self.engine.assess_fingerprint(
            fingerprint=fingerprint_from_ledger_entry(latest),
            base_confidence=latest.confidence,
            entries=self.repository.load_entries(),
            outcomes=self.repository.load_outcomes(),
        )
        return render_learning_explain(symbol=normalized, assessment=assessment)


__all__ = ["AdaptiveLearningService"]
