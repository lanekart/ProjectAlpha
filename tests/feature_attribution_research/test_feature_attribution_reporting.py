from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
from typer.testing import CliRunner

from alpha.application.feature_attribution_cli import feature_attribution_app
from alpha.feature_attribution_research.exports import FeatureAttributionExporter
from alpha.feature_attribution_research.feature_registry import FeatureRegistry
from alpha.feature_attribution_research.missingness import MissingInformationAudit
from alpha.feature_attribution_research.models import (
    AttributionDirection,
    AttributionResult,
    EvidencePartition,
    FeatureAttributionManifest,
    FeatureAttributionReport,
    FeatureConfidenceTier,
    FeatureQualityFlag,
    FeatureQualityRecord,
    FeatureSnapshot,
    FeatureStabilityScore,
    InformationDecayResult,
    OrthogonalEdgeResult,
    PartitionManifest,
    ResearchConclusion,
    ResearchPopulationSummary,
    StabilityClassification,
    TransactionCostPolicy,
)
from alpha.feature_attribution_research.rankings import FeatureRankingEngine
from alpha.feature_attribution_research.rendering import (
    render_feature_cards,
    render_report,
)
from alpha.feature_attribution_research.research_integration import (
    research_diagnostic_plugins,
)
from alpha.feature_attribution_research.stability import InformationDecayEngine


def test_rankings_produce_confidence_tiers_and_twenty_horizon_cards() -> None:
    definition = FeatureRegistry().get("ema20_slope")
    quality = (_quality("ema20_slope"),)
    univariate = tuple(
        _attribution("ema20_slope", partition, Decimal("0.70"))
        for partition in (None, *EvidencePartition)
    )
    stability = (
        FeatureStabilityScore(
            feature_id="ema20_slope",
            direction_stability=Decimal("1"),
            support_stability=Decimal("0.9"),
            era_stability=Decimal("0.8"),
            regime_stability=None,
            sector_stability=None,
            liquidity_stability=Decimal("0.8"),
            overall_stability=Decimal("0.875"),
            classification=StabilityClassification.STABLE_POSITIVE,
            unavailable_dimensions=("regime_stability", "sector_stability"),
        ),
    )
    orthogonal = (
        OrthogonalEdgeResult(
            feature_id="ema20_slope",
            model_name="scorecard",
            development_auc=Decimal("0.70"),
            validation_auc=Decimal("0.68"),
            holdout_auc=Decimal("0.67"),
            development_brier=Decimal("0.20"),
            validation_brier=Decimal("0.21"),
            holdout_brier=Decimal("0.22"),
            incremental_auc=Decimal("0.03"),
            incremental_brier_improvement=Decimal("0.01"),
            calibration_slope=Decimal("0.9"),
            feature_sign_stability=True,
            sample_count=300,
        ),
    )
    decay = tuple(
        InformationDecayResult(
            feature_id="ema20_slope",
            horizon=horizon,
            outcome_id=f"POSITIVE_AFTER_COSTS_{horizon}D",
            sample_count=300,
            auc=Decimal(str(0.72 - horizon / 1_000)),
            effect=Decimal("0.5"),
            direction=AttributionDirection.POSITIVE,
        )
        for horizon in (20, 60, 120)
    )

    rankings, cards = FeatureRankingEngine().build(
        definitions=(definition,),
        quality=quality,
        leakage=(),
        univariate=univariate,
        redundancy=(),
        orthogonal=orthogonal,
        stability=stability,
        information_decay=decay,
    )

    assert len(rankings) == 6
    assert cards[0].confidence_tier is FeatureConfidenceTier.A
    assert cards[0].conclusion is ResearchConclusion.FEATURE_HAS_STABLE_EDGE
    assert tuple(item[0] for item in cards[0].information_decay) == (20, 60, 120)
    rendered = render_feature_cards(cards)
    assert "# Top 20 Feature Cards" in rendered
    assert "Holdout AUC: 0.7000" in rendered
    assert "Recommendation: Retain for further validation" in rendered


def test_information_decay_uses_only_preregistered_horizon_outcomes() -> None:
    values = tuple(
        _attribution(
            "ema20_slope",
            None,
            Decimal("0.6"),
            outcome=f"POSITIVE_AFTER_COSTS_{horizon}D",
        )
        for horizon in (20, 60, 120)
    ) + (_attribution("ema20_slope", None, Decimal("0.7")),)

    decay = InformationDecayEngine().analyze(values)

    assert tuple(item.horizon for item in decay) == (20, 60, 120)


def test_missing_information_audit_prioritizes_orthogonal_gaps() -> None:
    rows = MissingInformationAudit().audit()
    priorities = tuple(item for item in rows if item.priority is not None)

    assert len(priorities) == 3
    assert tuple(item.priority for item in priorities) == (1, 2, 3)
    assert all(item.current_source is None for item in priorities)


