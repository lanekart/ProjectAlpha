from __future__ import annotations

from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from math import sqrt

from alpha.market_dna.feature_enrichment import numeric_value
from alpha.market_dna.models import ClusterResult, FeatureSnapshot

_FEATURES = (
    "strategy_score",
    "stop_distance_pct",
    "reward_risk",
    "price_component",
    "volume_component",
    "candle_component",
)


class ClusterDiscovery:
    """Deterministic feature-only k-means; outcomes are attached after assignment."""

    def discover(
        self,
        snapshots: tuple[FeatureSnapshot, ...],
        *,
        cluster_count: int = 3,
        minimum_support: int = 30,
    ) -> tuple[ClusterResult, ...]:
        if cluster_count < 2 or cluster_count > 5:
            raise ValueError("cluster count must be between 2 and 5")
        usable = tuple(
            item
            for item in snapshots
            if all(numeric_value(item, feature) is not None for feature in _FEATURES)
        )
        if len(usable) < cluster_count * minimum_support:
            return ()
        vectors = _normalised_vectors(usable)
        assignments = _kmeans(vectors, cluster_count)
        output: list[ClusterResult] = []
        for cluster_index in range(cluster_count):
            indexes = tuple(
                index
                for index, assigned in enumerate(assignments)
                if assigned == cluster_index
            )
            if len(indexes) < minimum_support:
                continue
            rows = tuple(usable[index] for index in indexes)
            centroid = tuple(
                sum((vectors[index][dimension] for index in indexes), start=0.0)
                / len(indexes)
                for dimension in range(len(_FEATURES))
            )
            profile = tuple(
                f"{feature}={_band(value)}"
                for feature, value in zip(_FEATURES, centroid, strict=True)
            )
            winners = sum(item.net_return_pct > Decimal("0") for item in rows)
            output.append(
                ClusterResult(
                    cluster_id=f"DNA_CLUSTER_{cluster_index + 1:02d}",
                    sample_size=len(rows),
                    profile=profile,
                    average_net_return_pct=(
                        sum(
                            (item.net_return_pct for item in rows),
                            start=Decimal("0"),
                        )
                        / Decimal(len(rows))
                    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
                    winner_rate_pct=(
                        Decimal(winners) / Decimal(len(rows)) * Decimal("100")
                    ).quantize(Decimal("0.01")),
                    dominant_symbol=Counter(item.symbol for item in rows).most_common(
                        1
                    )[0][0],
                    dominant_setup=Counter(item.setup for item in rows).most_common(1)[
                        0
                    ][0],
                    stability_pct=_split_stability(rows),
                    limitations=(
                        "Clusters use pre-trade features only; outcomes were attached "
                        "after assignment.",
                        "A descriptive cluster is not a strategy or causal market "
                        "state.",
                    ),
                )
            )
        return tuple(output)


def _normalised_vectors(
    rows: tuple[FeatureSnapshot, ...],
) -> tuple[tuple[float, ...], ...]:
    raw = tuple(
        tuple(
            float(numeric_value(item, feature) or Decimal("0")) for feature in _FEATURES
        )
        for item in rows
    )
    columns = tuple(tuple(row[index] for row in raw) for index in range(len(_FEATURES)))
    bounds = tuple((min(column), max(column)) for column in columns)
    return tuple(
        tuple(
            0.0 if high == low else (value - low) / (high - low)
            for value, (low, high) in zip(row, bounds, strict=True)
        )
        for row in raw
    )


def _kmeans(
    vectors: tuple[tuple[float, ...], ...], cluster_count: int
) -> tuple[int, ...]:
    ordered = sorted(range(len(vectors)), key=lambda index: (vectors[index][0], index))
    centroids = [
        vectors[ordered[min(len(ordered) - 1, (index * len(ordered)) // cluster_count)]]
        for index in range(cluster_count)
    ]
    assignments = tuple(0 for _ in vectors)
    for _ in range(25):
        updated = tuple(
            min(
                range(cluster_count),
                key=lambda index: (_distance(vector, centroids[index]), index),
            )
            for vector in vectors
        )
        if updated == assignments:
            break
        assignments = updated
        new_centroids: list[tuple[float, ...]] = []
        for cluster_index in range(cluster_count):
            members = tuple(
                vectors[index]
                for index, assigned in enumerate(assignments)
                if assigned == cluster_index
            )
            if not members:
                new_centroids.append(centroids[cluster_index])
                continue
            new_centroids.append(
                tuple(
                    sum(item[dimension] for item in members) / len(members)
                    for dimension in range(len(_FEATURES))
                )
            )
        centroids = new_centroids
    return assignments


def _distance(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    return sqrt(
        sum((left - right) ** 2 for left, right in zip(first, second, strict=True))
    )


def _band(value: float) -> str:
    if value < 0.34:
        return "LOW"
    if value < 0.67:
        return "MID"
    return "HIGH"


def _split_stability(rows: tuple[FeatureSnapshot, ...]) -> Decimal | None:
    ordered = sorted(rows, key=lambda item: item.candidate_timestamp)
    midpoint = len(ordered) // 2
    if midpoint == 0:
        return None
    early = (
        sum(item.net_return_pct > Decimal("0") for item in ordered[:midpoint])
        / midpoint
    )
    late_rows = ordered[midpoint:]
    late = sum(item.net_return_pct > Decimal("0") for item in late_rows) / len(
        late_rows
    )
    return Decimal(str(max(0.0, 1.0 - abs(early - late)) * 100)).quantize(
        Decimal("0.01")
    )


__all__ = ["ClusterDiscovery"]
