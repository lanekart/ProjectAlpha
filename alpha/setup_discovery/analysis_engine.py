# ruff: noqa: E501 - evidence prose remains readable as complete report sentences.
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal

from alpha.setup_discovery.models import (
    LookbackEvidence,
    LookbackProofStatus,
    ResearchRecommendation,
    SetupCluster,
    SetupFamilyCatalogEntry,
    SetupFeatureRecord,
    SetupRecommendationRecord,
    TopMissedOpportunity,
    VocabularyClassification,
)

_CANONICAL_COMPATIBILITY = {
    "EMA_RECLAIM": "EMA Pullback",
    "PULLBACK_CONTINUATION": "EMA Pullback",
    "RETEST_HOLD": "EMA Pullback",
    "VOLATILITY_CONTRACTION_BREAKOUT": "VCP",
    "BREAKOUT_FROM_BASE": "Flat Base",
    "VOLUME_BREAKOUT": "Flat Base",
}


class SetupVocabularyEngine:
    def catalog(
        self, clusters: tuple[SetupCluster, ...]
    ) -> tuple[SetupFamilyCatalogEntry, ...]:
        rows = tuple(_catalog_entry(item) for item in clusters)
        return tuple(
            sorted(
                rows,
                key=lambda item: (
                    -item.occurrences_explained,
                    item.cluster_id,
                ),
            )
        )

    def recommendations(
        self, catalog: tuple[SetupFamilyCatalogEntry, ...]
    ) -> tuple[SetupRecommendationRecord, ...]:
        return tuple(_recommendation(item) for item in catalog)


class MissedOpportunityRankingEngine:
    def rank(
        self,
        *,
        records: tuple[SetupFeatureRecord, ...],
        clusters: tuple[SetupCluster, ...],
        case_cluster: dict[str, str],
        lookbacks: tuple[LookbackEvidence, ...],
        limit: int = 100,
    ) -> tuple[TopMissedOpportunity, ...]:
        if limit < 1:
            raise ValueError("missed opportunity rank limit must be positive")
        cluster_by_id = {item.cluster_id: item for item in clusters}
        lookback_by_case = {item.case_id: item for item in lookbacks}
        eligible = tuple(
            item
            for item in records
            if item.failure_reason == "SETUP_FAMILY_NOT_SUPPORTED"
            or (
                item.failure_reason == "LOOKBACK_MISMATCH"
                and lookback_by_case.get(item.case_id) is not None
                and lookback_by_case[item.case_id].status
                is LookbackProofStatus.CONFIRMED
            )
        )
        ranked = sorted(
            eligible,
            key=lambda item: (
                -item.forward_return,
                -item.prospective_rr,
                -item.onset_confidence,
                item.onset_date,
                item.case_id,
            ),
        )[:limit]
        rows = []
        for rank, record in enumerate(ranked, start=1):
            cluster_id = case_cluster.get(record.case_id)
            cluster = cluster_by_id.get(cluster_id or "")
            lookback = lookback_by_case.get(record.case_id)
            required = None if lookback is None else lookback.minimum_visible_lookback
            if record.failure_reason == "LOOKBACK_MISMATCH":
                pattern = (
                    "Canonical context was incomplete; the expanded causal window "
                    f"revealed {record.event_family.replace('_', ' ').lower()}."
                )
                canonical_state = "NO_VALID_SETUP_IN_60_BARS"
                confidence = record.onset_confidence
            else:
                pattern = (
                    f"{cluster.family_name if cluster else record.event_family}: "
                    "causal structure existed but had no recognized canonical setup."
                )
                canonical_state = "UNSUPPORTED_SETUP_FAMILY"
                confidence = (
                    record.onset_confidence
                    if cluster is None
                    else cluster.distinct_archetype_confidence
                )
            rows.append(
                TopMissedOpportunity(
                    rank=rank,
                    case_id=record.case_id,
                    symbol=record.symbol,
                    onset_date=record.onset_date,
                    event_family=record.event_family,
                    cluster_id=cluster_id,
                    cluster_name=(
                        "Expanded Lookback Setup"
                        if cluster is None
                        else cluster.family_name
                    ),
                    canonical_detection_state=canonical_state,
                    unsupported_pattern_description=pattern,
                    canonical_lookback=60,
                    required_lookback=required,
                    prospective_rr=record.prospective_rr,
                    candidate_blocker=record.failure_reason,
                    classification_confidence=confidence,
                    forward_outcome=record.forward_return,
                    evidence_book_page=rank + 1,
                )
            )
        return tuple(rows)


