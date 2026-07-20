"""Transparent scoring helpers for diagnostic engines."""

from __future__ import annotations

from collections.abc import Iterable

from .models import ScoreCard, ScoreDimension


def build_scorecard(dimensions: Iterable[ScoreDimension]) -> ScoreCard:
    """Validate dimensions and calculate a normalized weighted score.

    Scores must be in the inclusive range 0..100. Weights must be non-negative,
    and at least one dimension must carry a positive weight.
    """

    items = tuple(dimensions)
    if not items:
        raise ValueError("at least one score dimension is required")

    for item in items:
        if not 0.0 <= item.score <= 100.0:
            raise ValueError(f"score for {item.key!r} must be between 0 and 100")
        if item.weight < 0.0:
            raise ValueError(f"weight for {item.key!r} must be non-negative")

    total_weight = sum(item.weight for item in items)
    if total_weight <= 0.0:
        raise ValueError("at least one score dimension must have positive weight")

    weighted_score = sum(item.score * item.weight for item in items) / total_weight
    return ScoreCard(dimensions=items, weighted_score=round(weighted_score, 4))
