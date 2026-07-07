from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


class ExplanationLevel(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    PROFESSIONAL = "professional"


class EvidenceCategory(StrEnum):
    DELIVERY = "DELIVERY"
    DERIVATIVES = "DERIVATIVES"
    BREADTH = "BREADTH"
    LIQUIDITY = "LIQUIDITY"
    SECTOR_ROTATION = "SECTOR_ROTATION"
    CORRELATION = "CORRELATION"
    INSTITUTIONAL_FLOW = "INSTITUTIONAL_FLOW"
    RISK = "RISK"
    OTHER = "OTHER"


class EvidenceDirection(StrEnum):
    SUPPORTIVE = "SUPPORTIVE"
    CAUTION = "CAUTION"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True, slots=True)
class EvidencePoint:
    label: str
    value: str
    interpretation: str

    def __post_init__(self) -> None:
        label = self.label.strip()
        value = self.value.strip()
        interpretation = self.interpretation.strip()

        if not label:
            raise ValueError("evidence label cannot be empty")
        if not value:
            raise ValueError("evidence value cannot be empty")
        if not interpretation:
            raise ValueError("evidence interpretation cannot be empty")

        object.__setattr__(self, "label", label)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "interpretation", interpretation)


@dataclass(frozen=True, slots=True)
class MarketEvidenceSignal:
    category: EvidenceCategory
    label: str
    direction: EvidenceDirection
    strength: Decimal
    observation: str
    meaning: str
    score_points: Decimal = Decimal("0")
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        label = self.label.strip()
        observation = self.observation.strip()
        meaning = self.meaning.strip()
        strength = Decimal(str(self.strength))
        score_points = Decimal(str(self.score_points))
        metadata = MappingProxyType(
            dict(
                sorted(
                    (key.strip(), value.strip()) for key, value in self.metadata.items()
                )
            )
        )

        if not label:
            raise ValueError("market evidence label cannot be empty")
        if strength < _ZERO:
            raise ValueError("market evidence strength cannot be negative")
        if strength > _HUNDRED:
            raise ValueError("market evidence strength cannot exceed 100")
        if not observation:
            raise ValueError("market evidence observation cannot be empty")
        if not meaning:
            raise ValueError("market evidence meaning cannot be empty")
        if score_points < _ZERO:
            raise ValueError("market evidence score points cannot be negative")
        if any(not key or not value for key, value in metadata.items()):
            raise ValueError("market evidence metadata keys and values cannot be empty")

        object.__setattr__(self, "label", label)
        object.__setattr__(self, "strength", strength)
        object.__setattr__(self, "observation", observation)
        object.__setattr__(self, "meaning", meaning)
        object.__setattr__(self, "score_points", score_points)
        object.__setattr__(self, "metadata", metadata)


@dataclass(frozen=True, slots=True)
class EvidenceNarrative:
    symbol: str
    recommendation: str
    score: Decimal
    supportive: tuple[MarketEvidenceSignal, ...]
    cautionary: tuple[MarketEvidenceSignal, ...]
    neutral: tuple[MarketEvidenceSignal, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        recommendation = self.recommendation.strip().upper()
        score = Decimal(str(self.score))

        if not symbol:
            raise ValueError("evidence narrative symbol cannot be empty")
        if not recommendation:
            raise ValueError("evidence narrative recommendation cannot be empty")
        if score < _ZERO:
            raise ValueError("evidence narrative score cannot be negative")
        if score > _HUNDRED:
            raise ValueError("evidence narrative score cannot exceed 100")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "recommendation", recommendation)
        object.__setattr__(self, "score", score)

    @property
    def total_supportive_points(self) -> Decimal:
        return sum((signal.score_points for signal in self.supportive), _ZERO)

    @property
    def total_cautionary_points(self) -> Decimal:
        return sum((signal.score_points for signal in self.cautionary), _ZERO)

    @property
    def strongest_support(self) -> MarketEvidenceSignal | None:
        if not self.supportive:
            return None
        return self.supportive[0]

    @property
    def strongest_caution(self) -> MarketEvidenceSignal | None:
        if not self.cautionary:
            return None
        return self.cautionary[0]


