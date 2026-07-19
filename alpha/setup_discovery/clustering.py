from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from decimal import Decimal
from statistics import median

import numpy as np

from alpha.setup_discovery.feature_engine import cluster_feature_names
from alpha.setup_discovery.models import (
    EvidencePartition,
    SetupCluster,
    SetupFeatureRecord,
)

CLUSTERING_VERSION = "deterministic-robust-kmeans-v1.0"


@dataclass(frozen=True, slots=True)
class ClusterResult:
    clusters: tuple[SetupCluster, ...]
    case_cluster: dict[str, str]
    selected_k: int
    selection_score: Decimal


class UnsupportedSetupClusterEngine:
    """Cluster causal setup features without exposing outcome columns."""

    def cluster(
        self,
        records: tuple[SetupFeatureRecord, ...],
        *,
        minimum_clusters: int = 8,
        maximum_clusters: int = 15,
        unsupported_population: int | None = None,
    ) -> ClusterResult:
        unsupported = tuple(
            item
            for item in records
            if item.failure_reason == "SETUP_FAMILY_NOT_SUPPORTED"
        )
        if len(unsupported) < minimum_clusters:
            raise ValueError("insufficient unsupported setup cases for clustering")
        population = unsupported_population or len(unsupported)
        if population < len(unsupported):
            raise ValueError(
                "unsupported population cannot be smaller than feature rows"
            )
        matrix = np.asarray(
            [
                [
                    np.nan if item is None else float(item)
                    for item in row.cluster_vector()
                ]
                for row in unsupported
            ],
            dtype=float,
        )
        prepared, medians, scales = _robust_scale(matrix)
        candidates: list[tuple[float, int, np.ndarray, np.ndarray]] = []
        upper = min(maximum_clusters, len(unsupported))
        for count in range(minimum_clusters, upper + 1):
            labels, centroids = _kmeans(prepared, count)
            score = _selection_score(prepared, labels, centroids)
            candidates.append((score, count, labels, centroids))
        score, selected_k, labels, centroids = max(
            candidates, key=lambda item: (item[0], -item[1])
        )
        ordered_labels = _stable_cluster_order(labels, unsupported)
        remapped = np.asarray([ordered_labels[int(item)] for item in labels], dtype=int)
        remapped_centroids = np.asarray(
            [
                centroids[old]
                for old, _new in sorted(ordered_labels.items(), key=lambda x: x[1])
            ]
        )
        clusters, case_cluster = _describe_clusters(
            records=unsupported,
            matrix=matrix,
            prepared=prepared,
            labels=remapped,
            centroids=remapped_centroids,
            medians=medians,
            scales=scales,
            population=population,
        )
        return ClusterResult(
            clusters=clusters,
            case_cluster=case_cluster,
            selected_k=selected_k,
            selection_score=_decimal(score),
        )


def with_representative_pages(
    clusters: tuple[SetupCluster, ...],
    page_by_case: dict[str, int],
) -> tuple[SetupCluster, ...]:
    return tuple(
        replace(
            cluster,
            representative_chart_pages=tuple(
                page_by_case[case_id]
                for case_id in cluster.representative_case_ids
                if case_id in page_by_case
            ),
        )
        for cluster in clusters
    )


