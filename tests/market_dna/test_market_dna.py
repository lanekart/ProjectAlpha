from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.cli import app
from alpha.market_dna.cluster_discovery import ClusterDiscovery
from alpha.market_dna.cohort_builder import CohortBuilder
from alpha.market_dna.distribution_analysis import DistributionAnalysis
from alpha.market_dna.dna_matcher import ResearchDNAMatcher
from alpha.market_dna.dna_registry import DNARegistry
from alpha.market_dna.effect_size_engine import EffectSizeEngine
from alpha.market_dna.feature_enrichment import FeatureQualityAuditEngine
from alpha.market_dna.feature_manifest import MarketDNAFeatureManifest
from alpha.market_dna.hypothesis_generator import HypothesisGenerator
from alpha.market_dna.interaction_discovery import InteractionDiscovery
from alpha.market_dna.lineage_analysis import LineageAnalysis
from alpha.market_dna.matched_cohort import MatchedCohortEngine
from alpha.market_dna.models import (
    PRODUCTION_INFLUENCE,
    ConditionOperator,
    DNADiscoveryReport,
    DNAEvidenceClass,
    DNAPatternStatus,
    FeatureCondition,
    FeatureFinding,
    FeatureQuality,
    FeatureSnapshot,
    MarketDNAConclusion,
)
from alpha.market_dna.multiple_testing_control import FalseDiscoveryControl
from alpha.market_dna.outcome_cohort_registry import OutcomeCohortRegistry
from alpha.market_dna.rendering import render_report
from alpha.market_dna.research_integration import research_diagnostic_plugins
from alpha.market_dna.service import MarketDNARequest, MarketDNAService
from alpha.market_dna.stability_analysis import StabilityAnalysis
from alpha.market_dna.strategy_lab_bridge import StrategyLabBridge
from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.strategy_discovery.models import (
    DiscoveryDataset,
    DiscoveryRow,
    HistoricalTruthClass,
)


class StubDNADataSource:
    def __init__(self, dataset: DiscoveryDataset) -> None:
        self.dataset = dataset

    def discovery_dataset(self) -> DiscoveryDataset:
        return self.dataset


def test_outcome_cohort_registry_is_explicit_and_versioned() -> None:
    definitions = OutcomeCohortRegistry().definitions

    assert len(definitions) == 16
    assert all(item.predicate and item.version for item in definitions)
    assert OutcomeCohortRegistry().require("strong-winners").cohort_id == (
        "STRONG_WINNERS"
    )


def test_cohort_construction_uses_net_return_and_explicit_cost() -> None:
    snapshots = (
        _snapshot(1, Decimal("20")),
        _snapshot(2, Decimal("19.99")),
        _snapshot(3, Decimal("-25")),
    )
    registry = OutcomeCohortRegistry()

    strong = CohortBuilder().build(registry.require("STRONG_WINNERS"), snapshots)
    catastrophic = CohortBuilder().build(
        registry.require("CATASTROPHIC_LOSERS"), snapshots
    )

    assert strong.candidate_ids == ("candidate-1",)
    assert catastrophic.candidate_ids == ("candidate-3",)
    assert strong.definition.predicate == "net_return_pct >= 20"


def test_point_in_time_snapshot_rejects_future_feature_timestamp() -> None:
    with pytest.raises(ValueError, match="follows the decision"):
        _snapshot(
            1,
            Decimal("5"),
            feature_timestamp=datetime(2024, 1, 3, tzinfo=UTC),
            candidate_timestamp=datetime(2024, 1, 2, tzinfo=UTC),
        )


def test_manifest_quarantines_leakage_and_invalid_context_features() -> None:
    manifest = MarketDNAFeatureManifest()
    by_name = {item.feature_id: item for item in manifest.definitions}

    quarantined = (
        "realised_return_pct",
        "mfe_pct",
        "mae_pct",
        "market_regime",
        "sector",
    )
    for name in quarantined:
        assert by_name[name].base_quality is FeatureQuality.QUARANTINED
        assert not by_name[name].discovery_permitted
    assert "realised_return_pct" not in {
        item.feature_id for item in manifest.discovery_features
    }