def representative_chart_case_ids(
    clusters: tuple[SetupCluster, ...],
    top: tuple[TopMissedOpportunity, ...],
) -> tuple[str, ...]:
    ordered = [item.case_id for item in top]
    for cluster in clusters:
        ordered.extend(cluster.representative_case_ids)
    return tuple(dict.fromkeys(ordered))


def render_symbol_deep_dive(
    *,
    symbol: str,
    timeline: tuple[dict[str, str], ...],
    lookbacks: tuple[LookbackEvidence, ...],
) -> str:
    normalized = symbol.upper()
    selected = tuple(item for item in lookbacks if item.symbol == normalized)
    lines = [
        f"# {normalized} Setup and Lookback Deep Dive",
        "",
        "Research-only point-in-time evidence. `PRODUCTION_INFLUENCE=false`.",
        "",
        "## Candidate Timeline",
        "",
    ]
    if not timeline:
        lines.append(
            "No frozen candidate-research onset was available for this symbol."
        )
    for index, timeline_item in enumerate(timeline, start=1):
        lines.extend(
            (
                f"### Window {index}: {timeline_item.get('onset_date', 'unavailable')}",
                "",
                f"- Setup evolution: {timeline_item.get('event_family', 'unavailable').replace('_', ' ').title()}",
                f"- Entry / stop / target: {timeline_item.get('entry_trigger', 'unavailable')} / "
                f"{timeline_item.get('prospective_stop', 'unavailable')} / "
                f"{timeline_item.get('prospective_target', 'unavailable')}",
                f"- Prospective reward/risk: {timeline_item.get('prospective_rr', 'unavailable')}",
                f"- Canonical setup recognized: {timeline_item.get('canonical_setup', 'unavailable')}",
                f"- Canonical candidate created: {timeline_item.get('canonical_candidate', 'unavailable')}",
                f"- Frozen blocker: {timeline_item.get('failure_reason', 'unavailable')}",
                "",
            )
        )
    lines.extend(("## Lookback Windows", ""))
    if not selected:
        lines.append("No frozen LOOKBACK_MISMATCH claim existed for this symbol.")
    for evidence in selected:
        lines.extend(
            (
                f"### {evidence.onset_date.isoformat()} - {evidence.event_family.replace('_', ' ').title()}",
                "",
                f"- Canonical window: {evidence.canonical_lookback} bars",
                "- Window results:",
                *tuple(
                    f"  - {window} bars: {result}"
                    for window, result in evidence.window_results.items()
                ),
                f"- Minimum visible window: {_available(evidence.minimum_visible_lookback)}",
                f"- First detectable date: {_available(evidence.first_detectable_date)}",
                f"- Additional bars required: {_available(evidence.additional_bars_required)}",
                f"- Entry extension acceptable: {_available(evidence.extension_acceptable)}",
                f"- Proof result: {evidence.status.value}",
                f"- Explanation: {evidence.difference_explained}",
                "",
            )
        )
    retained_rows = tuple(item for item in selected if item.classification_retained)
    modest_rows = tuple(
        item
        for item in retained_rows
        if item.additional_bars_required is not None
        and item.additional_bars_required <= 30
    )
    if modest_rows:
        conclusion = (
            f"{len(retained_rows)} claimed mismatch window(s) survive causal proof; "
            f"{len(modest_rows)} require no more than 30 additional bars. A modest "
            "lookback change may have improved those cases, but requires separate "
            "walk-forward research before any setup or policy change."
        )
    elif retained_rows:
        conclusion = (
            f"{len(retained_rows)} claimed mismatch window(s) survive only with more "
            "than 30 additional bars. No modest lookback change is supported."
        )
    elif selected:
        conclusion = (
            "None of the claimed mismatches survives causal proof. A lookback change "
            "would not have reliably captured this opportunity under the frozen rules."
        )
    else:
        conclusion = (
            "There is no lookback-mismatch evidence to support changing the canonical "
            "window for this symbol."
        )
    target_statement = _target_symbol_conclusion(normalized, selected)
    if target_statement:
        conclusion = f"{target_statement} {conclusion}"
    lines.extend(("## Conclusion", "", conclusion, ""))
    return "\n".join(lines)