def _robust_scale(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    medians = np.asarray(
        [
            float(np.median(column[np.isfinite(column)]))
            if np.any(np.isfinite(column))
            else 0.0
            for column in matrix.T
        ]
    )
    filled = np.where(np.isnan(matrix), medians, matrix)
    lower = np.percentile(filled, 25, axis=0)
    upper = np.percentile(filled, 75, axis=0)
    scales = upper - lower
    standard = np.std(filled, axis=0)
    scales = np.where(scales > 1e-12, scales, standard)
    scales = np.where(scales > 1e-12, scales, 1.0)
    prepared = np.clip((filled - medians) / scales, -5.0, 5.0)
    return prepared, medians, scales


def _kmeans(matrix: np.ndarray, count: int) -> tuple[np.ndarray, np.ndarray]:
    centroids = _initial_centroids(matrix, count)
    labels = np.zeros(len(matrix), dtype=int)
    for _iteration in range(100):
        distances = _distances(matrix, centroids)
        next_labels = np.argmin(distances, axis=1)
        next_centroids = np.asarray(
            [
                matrix[next_labels == index].mean(axis=0)
                if np.any(next_labels == index)
                else centroids[index]
                for index in range(count)
            ]
        )
        if np.array_equal(next_labels, labels) and np.allclose(
            next_centroids, centroids, atol=1e-8
        ):
            labels = next_labels
            centroids = next_centroids
            break
        labels = next_labels
        centroids = next_centroids
    return labels, centroids


def _initial_centroids(matrix: np.ndarray, count: int) -> np.ndarray:
    center = np.median(matrix, axis=0)
    first = int(np.argmin(np.sum((matrix - center) ** 2, axis=1)))
    chosen = [first]
    minimum = np.sum((matrix - matrix[first]) ** 2, axis=1)
    for _index in range(1, count):
        candidate = int(np.argmax(minimum))
        chosen.append(candidate)
        distance = np.sum((matrix - matrix[candidate]) ** 2, axis=1)
        minimum = np.minimum(minimum, distance)
    return matrix[np.asarray(chosen)].copy()


def _distances(matrix: np.ndarray, centroids: np.ndarray) -> np.ndarray:
    return np.sum((matrix[:, None, :] - centroids[None, :, :]) ** 2, axis=2)


def _selection_score(
    matrix: np.ndarray,
    labels: np.ndarray,
    centroids: np.ndarray,
) -> float:
    distances = np.sqrt(_distances(matrix, centroids))
    own = distances[np.arange(len(matrix)), labels]
    masked = distances.copy()
    masked[np.arange(len(matrix)), labels] = np.inf
    alternate = np.min(masked, axis=1)
    denominator = np.maximum(own, alternate)
    silhouette = np.zeros_like(denominator)
    np.divide(alternate - own, denominator, out=silhouette, where=denominator > 0)
    sizes = np.bincount(labels, minlength=len(centroids))
    minimum_share = float(sizes.min()) / float(len(matrix))
    underfilled_penalty = max(0.0, 0.01 - minimum_share) * 20.0
    if int(sizes.min()) < 20:
        underfilled_penalty += 0.25
    return float(np.mean(silhouette)) - underfilled_penalty


def _stable_cluster_order(
    labels: np.ndarray,
    records: tuple[SetupFeatureRecord, ...],
) -> dict[int, int]:
    keys = []
    for label in sorted(set(int(item) for item in labels)):
        members = [records[index] for index in np.flatnonzero(labels == label)]
        dominant = Counter(item.event_family for item in members).most_common(1)[0][0]
        keys.append((-len(members), dominant, label))
    return {old: new for new, (_size, _dominant, old) in enumerate(sorted(keys))}


def _describe_clusters(
    *,
    records: tuple[SetupFeatureRecord, ...],
    matrix: np.ndarray,
    prepared: np.ndarray,
    labels: np.ndarray,
    centroids: np.ndarray,
    medians: np.ndarray,
    scales: np.ndarray,
    population: int,
) -> tuple[tuple[SetupCluster, ...], dict[str, str]]:
    total = population
    clusters: list[SetupCluster] = []
    case_cluster: dict[str, str] = {}
    used_names: Counter[str] = Counter()
    centroid_distances = np.sqrt(_distances(centroids, centroids))
    np.fill_diagonal(centroid_distances, np.inf)
    for label in range(len(centroids)):
        indexes = np.flatnonzero(labels == label)
        members = tuple(records[int(index)] for index in indexes)
        cluster_id = f"SDE-FAMILY-{label + 1:02d}"
        for member in members:
            case_cluster[member.case_id] = cluster_id
        family_counts = Counter(item.event_family for item in members)
        dominant, dominant_count = family_counts.most_common(1)[0]
        raw_name = _family_name(members, dominant)
        used_names[raw_name] += 1
        name = (
            raw_name
            if used_names[raw_name] == 1
            else f"{raw_name} {used_names[raw_name]}"
        )
        distances = np.linalg.norm(prepared[indexes] - centroids[label], axis=1)
        representatives = _representatives(members, distances)
        outcome_values = [
            item.net_return_60 for item in members if item.net_return_60 is not None
        ]
        partition_values = {
            partition: [
                item.net_return_60
                for item in members
                if item.partition is partition and item.net_return_60 is not None
            ]
            for partition in EvidencePartition
        }
        partition_means = {
            partition: _mean(values) for partition, values in partition_values.items()
        }
        separation = float(np.min(centroid_distances[label]))
        support = min(1.0, math_log_support(len(members)))
        confidence = min(1.0, max(0.0, separation / 4.0) * 0.55 + support * 0.45)
        centroid = centroids[label] * scales + medians
        clusters.append(
            SetupCluster(
                cluster_id=cluster_id,
                family_name=name,
                occurrences=len(members),
                unsupported_case_share=_decimal(len(members) / total),
                dominant_event_family=dominant,
                family_purity=_decimal(dominant_count / len(members)),
                representative_symbols=tuple(item.symbol for item in representatives),
                representative_case_ids=tuple(item.case_id for item in representatives),
                representative_chart_pages=(),
                average_reward_risk=_mean_required(
                    [item.prospective_rr for item in members]
                ),
                median_holding_period=_decimal(
                    median(item.holding_period for item in members)
                ),
                average_forward_outcome=_mean_required(
                    [item.forward_return for item in members]
                ),
                average_net_return_60=_mean(outcome_values),
                distinct_archetype_confidence=_decimal(confidence),
                development_expectancy=partition_means[EvidencePartition.DEVELOPMENT],
                validation_expectancy=partition_means[EvidencePartition.VALIDATION],
                holdout_expectancy=partition_means[EvidencePartition.HOLDOUT],
                cross_partition_stability=_stability(partition_means),
                candidate_explosion_risk=_explosion(len(members), total),
                feature_centroid={
                    name: f"{float(value):.6f}"
                    for name, value in zip(
                        cluster_feature_names(), centroid, strict=True
                    )
                },
            )
        )
    return tuple(clusters), case_cluster


def _representatives(
    members: tuple[SetupFeatureRecord, ...], distances: np.ndarray
) -> tuple[SetupFeatureRecord, ...]:
    ranked = sorted(
        zip(members, distances, strict=True),
        key=lambda item: (float(item[1]), item[0].symbol, item[0].onset_date),
    )
    selected: list[SetupFeatureRecord] = []
    used_symbols: set[str] = set()
    for record, _distance in ranked:
        if record.symbol in used_symbols:
            continue
        selected.append(record)
        used_symbols.add(record.symbol)
        if len(selected) == 3:
            break
    return tuple(selected)


def _family_name(members: tuple[SetupFeatureRecord, ...], dominant: str) -> str:
    geometries = Counter(item.consolidation_geometry for item in members)
    geometry = geometries.most_common(1)[0][0]
    depth = Decimal(str(median(float(item.base_depth) for item in members)))
    duration = Decimal(str(median(item.base_duration for item in members)))
    alignments = [
        item.moving_average_alignment
        for item in members
        if item.moving_average_alignment is not None
    ]
    alignment = _mean(alignments)
    volume_values = [
        item.breakout_volume for item in members if item.breakout_volume is not None
    ]
    volume = _mean(volume_values)
    atr_values = [
        item.atr_expansion for item in members if item.atr_expansion is not None
    ]
    atr = _mean(atr_values)
    prefix = {
        "CONTRACTING": "Contracting",
        "ASCENDING": "Ascending",
        "REVERSAL": "Reversal",
        "FLAT": "Flat-Base",
        "IRREGULAR": "Irregular",
    }[geometry.value]
    base = (
        "Deep-Base"
        if depth >= Decimal("0.28")
        else ("Shallow-Base" if depth <= Decimal("0.16") else "Moderate-Base")
    )
    duration_label = "Long" if duration >= 60 else ("Short" if duration <= 20 else "")
    alignment_label = ""
    if alignment is not None:
        if alignment <= Decimal("-0.10"):
            alignment_label = "Strongly-Misaligned"
        elif alignment < 0:
            alignment_label = "Misaligned"
        elif alignment >= Decimal("0.03"):
            alignment_label = "Aligned"
    volume_label = "Normal-Volume"
    if volume is not None:
        if volume >= 10:
            volume_label = "Abnormal-Volume"
        elif volume >= 3:
            volume_label = "Surge-Volume"
        elif volume >= Decimal("1.5"):
            volume_label = "Confirmed-Volume"
        elif volume < Decimal("0.8"):
            volume_label = "Weak-Volume"
    atr_label = ""
    if atr is not None:
        if atr >= Decimal("2.5"):
            atr_label = "Extreme-ATR"
        elif atr >= Decimal("1.8"):
            atr_label = "Expanded-ATR"
    family = dominant.replace("_", " ").title()
    parts = (
        base,
        duration_label,
        alignment_label,
        prefix,
        family,
        volume_label,
        atr_label,
    )
    return " ".join(item for item in parts if item)


def _stability(values: dict[EvidencePartition, Decimal | None]) -> str:
    available = [item for item in values.values() if item is not None]
    if len(available) < 3:
        return "INSUFFICIENT_EVIDENCE"
    signs = {item >= 0 for item in available}
    if len(signs) > 1:
        return "UNSTABLE"
    spread = max(available) - min(available)
    return "STABLE" if spread <= Decimal("0.10") else "DIRECTIONALLY_STABLE"


def _explosion(count: int, total: int) -> str:
    share = Decimal(count) / Decimal(total)
    if share >= Decimal("0.15"):
        return "HIGH"
    if share >= Decimal("0.05"):
        return "MODERATE"
    return "LOW"


def _mean(values: list[Decimal]) -> Decimal | None:
    return None if not values else _mean_required(values)


def _mean_required(values: list[Decimal]) -> Decimal:
    return (sum(values, Decimal("0")) / Decimal(len(values))).quantize(
        Decimal("0.000001")
    )


def _decimal(value: float | int | Decimal) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.000001"))


def math_log_support(count: int) -> float:
    return min(1.0, float(np.log1p(count)) / float(np.log1p(500)))


__all__ = [
    "CLUSTERING_VERSION",
    "ClusterResult",
    "UnsupportedSetupClusterEngine",
    "with_representative_pages",
]
