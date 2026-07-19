from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from alpha.candidate_generation_research.exports import (
    DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.setup_discovery.analysis_engine import (
    MissedOpportunityRankingEngine,
    SetupVocabularyEngine,
    render_symbol_deep_dive,
    representative_chart_case_ids,
    strongest_research_family,
    top_three_clusters,
)
from alpha.setup_discovery.clustering import (
    CLUSTERING_VERSION,
    UnsupportedSetupClusterEngine,
    with_representative_pages,
)
from alpha.setup_discovery.evidence_loader import CandidateResearchEvidenceLoader
from alpha.setup_discovery.feature_engine import FEATURE_VERSION, SetupFeatureEngine
from alpha.setup_discovery.lookback_engine import (
    LOOKBACK_VERSION,
    LookbackMismatchEvidenceEngine,
)
from alpha.setup_discovery.models import (
    CANONICAL_LOOKBACK,
    EXPANDED_LOOKBACKS,
    SDE_POLICY_ID,
    LookbackProofStatus,
    ResearchRecommendation,
    SetupDiscoveryManifest,
    SetupDiscoveryReport,
    SetupDiscoverySummary,
)


class SetupDiscoveryEvidenceEngine:
    """Explain missed setups without changing candidate or production policy."""

    def run(
        self,
        *,
        store: LegacyMarketDataStore,
        candidate_directory: Path | str = DEFAULT_CANDIDATE_RESEARCH_OUTPUT,
        generated_at: datetime | None = None,
    ) -> SetupDiscoveryReport:
        loader = CandidateResearchEvidenceLoader()
        cases = loader.load_cases(directory=candidate_directory)
        features = SetupFeatureEngine().extract(store=store, cases=cases)
        unsupported_count = sum(
            item.failure_reason == "SETUP_FAMILY_NOT_SUPPORTED" for item in cases
        )
        cluster_result = UnsupportedSetupClusterEngine().cluster(
            features,
            unsupported_population=unsupported_count,
        )
        lookbacks = LookbackMismatchEvidenceEngine().evaluate(store=store, cases=cases)
        vocabulary = SetupVocabularyEngine()
        catalog = vocabulary.catalog(cluster_result.clusters)
        recommendations = vocabulary.recommendations(catalog)
        top = MissedOpportunityRankingEngine().rank(
            records=features,
            clusters=cluster_result.clusters,
            case_cluster=cluster_result.case_cluster,
            lookbacks=lookbacks,
        )
        case_by_id = {item.case_id: item for item in cases}
        chart_case_ids = representative_chart_case_ids(cluster_result.clusters, top)
        chart_cases = tuple(
            case_by_id[case_id] for case_id in chart_case_ids if case_id in case_by_id
        )
        charts = SetupFeatureEngine().charts(store=store, cases=chart_cases)
        page_by_case = _page_mapping(cluster_result.clusters, top)
        clusters = with_representative_pages(cluster_result.clusters, page_by_case)
        largest = top_three_clusters(clusters)
        clustered_count = sum(item.occurrences for item in clusters)
        claimed_count = sum(
            item.failure_reason == "LOOKBACK_MISMATCH" for item in cases
        )
        confirmed_count = sum(
            item.status is LookbackProofStatus.CONFIRMED for item in lookbacks
        )
        insufficient_count = sum(
            item.status is LookbackProofStatus.DATA_INSUFFICIENT for item in lookbacks
        )
        not_to_add = tuple(
            item.family_name
            for item in recommendations
            if item.recommendation is ResearchRecommendation.DO_NOT_INTRODUCE
        )
        feature_coverage = (
            Decimal("0") if not cases else Decimal(len(features)) / Decimal(len(cases))
        )
        summary = SetupDiscoverySummary(
            unsupported_cases=unsupported_count,
            unsupported_cases_clustered=clustered_count,
            unsupported_cases_unclustered=unsupported_count - clustered_count,
            lookback_cases_claimed=claimed_count,
            lookback_cases_confirmed=confirmed_count,
            lookback_cases_rejected=len(lookbacks) - confirmed_count,
            lookback_cases_data_insufficient=insufficient_count,
            clusters_selected=cluster_result.selected_k,
            top_three_clusters=tuple(item.family_name for item in largest),
            top_three_case_share=sum(
                (item.unsupported_case_share for item in largest), Decimal("0")
            ),
            strongest_research_family=strongest_research_family(catalog),
            families_not_to_add=not_to_add,
            overall_evidence_confidence=_overall_confidence(
                feature_coverage=feature_coverage,
                clusters=clusters,
            ),
        )
        source_audit = loader.source_audit_id(candidate_directory)
        dataset = store.manifest()
        manifest = SetupDiscoveryManifest(
            policy_id=SDE_POLICY_ID,
            parent_policy_id="ALPHA_CANONICAL_v1.0",
            source_audit_id=source_audit,
            dataset_version=(
                f"{dataset.dataset_version}|{dataset.first_session}|"
                f"{dataset.last_session}|rows={dataset.rows}"
            ),
            feature_version=FEATURE_VERSION,
            clustering_version=CLUSTERING_VERSION,
            lookback_version=LOOKBACK_VERSION,
            canonical_lookback=CANONICAL_LOOKBACK,
            expanded_lookbacks=EXPANDED_LOOKBACKS,
            cluster_bounds=(8, 15),
            outcomes_excluded_from_clustering=True,
        )
        kalyan = render_symbol_deep_dive(
            symbol="KALYANKJIL",
            timeline=loader.symbol_timeline(
                "KALYANKJIL", directory=candidate_directory
            ),
            lookbacks=lookbacks,
        )
        pcjeweller = render_symbol_deep_dive(
            symbol="PCJEWELLER",
            timeline=loader.symbol_timeline(
                "PCJEWELLER", directory=candidate_directory
            ),
            lookbacks=lookbacks,
        )
        generated = generated_at or datetime.now(tz=UTC)
        report_id = (
            f"SDE-1|{source_audit}|{dataset.first_session}|{dataset.last_session}"
        )
        return SetupDiscoveryReport(
            report_id=report_id,
            generated_at=generated,
            manifest=manifest,
            features=features,
            clusters=clusters,
            lookback_evidence=lookbacks,
            top_opportunities=top,
            charts=charts,
            catalog=catalog,
            recommendations=recommendations,
            kalyan_deep_dive=kalyan,
            pcjeweller_deep_dive=pcjeweller,
            summary=summary,
        )


def _page_mapping(
    clusters: tuple[object, ...], top: tuple[object, ...]
) -> dict[str, int]:
    mapping = {
        str(getattr(item, "case_id")): int(getattr(item, "evidence_book_page"))
        for item in top
    }
    next_page = len(top) + 2
    for cluster in clusters:
        for case_id in getattr(cluster, "representative_case_ids"):
            if case_id not in mapping:
                mapping[case_id] = next_page
                next_page += 1
    return mapping


def _overall_confidence(
    *, feature_coverage: Decimal, clusters: tuple[object, ...]
) -> str:
    high_confidence = sum(
        getattr(item, "distinct_archetype_confidence") >= Decimal("0.60")
        for item in clusters
    )
    if feature_coverage >= Decimal("0.98") and high_confidence >= len(clusters) // 2:
        return "HIGH"
    if feature_coverage >= Decimal("0.90"):
        return "MODERATE"
    return "LOW"


__all__ = ["SetupDiscoveryEvidenceEngine"]