def test_feature_quality_flags_scale_and_missingness() -> None:
    manifest = MarketDNAFeatureManifest()
    snapshots = tuple(
        _snapshot(
            index,
            Decimal("5"),
            features={
                "strategy_score": "120" if index == 0 else "60",
                "reward_risk": "unavailable" if index < 6 else "2",
            },
        )
        for index in range(10)
    )
    audits = FeatureQualityAuditEngine().audit(manifest.definitions, snapshots)
    by_name = {item.feature.feature_id: item for item in audits}

    assert by_name["strategy_score"].quality is FeatureQuality.UNSTABLE
    assert by_name["reward_risk"].quality is FeatureQuality.INSUFFICIENT_COVERAGE
    assert by_name["reward_risk"].missing_count == 6


def test_effect_size_enrichment_and_circular_feature_exclusion() -> None:
    snapshots = tuple(
        _snapshot(
            index,
            Decimal("25") if index < 20 else Decimal("-5"),
            approved=index % 3 == 0,
            features={"confidence": "HIGH" if index < 20 or index < 25 else "LOW"},
        )
        for index in range(40)
    )
    manifest = MarketDNAFeatureManifest()
    audits = FeatureQualityAuditEngine().audit(manifest.definitions, snapshots)
    cohort = CohortBuilder().build(
        OutcomeCohortRegistry().require("STRONG_WINNERS"), snapshots
    )
    findings = EffectSizeEngine().evaluate(
        cohort=cohort,
        scope="UNIVERSAL",
        snapshots=snapshots,
        audits=audits,
    )
    high = next(
        item
        for item in findings
        if item.condition.canonical_key == "confidence|EQUAL|HIGH"
    )

    assert high.enrichment_ratio == Decimal("4.0000")
    assert high.risk_ratio == Decimal("4.0000")
    assert high.odds_ratio is not None and high.odds_ratio > Decimal("1")
    assert high.effect_size is not None and high.effect_size > Decimal("0")
    assert high.confidence_interval_low is not None

    rejected = CohortBuilder().build(
        OutcomeCohortRegistry().require("PROFITABLE_REJECTED"), snapshots
    )
    rejected_findings = EffectSizeEngine().evaluate(
        cohort=rejected,
        scope="UNIVERSAL",
        snapshots=snapshots,
        audits=audits,
    )
    assert "raw_approved" not in {
        item.condition.feature_id for item in rejected_findings
    }


def test_continuous_distribution_comparison_reports_effect() -> None:
    snapshots = tuple(
        _snapshot(
            index,
            Decimal("25") if index < 20 else Decimal("-5"),
            features={"strategy_score": "80" if index < 20 else "40"},
        )
        for index in range(40)
    )
    audits = FeatureQualityAuditEngine().audit(
        MarketDNAFeatureManifest().definitions, snapshots
    )
    comparisons = DistributionAnalysis().compare(
        cohort_id="STRONG_WINNERS",
        scope="UNIVERSAL",
        cohort_ids=frozenset(f"candidate-{index}" for index in range(20)),
        snapshots=snapshots,
        audits=audits,
    )
    score = next(item for item in comparisons if item.feature_id == "strategy_score")

    assert score.cohort_mean == Decimal("80.0000")
    assert score.baseline_mean == Decimal("40.0000")
    assert score.standardised_effect_size is not None


def test_matched_cohort_is_deterministic_and_reports_unmatched() -> None:
    snapshots = tuple(
        _snapshot(
            index,
            Decimal("25") if index < 10 else Decimal("-5"),
            setup="BREAKOUT" if index != 19 else "PULLBACK",
        )
        for index in range(20)
    )
    cohort = CohortBuilder().build(
        OutcomeCohortRegistry().require("STRONG_WINNERS"), snapshots
    )
    result = MatchedCohortEngine().match(cohort, snapshots)

    assert result.matched_pairs == 9
    assert result.unmatched_cohort == 1
    assert result.matching_dimensions == ("horizon", "setup", "calendar_year")


def test_interaction_search_is_bounded_and_enforces_minimum_cells() -> None:
    snapshots = tuple(
        _snapshot(
            index,
            Decimal("25") if index < 60 else Decimal("-5"),
            features={
                "confidence": "HIGH" if index % 2 == 0 else "MEDIUM",
                "data_quality": "COMPLETE" if index % 3 else "PARTIAL",
            },
        )
        for index in range(120)
    )
    audits = FeatureQualityAuditEngine().audit(
        MarketDNAFeatureManifest().definitions, snapshots
    )
    cohort = CohortBuilder().build(
        OutcomeCohortRegistry().require("STRONG_WINNERS"), snapshots
    )
    findings = EffectSizeEngine().evaluate(
        cohort=cohort,
        scope="UNIVERSAL",
        snapshots=snapshots,
        audits=audits,
    )
    interactions = InteractionDiscovery().discover(
        cohort=cohort,
        snapshots=snapshots,
        findings=findings,
        audits=audits,
        minimum_cell=5,
        maximum_interactions=3,
    )

    assert len(interactions) <= 3
    assert all(
        item.sample_size >= 5 and item.baseline_size >= 5 for item in interactions
    )