def _target_symbol_conclusion(
    symbol: str, evidence: tuple[LookbackEvidence, ...]
) -> str:
    target_dates = {
        "KALYANKJIL": date(2023, 1, 31),
        "PCJEWELLER": date(2022, 6, 10),
    }
    target_date = target_dates.get(symbol)
    if target_date is None:
        return ""
    rows = tuple(item for item in evidence if item.onset_date == target_date)
    if not rows:
        return f"The focal {target_date.isoformat()} opportunity has no lookback claim."
    if any(item.status is LookbackProofStatus.CONFIRMED for item in rows):
        minimum = min(
            item.minimum_visible_lookback
            for item in rows
            if item.minimum_visible_lookback is not None
        )
        return (
            f"The focal {target_date.isoformat()} opportunity is supported at "
            f"{minimum} bars and was not visible under the 60-bar rule."
        )
    if any(
        item.status is LookbackProofStatus.REJECTED_CANONICAL_WINDOW_SUFFICIENT
        for item in rows
    ):
        return (
            f"The focal {target_date.isoformat()} opportunity was already visible in "
            "60 bars; its miss was not caused by lookback length."
        )
    return (
        f"The focal {target_date.isoformat()} opportunity has no causal expanded-window "
        "proof."
    )


def _catalog_entry(cluster: SetupCluster) -> SetupFamilyCatalogEntry:
    closest = _CANONICAL_COMPATIBILITY.get(cluster.dominant_event_family)
    negative_holdout = (
        cluster.holdout_expectancy is not None and cluster.holdout_expectancy <= 0
    )
    negative_average = (
        cluster.average_net_return_60 is not None and cluster.average_net_return_60 <= 0
    )
    if negative_holdout or negative_average:
        classification = VocabularyClassification.DISCARD
        rationale = "Net expectancy is non-positive in aggregate or holdout evidence."
    elif cluster.family_purity < Decimal("0.55"):
        classification = VocabularyClassification.AMBIGUOUS
        rationale = (
            "The cluster mixes setup labels and is not a coherent vocabulary unit."
        )
    elif closest is not None and cluster.distinct_archetype_confidence >= Decimal(
        "0.55"
    ):
        classification = VocabularyClassification.CANONICAL_VARIANT
        rationale = (
            f"The structure is closest to existing {closest}, with a stable technical "
            "subtype rather than a wholly new setup."
        )
    elif closest is not None:
        classification = VocabularyClassification.EXISTING_CANONICAL_SETUP
        rationale = f"The evidence is already expressible as existing {closest}."
    elif cluster.cross_partition_stability in {"STABLE", "DIRECTIONALLY_STABLE"}:
        classification = VocabularyClassification.NEW_ARCHETYPE
        rationale = "No canonical setup expresses the stable point-in-time structure."
    else:
        classification = VocabularyClassification.AMBIGUOUS
        rationale = (
            "No canonical match exists, but chronological stability is insufficient."
        )
    evidence = _evidence_strength(cluster)
    return SetupFamilyCatalogEntry(
        cluster_id=cluster.cluster_id,
        family_name=cluster.family_name,
        classification=classification,
        closest_canonical_setup=closest,
        occurrences_explained=cluster.occurrences,
        unsupported_case_share=cluster.unsupported_case_share,
        average_expectancy=cluster.average_net_return_60,
        average_reward_risk=cluster.average_reward_risk,
        stability=cluster.cross_partition_stability,
        candidate_explosion_risk=cluster.candidate_explosion_risk,
        evidence_strength=evidence,
        rationale=rationale,
    )