class EvidenceNarrativeEngine:
    def build(
        self,
        *,
        symbol: str,
        recommendation: str,
        score: Decimal,
        evidence: Iterable[MarketEvidenceSignal],
    ) -> EvidenceNarrative:
        signals = tuple(evidence)
        supportive = self._sort_signals(
            signal
            for signal in signals
            if signal.direction is EvidenceDirection.SUPPORTIVE
        )
        cautionary = self._sort_signals(
            signal
            for signal in signals
            if signal.direction is EvidenceDirection.CAUTION
        )
        neutral = self._sort_signals(
            signal
            for signal in signals
            if signal.direction is EvidenceDirection.NEUTRAL
        )

        return EvidenceNarrative(
            symbol=symbol,
            recommendation=recommendation,
            score=score,
            supportive=supportive,
            cautionary=cautionary,
            neutral=neutral,
        )

    def explain(self, narrative: EvidenceNarrative) -> tuple[str, ...]:
        lines = [
            f"Why {narrative.symbol} is {narrative.recommendation}:",
            f"Recommendation Score: {narrative.score}/100",
        ]

        if narrative.supportive:
            lines.append("")
            lines.append("Evidence supporting conviction:")
            for signal in narrative.supportive:
                lines.extend(self._signal_lines(signal))

        if narrative.cautionary:
            lines.append("")
            lines.append("Evidence that can reduce conviction:")
            for signal in narrative.cautionary:
                lines.extend(self._signal_lines(signal))

        if narrative.neutral:
            lines.append("")
            lines.append("Neutral evidence:")
            for signal in narrative.neutral:
                lines.extend(self._signal_lines(signal))

        return tuple(lines)

    def _sort_signals(
        self,
        signals: Iterable[MarketEvidenceSignal],
    ) -> tuple[MarketEvidenceSignal, ...]:
        return tuple(
            sorted(
                signals,
                key=lambda signal: (
                    -signal.score_points,
                    -signal.strength,
                    signal.category.value,
                    signal.label,
                ),
            )
        )

    def _signal_lines(self, signal: MarketEvidenceSignal) -> list[str]:
        lines = [
            f"- {signal.label} [{signal.category.value}]: {signal.observation}",
            f"  Meaning: {signal.meaning}",
            f"  Strength: {signal.strength}/100",
        ]
        if signal.score_points > _ZERO:
            lines.append(f"  Score contribution: {signal.score_points}")
        for key, value in signal.metadata.items():
            lines.append(f"  {key}: {value}")
        return lines


@dataclass(frozen=True, slots=True)
class ScoreContribution:
    name: str
    points: Decimal
    max_points: Decimal
    evidence: tuple[EvidencePoint, ...]
    plain_language: str

    def __post_init__(self) -> None:
        name = self.name.strip()
        plain_language = self.plain_language.strip()

        if not name:
            raise ValueError("contribution name cannot be empty")
        if self.points < _ZERO:
            raise ValueError("contribution points cannot be negative")
        if self.max_points <= _ZERO:
            raise ValueError("contribution max points must be positive")
        if self.points > self.max_points:
            raise ValueError("contribution points cannot exceed max points")
        if not plain_language:
            raise ValueError("contribution plain language cannot be empty")
        if len(self.evidence) == 0:
            raise ValueError("contribution requires at least one evidence point")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "plain_language", plain_language)

    @property
    def score_ratio(self) -> Decimal:
        return self.points / self.max_points


@dataclass(frozen=True, slots=True)
class RiskFactor:
    name: str
    severity: str
    explanation: str

    def __post_init__(self) -> None:
        name = self.name.strip()
        severity = self.severity.strip().lower()
        explanation = self.explanation.strip()

        if not name:
            raise ValueError("risk name cannot be empty")
        if severity not in {"low", "medium", "high"}:
            raise ValueError("risk severity must be low, medium, or high")
        if not explanation:
            raise ValueError("risk explanation cannot be empty")

        object.__setattr__(self, "name", name)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "explanation", explanation)


@dataclass(frozen=True, slots=True)
class RecommendationExplanation:
    symbol: str
    action: str
    score: Decimal
    explanation_level: ExplanationLevel
    contributions: tuple[ScoreContribution, ...]
    risks: tuple[RiskFactor, ...] = ()
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        action = self.action.strip().upper()
        metadata = MappingProxyType(
            dict(
                sorted(
                    (key.strip(), value.strip()) for key, value in self.metadata.items()
                )
            )
        )

        if not symbol:
            raise ValueError("explanation symbol cannot be empty")
        if not action:
            raise ValueError("explanation action cannot be empty")
        if self.score < _ZERO:
            raise ValueError("explanation score cannot be negative")
        if self.score > _HUNDRED:
            raise ValueError("explanation score cannot exceed 100")
        if len(self.contributions) == 0:
            raise ValueError("explanation requires at least one contribution")
        if any(not key or not value for key, value in metadata.items()):
            raise ValueError("metadata keys and values cannot be empty")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "action", action)
        object.__setattr__(self, "metadata", metadata)

    @property
    def total_contribution_points(self) -> Decimal:
        return sum(
            (contribution.points for contribution in self.contributions),
            _ZERO,
        )

    @property
    def top_contribution(self) -> ScoreContribution:
        return max(
            self.contributions,
            key=lambda contribution: contribution.points,
        )


ExplanationReport = RecommendationExplanation


