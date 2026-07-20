"""Base lifecycle for all Project Alpha diagnostic engines."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping

from .models import (
    DiagnosticContext,
    DiagnosticResult,
    Finding,
    Recommendation,
    ScoreCard,
)


class DiagnosticEngine(ABC):
    """Run diagnostics through one explicit, non-bypassable lifecycle."""

    engine_key: str
    engine_version: str

    def run(self, context: DiagnosticContext) -> DiagnosticResult:
        """Execute discovery, validation, scoring, classification and advice."""

        if context.engine_key != self.engine_key:
            raise ValueError(
                f"context engine_key {context.engine_key!r} does not match "
                f"engine {self.engine_key!r}"
            )

        discovery = self.discover(context)
        findings = self.validate(context, discovery)
        scorecard = self.score(context, discovery, findings)
        classification = self.classify(context, discovery, findings, scorecard)
        recommendations = self.recommend(
            context,
            discovery,
            findings,
            scorecard,
            classification,
        )
        metadata = self.metadata(context, discovery, findings, scorecard)

        return DiagnosticResult(
            engine_key=self.engine_key,
            engine_version=self.engine_version,
            generated_at=context.as_of,
            classification=classification,
            discovery=discovery,
            findings=findings,
            scorecard=scorecard,
            recommendations=recommendations,
            metadata=metadata,
        )

    @abstractmethod
    def discover(self, context: DiagnosticContext) -> Mapping[str, object]:
        """Discover deterministic input facts without modifying source data."""

    @abstractmethod
    def validate(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
    ) -> tuple[Finding, ...]:
        """Validate discovered facts and return governed findings."""

    @abstractmethod
    def score(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
        findings: tuple[Finding, ...],
    ) -> ScoreCard:
        """Build a transparent multi-dimensional scorecard."""

    @abstractmethod
    def classify(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
        findings: tuple[Finding, ...],
        scorecard: ScoreCard,
    ) -> str:
        """Return the stable top-level diagnostic classification."""

    @abstractmethod
    def recommend(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
        findings: tuple[Finding, ...],
        scorecard: ScoreCard,
        classification: str,
    ) -> tuple[Recommendation, ...]:
        """Return deterministic recommendations ordered by importance."""

    def metadata(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
        findings: tuple[Finding, ...],
        scorecard: ScoreCard,
    ) -> Mapping[str, object]:
        """Return optional engine-specific metadata for exports."""

        del context, discovery, findings, scorecard
        return {}
