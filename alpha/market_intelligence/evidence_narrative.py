from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from types import MappingProxyType

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")


class EvidenceDirection(StrEnum):
    SUPPORTIVE = "supportive"
    CAUTION = "caution"
    NEUTRAL = "neutral"


class EvidenceCategory(StrEnum):
    DELIVERY = "delivery"
    DERIVATIVES = "derivatives"
    INSTITUTIONAL_FLOW = "institutional_flow"
    PRICE_ACTION = "price_action"
    BREADTH = "breadth"
    LIQUIDITY = "liquidity"
    RISK = "risk"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class MarketEvidenceSignal:
    category: EvidenceCategory
    label: str
    direction: EvidenceDirection
    strength: Decimal
    observation: str
    meaning: str
    score_points: Decimal = _ZERO
    metadata: Mapping[str, str] = MappingProxyType({})

    def __post_init__(self) -> None:
        label = self.label.strip()
        observation = self.observation.strip()
        meaning = self.meaning.strip()
        metadata = MappingProxyType(
            dict(
                sorted(
                    (key.strip(), value.strip()) for key, value in self.metadata.items()
                )
            )
        )

        if not label:
            raise ValueError("evidence label cannot be empty")
        if self.strength < _ZERO:
            raise ValueError("evidence strength cannot be negative")
        if self.strength > _HUNDRED:
            raise ValueError("evidence strength cannot exceed 100")
        if not observation:
            raise ValueError("evidence observation cannot be empty")
        if not meaning:
            raise ValueError("evidence meaning cannot be empty")
        if self.score_points < _ZERO:
            raise ValueError("evidence score points cannot be negative")
        if any(not key or not value for key, value in metadata.items()):
            raise ValueError("metadata keys and values cannot be empty")

        object.__setattr__(self, "label", label)
        object.__setattr__(self, "observation", observation)
        object.__setattr__(self, "meaning", meaning)
        object.__setattr__(self, "metadata", metadata)

    @property
    def is_supportive(self) -> bool:
        return self.direction is EvidenceDirection.SUPPORTIVE

    @property
    def is_cautionary(self) -> bool:
        return self.direction is EvidenceDirection.CAUTION


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

        if not symbol:
            raise ValueError("narrative symbol cannot be empty")
        if not recommendation:
            raise ValueError("narrative recommendation cannot be empty")
        if self.score < _ZERO:
            raise ValueError("narrative score cannot be negative")
        if self.score > _HUNDRED:
            raise ValueError("narrative score cannot exceed 100")

        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "recommendation", recommendation)

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

    @property
    def total_supportive_points(self) -> Decimal:
        return sum(
            (signal.score_points for signal in self.supportive),
            _ZERO,
        )

    @property
    def total_cautionary_points(self) -> Decimal:
        return sum(
            (signal.score_points for signal in self.cautionary),
            _ZERO,
        )


class EvidenceNarrativeEngine:
    def build(
        self,
        *,
        symbol: str,
        recommendation: str,
        score: Decimal,
        evidence: Iterable[MarketEvidenceSignal],
    ) -> EvidenceNarrative:
        supportive: list[MarketEvidenceSignal] = []
        cautionary: list[MarketEvidenceSignal] = []
        neutral: list[MarketEvidenceSignal] = []

        for signal in evidence:
            if signal.direction is EvidenceDirection.SUPPORTIVE:
                supportive.append(signal)
            elif signal.direction is EvidenceDirection.CAUTION:
                cautionary.append(signal)
            else:
                neutral.append(signal)

        return EvidenceNarrative(
            symbol=symbol,
            recommendation=recommendation,
            score=score,
            supportive=self._sorted_signals(supportive),
            cautionary=self._sorted_signals(cautionary),
            neutral=self._sorted_signals(neutral),
        )

    def explain(self, narrative: EvidenceNarrative) -> tuple[str, ...]:
        lines = [
            f"Why {narrative.symbol} is {narrative.recommendation}:",
            f"Recommendation Score: {narrative.score}/100",
            "",
            self._summary(narrative),
        ]

        if narrative.supportive:
            lines.append("")
            lines.append("Evidence supporting the recommendation:")
            lines.extend(self._signal_lines(narrative.supportive))

        if narrative.cautionary:
            lines.append("")
            lines.append("Evidence that can reduce conviction:")
            lines.extend(self._signal_lines(narrative.cautionary))

        if narrative.neutral:
            lines.append("")
            lines.append("Neutral context:")
            lines.extend(self._signal_lines(narrative.neutral))

        return tuple(lines)

    def _summary(self, narrative: EvidenceNarrative) -> str:
        strongest = narrative.strongest_support
        caution = narrative.strongest_caution

        if strongest is None:
            return (
                "The recommendation does not currently have a strong "
                "supportive evidence base."
            )

        if caution is None:
            return (
                f"The recommendation is mainly supported by "
                f"{strongest.label.lower()}, which added "
                f"{strongest.score_points} score points."
            )

        return (
            f"The recommendation is mainly supported by "
            f"{strongest.label.lower()}, while "
            f"{caution.label.lower()} is the main cautionary factor."
        )

    def _signal_lines(
        self,
        signals: tuple[MarketEvidenceSignal, ...],
    ) -> list[str]:
        lines: list[str] = []

        for signal in signals:
            lines.append(
                f"- {signal.label}: {signal.observation} "
                f"(+{signal.score_points} points)"
            )
            lines.append(f"  Meaning: {signal.meaning}")
            for key, value in signal.metadata.items():
                lines.append(f"  {key}: {value}")

        return lines

    def _sorted_signals(
        self,
        signals: Iterable[MarketEvidenceSignal],
    ) -> tuple[MarketEvidenceSignal, ...]:
        return tuple(
            sorted(
                signals,
                key=lambda signal: (
                    signal.score_points,
                    signal.strength,
                    signal.label,
                ),
                reverse=True,
            )
        )


__all__ = [
    "EvidenceCategory",
    "EvidenceDirection",
    "EvidenceNarrative",
    "EvidenceNarrativeEngine",
    "MarketEvidenceSignal",
]