def test_cluster_assignments_do_not_use_outcomes() -> None:
    snapshots = tuple(
        _snapshot(
            index,
            Decimal("20") if index % 2 else Decimal("-20"),
            features={
                "strategy_score": str(20 + index % 60),
                "price_component": str(Decimal(index % 10) / Decimal("10")),
                "volume_component": str(Decimal(index % 8) / Decimal("8")),
                "candle_component": str(Decimal(index % 6) / Decimal("6")),
            },
        )
        for index in range(120)
    )
    reversed_outcomes = tuple(
        replace(item, net_return_pct=-item.net_return_pct) for item in snapshots
    )

    first = ClusterDiscovery().discover(snapshots)
    second = ClusterDiscovery().discover(reversed_outcomes)

    first_assignments = tuple(
        (item.cluster_id, item.sample_size, item.profile) for item in first
    )
    second_assignments = tuple(
        (item.cluster_id, item.sample_size, item.profile) for item in second
    )
    assert first_assignments == second_assignments


def test_false_discovery_control_is_monotonic_and_deterministic() -> None:
    findings = _sample_findings()
    modified = tuple(
        replace(item, raw_p_value=value)
        for item, value in zip(
            findings[:3],
            (Decimal("0.001"), Decimal("0.02"), Decimal("0.20")),
            strict=True,
        )
    )

    adjusted, summary = FalseDiscoveryControl().adjust_findings(modified)

    assert tuple(item.adjusted_p_value for item in adjusted) == (
        Decimal("0.003000"),
        Decimal("0.030000"),
        Decimal("0.200000"),
    )
    assert summary.surviving_findings == 2


def test_lineage_confounded_interaction_is_flagged() -> None:
    definitions = {
        item.feature_id: item for item in MarketDNAFeatureManifest().definitions
    }
    conditions = (
        FeatureCondition(
            "strategy_score", ConditionOperator.GREATER_THAN_OR_EQUAL, "60"
        ),
        FeatureCondition(
            "price_component", ConditionOperator.GREATER_THAN_OR_EQUAL, "0.55"
        ),
    )

    assert LineageAnalysis().interaction_is_confounded(conditions, definitions)


def test_temporal_stability_and_concentration_downgrade_pattern() -> None:
    snapshots = tuple(
        replace(
            _snapshot(
                year * 10 + index,
                Decimal("25") if index < 5 else Decimal("-5"),
                features={"confidence": "HIGH" if index < 7 else "LOW"},
                candidate_timestamp=datetime(2018 + year, 1, index + 1, tzinfo=UTC),
            ),
            symbol="ONE",
        )
        for year in range(6)
        for index in range(10)
    )
    audits = FeatureQualityAuditEngine().audit(
        MarketDNAFeatureManifest().definitions, snapshots
    )
    cohort = CohortBuilder().build(
        OutcomeCohortRegistry().require("STRONG_WINNERS"), snapshots
    )
    finding = next(
        item
        for item in EffectSizeEngine().evaluate(
            cohort=cohort,
            scope="UNIVERSAL",
            snapshots=snapshots,
            audits=audits,
        )
        if item.condition.canonical_key == "confidence|EQUAL|HIGH"
    )
    adjusted = replace(finding, adjusted_p_value=Decimal("0.001"))
    pattern = StabilityAnalysis().patterns(
        findings=(adjusted,), interactions=(), minimum_sample=5
    )[0]

    assert finding.fold_consistency_pct == Decimal("100.0000")
    assert finding.temporal_stability.value == "STABLE"
    assert finding.symbol_concentration_pct == Decimal("100.0000")
    assert pattern.status is DNAPatternStatus.CONCENTRATED


def test_pattern_status_hashing_hypothesis_and_matcher_are_deterministic(
    tmp_path: Path,
) -> None:
    report = _service_report(tmp_path)
    first_pattern = report.patterns[0]
    candidate = replace(
        first_pattern,
        status=DNAPatternStatus.STRATEGY_HYPOTHESIS_CANDIDATE,
        evidence_class=DNAEvidenceClass.AUTHORITATIVE,
        rejection_reasons=(),
    )
    hypothesis = HypothesisGenerator().generate((candidate,))[0]
    specification = StrategyLabBridge(tmp_path / "bridge.json").publish(hypothesis)
    match = ResearchDNAMatcher().match(candidate, _snapshot(1, Decimal("5")))

    assert hypothesis.originating_pattern_ids == (candidate.pattern_id,)
    assert specification.execute_automatically is False
    assert specification.production_influence is False
    assert match.production_influence is False
    bridge_payload = json.loads((tmp_path / "bridge.json").read_text())
    assert bridge_payload["execute_automatically"] is False