def _recommendation(item: SetupFamilyCatalogEntry) -> SetupRecommendationRecord:
    if item.classification is VocabularyClassification.DISCARD:
        recommendation = ResearchRecommendation.DO_NOT_INTRODUCE
        risk = "HIGH"
        reason = item.rationale
    elif item.candidate_explosion_risk == "HIGH":
        recommendation = ResearchRecommendation.DO_NOT_INTRODUCE
        risk = "HIGH"
        reason = (
            "Observed missed-case coverage is broad enough to create candidate-explosion "
            "risk; do not add it without a full-population false-positive study."
        )
    elif (
        item.classification is VocabularyClassification.NEW_ARCHETYPE
        and item.evidence_strength == "HIGH"
        and item.stability in {"STABLE", "DIRECTIONALLY_STABLE"}
    ):
        recommendation = ResearchRecommendation.INTRODUCE_AS_RESEARCH_SETUP
        risk = "MODERATE"
        reason = (
            "The family is distinct and chronologically stable enough for isolated "
            "walk-forward research, not production introduction."
        )
    elif item.classification is VocabularyClassification.CANONICAL_VARIANT:
        recommendation = ResearchRecommendation.EXTEND_CANONICAL_IN_RESEARCH
        risk = "MODERATE"
        reason = (
            f"Test a narrow {item.closest_canonical_setup} recognition extension in "
            "Strategy Lab with candidate-volume and holdout controls."
        )
    else:
        recommendation = ResearchRecommendation.RESEARCH_FURTHER
        risk = "MODERATE"
        reason = "Evidence is not yet sufficient for a vocabulary or policy decision."
    return SetupRecommendationRecord(
        cluster_id=item.cluster_id,
        family_name=item.family_name,
        recommendation=recommendation,
        evidence_strength=item.evidence_strength,
        risk=risk,
        reason=reason,
    )


def top_three_clusters(clusters: tuple[SetupCluster, ...]) -> tuple[SetupCluster, ...]:
    return tuple(
        sorted(clusters, key=lambda item: (-item.occurrences, item.cluster_id))[:3]
    )


def strongest_research_family(
    catalog: tuple[SetupFamilyCatalogEntry, ...],
) -> str:
    eligible = tuple(
        item
        for item in catalog
        if item.classification is VocabularyClassification.NEW_ARCHETYPE
        and item.average_expectancy is not None
        and item.average_expectancy > 0
    )
    if not eligible:
        return "NONE"
    return max(
        eligible,
        key=lambda item: (
            item.evidence_strength == "HIGH",
            item.stability in {"STABLE", "DIRECTIONALLY_STABLE"},
            item.average_expectancy or Decimal("0"),
            item.occurrences_explained,
        ),
    ).family_name


def _evidence_strength(cluster: SetupCluster) -> str:
    if (
        cluster.occurrences >= 100
        and cluster.distinct_archetype_confidence >= Decimal("0.60")
        and cluster.cross_partition_stability in {"STABLE", "DIRECTIONALLY_STABLE"}
    ):
        return "HIGH"
    if cluster.occurrences >= 30 and cluster.distinct_archetype_confidence >= Decimal(
        "0.40"
    ):
        return "MODERATE"
    return "LOW"


def family_counts(records: tuple[SetupFeatureRecord, ...]) -> Counter[str]:
    return Counter(item.event_family for item in records)


def _available(value: object | None) -> str:
    if value is None:
        return "unavailable"
    if hasattr(value, "isoformat"):
        return str(value.isoformat())
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


__all__ = [
    "MissedOpportunityRankingEngine",
    "SetupVocabularyEngine",
    "render_symbol_deep_dive",
    "representative_chart_case_ids",
    "strongest_research_family",
    "top_three_clusters",
]