@dataclass(frozen=True, slots=True)
class ExplanationDelta:
    label: str
    previous: str
    current: str
    impact: Decimal
    explanation: str

    def __post_init__(self) -> None:
        label = self.label.strip()
        previous = self.previous.strip()
        current = self.current.strip()
        explanation = self.explanation.strip()

        if not label:
            raise ValueError("delta label cannot be empty")
        if not previous:
            raise ValueError("delta previous value cannot be empty")
        if not current:
            raise ValueError("delta current value cannot be empty")
        if not explanation:
            raise ValueError("delta explanation cannot be empty")

        object.__setattr__(self, "label", label)
        object.__setattr__(self, "previous", previous)
        object.__setattr__(self, "current", current)
        object.__setattr__(self, "explanation", explanation)


@dataclass(frozen=True, slots=True)
class ExplanationChangeReport:
    symbol: str
    previous_score: Decimal
    current_score: Decimal
    deltas: tuple[ExplanationDelta, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()

        if not symbol:
            raise ValueError("change report symbol cannot be empty")
        if self.previous_score < _ZERO:
            raise ValueError("previous score cannot be negative")
        if self.current_score < _ZERO:
            raise ValueError("current score cannot be negative")
        if self.previous_score > _HUNDRED:
            raise ValueError("previous score cannot exceed 100")
        if self.current_score > _HUNDRED:
            raise ValueError("current score cannot exceed 100")
        if len(self.deltas) == 0:
            raise ValueError("change report requires at least one delta")

        object.__setattr__(self, "symbol", symbol)

    @property
    def score_change(self) -> Decimal:
        return self.current_score - self.previous_score


class ExplainabilityEngine:
    def explain(self, explanation: RecommendationExplanation) -> tuple[str, ...]:
        lines = [
            f"{explanation.symbol} {explanation.action} explanation",
            f"Recommendation Score: {explanation.score}/100",
            "",
            self._summary_line(explanation),
            "",
            "Why this recommendation scored this way:",
        ]

        for contribution in explanation.contributions:
            lines.extend(self._contribution_lines(explanation, contribution))

        if explanation.risks:
            lines.append("")
            lines.append("Counterarguments and risks:")
            for risk in explanation.risks:
                lines.append(f"- {risk.name} ({risk.severity}): {risk.explanation}")

        if explanation.metadata:
            lines.append("")
            lines.append("Context:")
            for key, value in explanation.metadata.items():
                lines.append(f"- {key}: {value}")

        return tuple(lines)

    def explain_changes(
        self,
        report: ExplanationChangeReport,
    ) -> tuple[str, ...]:
        direction = "increased"
        if report.score_change < _ZERO:
            direction = "decreased"
        if report.score_change == _ZERO:
            direction = "remained unchanged"

        lines = [
            f"What changed for {report.symbol}:",
            (
                "Recommendation Score "
                f"{direction}: {report.previous_score} "
                f"to {report.current_score}"
            ),
            f"Score change: {report.score_change}",
            "",
            "Key changes:",
        ]

        for delta in sorted(
            report.deltas,
            key=lambda item: abs(item.impact),
            reverse=True,
        ):
            lines.append(
                f"- {delta.label}: {delta.previous} -> {delta.current} "
                f"({delta.impact:+})"
            )
            lines.append(f"  {delta.explanation}")

        return tuple(lines)

    def _summary_line(
        self,
        explanation: RecommendationExplanation,
    ) -> str:
        top = explanation.top_contribution
        return (
            f"{explanation.symbol} received this score mainly because "
            f"{top.name.lower()} contributed {top.points} points."
        )

    def _contribution_lines(
        self,
        explanation: RecommendationExplanation,
        contribution: ScoreContribution,
    ) -> list[str]:
        lines = [
            "",
            (f"{contribution.name}: +{contribution.points}/{contribution.max_points}"),
        ]

        if explanation.explanation_level is ExplanationLevel.BEGINNER:
            lines.append(contribution.plain_language)
            return lines

        for evidence in contribution.evidence:
            lines.append(f"- {evidence.label}: {evidence.value}")
            lines.append(f"  Meaning: {evidence.interpretation}")

        if explanation.explanation_level is ExplanationLevel.PROFESSIONAL:
            lines.append(f"  Contribution ratio: {contribution.score_ratio:.4f}")

        return lines


def build_evidence_points(
    records: Iterable[tuple[str, str, str]],
) -> tuple[EvidencePoint, ...]:
    return tuple(
        EvidencePoint(
            label=label,
            value=value,
            interpretation=interpretation,
        )
        for label, value, interpretation in records
    )


__all__ = [
    "EvidenceCategory",
    "EvidenceDirection",
    "EvidenceNarrative",
    "EvidenceNarrativeEngine",
    "EvidencePoint",
    "ExplainabilityEngine",
    "ExplanationChangeReport",
    "ExplanationDelta",
    "ExplanationLevel",
    "ExplanationReport",
    "MarketEvidenceSignal",
    "RecommendationExplanation",
    "RiskFactor",
    "ScoreContribution",
    "build_evidence_points",
]