def test_registry_is_immutable_and_exports_json_csv(tmp_path: Path) -> None:
    report = _service_report(tmp_path)
    registry = DNARegistry(tmp_path / "registry-direct.json")

    assert registry.record(report)
    assert not registry.record(report)
    with pytest.raises(ValueError, match="immutable"):
        registry.record(replace(report, highest_value_evidence_gap="changed"))

    json_path = registry.export_json(tmp_path / "dna.json")
    csv_path = registry.export_csv(tmp_path / "dna.csv")
    assert '"production_influence": false' in json_path.read_text()
    assert "pattern_id" in csv_path.read_text()


def test_service_records_research_report_and_keeps_reconstructed_findings_inert(
    tmp_path: Path,
) -> None:
    report = _service_report(tmp_path)
    research = ResearchExperimentRegistry(tmp_path / "research.json").load()

    assert report.evidence_class is DNAEvidenceClass.RECONSTRUCTED
    assert report.final_conclusion == MarketDNAConclusion.NO_ROBUST_MARKET_DNA_FOUND
    assert not report.hypotheses
    assert all(item.production_influence is False for item in report.patterns)
    assert research and research[0].subsystem.value == "MARKET_DNA"


def test_rendering_cli_ird_and_production_isolation(tmp_path: Path) -> None:
    report = _service_report(tmp_path)
    rendered = "\n".join(render_report(report))
    runner = CliRunner()
    cli = runner.invoke(app, ["market-dna", "inventory"])
    plugin = research_diagnostic_plugins()[0]

    assert "Market DNA Discovery Report" in rendered
    assert "NO_ROBUST_MARKET_DNA_FOUND" in rendered
    assert "PRODUCTION_INFLUENCE=false" in rendered
    assert cli.exit_code == 0
    assert "Quarantined" in cli.stdout
    assert plugin.diagnostic_id == "market-dna-discovery"
    assert PRODUCTION_INFLUENCE is False
    with pytest.raises(ValueError, match="cannot influence production"):
        replace(report.patterns[0], production_influence=True)


def test_request_rejects_quarantined_sector_and_invalid_bounds() -> None:
    with pytest.raises(ValueError, match="sector is quarantined"):
        MarketDNARequest(sector="BANKING")
    with pytest.raises(ValueError, match="minimum sample"):
        MarketDNARequest(minimum_sample=4)
    with pytest.raises(ValueError, match="maximum interactions"):
        MarketDNARequest(maximum_interactions=501)


def _sample_findings() -> tuple[FeatureFinding, ...]:
    snapshots = tuple(
        _snapshot(index, Decimal("25") if index < 20 else Decimal("-5"))
        for index in range(40)
    )
    audits = FeatureQualityAuditEngine().audit(
        MarketDNAFeatureManifest().definitions, snapshots
    )
    cohort = CohortBuilder().build(
        OutcomeCohortRegistry().require("STRONG_WINNERS"), snapshots
    )
    return EffectSizeEngine().evaluate(
        cohort=cohort,
        scope="UNIVERSAL",
        snapshots=snapshots,
        audits=audits,
    )


def _service_report(tmp_path: Path) -> DNADiscoveryReport:
    service = MarketDNAService(
        data_source=StubDNADataSource(_dataset()),
        registry=DNARegistry(tmp_path / "registry.json"),
        research_registry=ResearchExperimentRegistry(tmp_path / "research.json"),
    )
    return service.report(MarketDNARequest(minimum_sample=5, maximum_interactions=10))


def _dataset() -> DiscoveryDataset:
    start = datetime(2017, 1, 2, tzinfo=UTC)
    rows = tuple(
        _row(
            index,
            start + timedelta(days=index * 30),
            (
                Decimal("25")
                if index % 4 == 0
                else Decimal("12")
                if index % 4 == 1
                else Decimal("-30")
                if index % 4 == 2
                else Decimal("-5")
            ),
        )
        for index in range(120)
    )
    return DiscoveryDataset(
        dataset_version="market-dna-test-reconstructed-v1",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        source="test",
        source_hash="test-source",
        population_class=HistoricalTruthClass.RECONSTRUCTED,
        rows=rows,
        exclusions=(),
        quarantined_population=0,
    )