def test_exports_cli_and_ird_integration_are_deterministic(
    tmp_path: Path, monkeypatch: object
) -> None:
    report = _report()
    output = tmp_path / "feature-attribution"
    paths = FeatureAttributionExporter().export(report, output_directory=output)
    first_manifest = (output / "manifest.json").read_text(encoding="utf-8")
    FeatureAttributionExporter().export(report, output_directory=output)

    assert (output / "research_population.csv") in paths
    assert (output / "feature_snapshots.parquet") in paths
    assert (output / "top20_feature_cards.md") in paths
    assert first_manifest == (output / "manifest.json").read_text(encoding="utf-8")
    assert len(pd.read_parquet(output / "feature_snapshots.parquet")) == 1
    manifest = json.loads(first_manifest)
    assert manifest["transaction_cost_policy"]["round_trip_rate"] == "0.002"
    assert manifest["guardrails"]["PRODUCTION_INFLUENCE"] is False

    runner = CliRunner()
    result = runner.invoke(
        feature_attribution_app, ["population", "--output", str(output)]
    )
    assert result.exit_code == 0
    assert "All Market Opportunities: 1" in result.stdout
    assert "Costs Used: 0.20%" in result.stdout

    import alpha.feature_attribution_research.research_integration as integration

    # pytest's monkeypatch fixture is deliberately duck-typed here to keep mypy
    # focused on production modules.
    monkeypatch.setattr(  # type: ignore[attr-defined]
        integration, "DEFAULT_FEATURE_ATTRIBUTION_OUTPUT", output
    )
    evidence = research_diagnostic_plugins()[0].collect()
    assert evidence.production_influence is False
    assert evidence.state.value == "AVAILABLE"
    assert any(
        item.metric_id == "feature_attribution.population" and item.value == 1
        for item in evidence.metrics
    )


def test_executive_report_states_constraints_and_cost_policy() -> None:
    text = render_report(_report())

    assert "Production Influence: false" in text
    assert "Costs Used: 0.20%" in text
    assert "Relative strength is blocked" in text
    assert "No production weights, thresholds, setups, approvals, or policies" in text


def _report() -> FeatureAttributionReport:
    observed_on = date(2024, 1, 2)
    manifest = FeatureAttributionManifest(
        research_id="research-test",
        generated_at=datetime(2024, 1, 3, tzinfo=UTC),
        source_commit="abc123",
        dataset_version="TEST",
        canonical_policy_id="ALPHA_CANONICAL_v1.0",
        candidate_research_version="candidate-test",
        setup_discovery_version="sde-test",
        feature_engine_version="feature-test",
        outcome_definition_version="outcome-test",
        transaction_cost_policy=TransactionCostPolicy(),
        partition_manifest=PartitionManifest(
            development_start=date(2020, 1, 1),
            development_end=date(2021, 12, 31),
            validation_start=date(2022, 1, 1),
            validation_end=date(2022, 12, 31),
            holdout_start=date(2023, 1, 1),
            holdout_end=date(2024, 12, 31),
        ),
        source_artifact_hashes=(("source.csv", "hash"),),
    )
    snapshot = FeatureSnapshot(
        onset_id="onset-1",
        symbol="ABC",
        onset_date=observed_on,
        partition=EvidencePartition.HOLDOUT,
        values=(("ema20_slope", 0.1),),
        source_max_date=observed_on,
        feature_snapshot_hash="snapshot-hash",
    )
    return FeatureAttributionReport(
        manifest=manifest,
        population=(),
        population_summary=ResearchPopulationSummary(
            raw_linked_onsets=2,
            deduplicated_linked_onsets=1,
            reconstructed_market_opportunities=1,
            labelled_market_opportunities=1,
            cohort_counts=(("ALL_MARKET_OPPORTUNITIES", 1),),
            selection_bias_warning="Linked rows are hindsight-conditioned.",
        ),
        feature_definitions=(FeatureRegistry().get("ema20_slope"),),
        feature_snapshots=(snapshot,),
        outcome_definitions=(),
        outcomes=(),
        quality=(_quality("ema20_slope"),),
        leakage=(),
        univariate=(),
        negative_features=(),
        conditional=(),
        redundancy=(),
        interactions=(),
        orthogonal=(),
        information_decay=(),
        stability=(),
        rankings=(),
        missing_information=(),
        feature_cards=(),
        case_studies=(),
    )


def _quality(feature_id: str) -> FeatureQualityRecord:
    return FeatureQualityRecord(
        feature_id=feature_id,
        population_count=300,
        available_count=300,
        missing_count=0,
        missing_rate=Decimal("0"),
        unique_values=300,
        zero_variance=False,
        outlier_rate=Decimal("0"),
        minimum=Decimal("0"),
        maximum=Decimal("1"),
        median=Decimal("0.5"),
        iqr=Decimal("0.5"),
        development_coverage=Decimal("1"),
        validation_coverage=Decimal("1"),
        holdout_coverage=Decimal("1"),
        flags=(FeatureQualityFlag.PASS,),
    )


def _attribution(
    feature_id: str,
    partition: EvidencePartition | None,
    auc: Decimal,
    *,
    outcome: str = "TARGET_BEFORE_STOP",
) -> AttributionResult:
    return AttributionResult(
        feature_id=feature_id,
        outcome_id=outcome,
        partition=partition,
        horizon=120,
        sample_count=300,
        missing_count=0,
        winner_median=Decimal("0.7"),
        loser_median=Decimal("0.3"),
        median_difference=Decimal("0.4"),
        standardized_effect_size=Decimal("0.8"),
        rank_biserial_correlation=Decimal("0.4"),
        auc=auc,
        monotonicity_score=Decimal("0.9"),
        bootstrap_low=auc - Decimal("0.04"),
        bootstrap_high=auc + Decimal("0.04"),
        direction=AttributionDirection.POSITIVE,
        deciles=(),
    )
