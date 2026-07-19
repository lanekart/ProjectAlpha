from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from types import MappingProxyType
from typing import Any

from alpha.benchmark_replay.provenance import file_hash
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.market_opportunity_truth.comparison import (
    AlphaOpportunityComparisonEngine,
)
from alpha.market_opportunity_truth.market_supply import (
    OpportunityLifecycleEngine,
    assemble_market_opportunities,
    market_supply_summary,
)
from alpha.market_opportunity_truth.models import (
    BASELINE_ID,
    CLUSTER_POLICY_VERSION,
    COMPARISON_POLICY_VERSION,
    MOTA_VERSION,
    QUALITY_POLICY_VERSION,
    MarketOpportunityTruthReport,
    MOTAManifest,
)
from alpha.market_opportunity_truth.onset_detection import PointInTimeOnsetEngine
from alpha.market_opportunity_truth.opportunity_calendar import (
    build_opportunity_calendar,
)
from alpha.market_opportunity_truth.opportunity_clusters import cluster_summaries
from alpha.market_opportunity_truth.opportunity_density import (
    build_opportunity_density,
)
from alpha.market_opportunity_truth.opportunity_population import (
    DEFAULT_ACU_OUTPUT,
    DEFAULT_BENCHMARK_OUTPUT,
    DEFAULT_FEATURE_OUTPUT,
    OpportunityPopulationLoader,
)
from alpha.market_opportunity_truth.opportunity_quality import quality_distribution


class MarketOpportunityTruthEngine:
    """Build MOTA from a frozen causal population and later outcome evidence."""

    def run(
        self,
        *,
        store: LegacyMarketDataStore,
        feature_output: Path | str = DEFAULT_FEATURE_OUTPUT,
        benchmark_output: Path | str = DEFAULT_BENCHMARK_OUTPUT,
        acu_output: Path | str = DEFAULT_ACU_OUTPUT,
        matching_window_sessions: int = 5,
    ) -> MarketOpportunityTruthReport:
        feature_root = Path(feature_output)
        benchmark_root = Path(benchmark_output)
        acu_root = Path(acu_output)
        evidence = OpportunityPopulationLoader().load(
            feature_output=feature_root,
            benchmark_output=benchmark_root,
            acu_output=acu_root,
        )
        _validate_candidate_population(
            benchmark_root / "candidate_statistics.csv",
            acu_root / "candidate_rankings.csv",
        )
        baseline = dict(evidence.baseline_manifest)
        feature = dict(evidence.feature_manifest)
        start = _date_text(baseline, "replay_start")
        end = _date_text(baseline, "replay_end")
        sessions = store.trade_dates(start=start, end=end)
        if len(sessions) != int(baseline.get("sessions", -1)):
            raise ValueError("MOTA session population does not match CABR")
        seeds = PointInTimeOnsetEngine().classify(evidence.onsets)
        lifecycles = OpportunityLifecycleEngine().evaluate(
            store=store,
            seeds=seeds,
            outcome_labels_path=feature_root / "outcome_labels.csv",
        )
        opportunities = assemble_market_opportunities(seeds, lifecycles)
        calendar = build_opportunity_calendar(opportunities, sessions=sessions)
        density = build_opportunity_density(opportunities, sessions=sessions)
        alpha_comparison, capture = AlphaOpportunityComparisonEngine().compare(
            opportunities=opportunities,
            sessions=sessions,
            candidate_rankings_path=acu_root / "candidate_rankings.csv",
            trade_log_path=benchmark_root / "trade_log.csv",
            matching_window_sessions=matching_window_sessions,
        )
        monthly_counts = tuple(
            (item.month, item.opportunities, item.institutional_quality)
            for item in calendar
        )
        versions = _mapping(baseline, "versions")
        source_hashes = dict(evidence.source_hashes)
        source_hashes["warehouse_identity"] = str(versions.get("warehouse_hash", ""))
        manifest = MOTAManifest(
            audit_version=MOTA_VERSION,
            baseline_id=BASELINE_ID,
            baseline_manifest_hash=file_hash(benchmark_root / "manifest.json"),
            source_commit=_required(feature, "source_commit"),
            warehouse_version=_required(versions, "warehouse_version"),
            candidate_version=_required(versions, "candidate_generation_version"),
            feature_version=_required(versions, "feature_version"),
            opportunity_definition_version=(
                "pre-association-point-in-time-tradable-onset-v1.0"
            ),
            quality_policy_version=QUALITY_POLICY_VERSION,
            cluster_policy_version=CLUSTER_POLICY_VERSION,
            comparison_policy_version=COMPARISON_POLICY_VERSION,
            horizon_sessions=120,
            matching_window_sessions=matching_window_sessions,
            source_hashes=MappingProxyType(source_hashes),
        )
        return MarketOpportunityTruthReport(
            manifest=manifest,
            opportunities=opportunities,
            calendar=calendar,
            density=density,
            quality_distribution=quality_distribution(opportunities),
            clusters=cluster_summaries(opportunities),
            alpha_comparison=alpha_comparison,
            capture_statistics=capture,
            supply_summary=market_supply_summary(
                opportunities,
                monthly_counts=monthly_counts,
            ),
        )


def _validate_candidate_population(statistics_path: Path, rankings_path: Path) -> None:
    technical = 0
    with statistics_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            technical += int(row["technical_candidates"])
    with rankings_path.open(newline="", encoding="utf-8") as handle:
        ranked = sum(1 for _ in csv.DictReader(handle))
    if technical != ranked:
        raise ValueError("MOTA Alpha ranking population is incomplete")


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"MOTA manifest field must be an object: {key}")
    return {str(item_key): item for item_key, item in value.items()}


def _required(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"MOTA manifest field is unavailable: {key}")
    return str(value)


def _date_text(payload: dict[str, Any], key: str) -> date:
    return date.fromisoformat(_required(payload, key))


__all__ = ["MarketOpportunityTruthEngine"]