def _row(index: int, timestamp: datetime, realised_return: Decimal) -> DiscoveryRow:
    values = _features(index)
    return DiscoveryRow(
        candidate_id=f"candidate-{index}",
        candidate_timestamp=timestamp,
        symbol=f"SYM{index % 8}",
        series="EQ",
        identity_status="UNVERIFIED",
        feature_timestamp=timestamp,
        recommendation="BUY" if index % 3 == 0 else "AVOID",
        setup="BREAKOUT" if index % 2 == 0 else "PULLBACK",
        entry_timing_state="BUY" if index % 3 == 0 else "AVOID",
        approval_gate_states={"raw": index % 3 == 0},
        entry_zone_low=Decimal("98"),
        entry_zone_high=Decimal("100"),
        confirmation_entry=Decimal("100"),
        stop_loss=Decimal("90"),
        target_1=Decimal("120"),
        target_2=Decimal("130"),
        target_3=Decimal("140"),
        outcome_horizon="20d",
        realised_outcome=(
            "WOULD_HAVE_WON" if realised_return > 0 else "WOULD_HAVE_LOST"
        ),
        mfe_pct=max(Decimal("5"), realised_return),
        mae_pct=min(Decimal("-5"), realised_return),
        realised_return_pct=realised_return,
        realised_r_multiple=realised_return / Decimal("10"),
        evidence_provenance={"source": "test"},
        replay_version="test-v1",
        data_quality_status="COMPLETE",
        corporate_action_status="UNAVAILABLE_NOT_LINKED",
        truth_class=HistoricalTruthClass.RECONSTRUCTED,
        features=values,
    )


def _snapshot(
    index: int,
    net_return: Decimal,
    *,
    features: dict[str, str] | None = None,
    approved: bool = False,
    setup: str = "BREAKOUT",
    candidate_timestamp: datetime | None = None,
    feature_timestamp: datetime | None = None,
) -> FeatureSnapshot:
    timestamp = candidate_timestamp or datetime(2024, 1, 1, tzinfo=UTC) + timedelta(
        days=index
    )
    values = _features(index)
    values.update(features or {})
    values["raw_approved"] = "true" if approved else "false"
    return FeatureSnapshot(
        candidate_id=f"candidate-{index}",
        candidate_timestamp=timestamp,
        feature_timestamp=feature_timestamp or timestamp,
        symbol=f"SYM{index % 8}",
        setup=setup,
        horizon="20d",
        evidence_class=DNAEvidenceClass.RECONSTRUCTED,
        corporate_action_status="UNAVAILABLE_NOT_LINKED",
        feature_values=values,
        realised_outcome=("WOULD_HAVE_WON" if net_return > 0 else "WOULD_HAVE_LOST"),
        gross_return_pct=net_return + Decimal("0.30"),
        net_return_pct=net_return,
        realised_r_multiple=net_return / Decimal("10"),
        mfe_pct=max(Decimal("5"), net_return),
        mae_pct=min(Decimal("-5"), net_return),
        target_1_touched=net_return >= Decimal("20"),
        stop_touched=net_return <= Decimal("-10"),
        raw_approved=approved,
        entry_missed_proxy=not approved,
    )


def _features(index: int) -> dict[str, str]:
    return {
        "strategy_score": str(40 + index % 50),
        "final_verdict": "BUY" if index % 3 == 0 else "AVOID",
        "raw_approved": "true" if index % 3 == 0 else "false",
        "confidence": "HIGH" if index % 2 == 0 else "MEDIUM",
        "data_quality": "COMPLETE" if index % 3 else "PARTIAL",
        "setup_type": "BREAKOUT" if index % 2 == 0 else "PULLBACK",
        "entry_timing_state": "BUY" if index % 3 == 0 else "AVOID",
        "long_trade_permission": "true" if index % 4 else "false",
        "complete_trade_plan": "true",
        "entry_price": "100",
        "stop_distance_pct": str(5 + index % 8),
        "reward_risk": str(Decimal("1.5") + Decimal(index % 4) / Decimal("2")),
        "price_component": str(Decimal("0.4") + Decimal(index % 5) / Decimal("10")),
        "volume_component": str(Decimal("0.4") + Decimal(index % 4) / Decimal("10")),
        "candle_component": str(Decimal("0.4") + Decimal(index % 3) / Decimal("10")),
    }
