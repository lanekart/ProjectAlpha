from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from alpha.adaptive_weights.confidence_engine import ContributionConfidenceEngine
from alpha.adaptive_weights.evidence_builder import (
    export_evidence_csv,
    export_evidence_json,
    load_evidence,
)
from alpha.adaptive_weights.marginal_contribution import MarginalContributionEngine
from alpha.adaptive_weights.models import AlphaComponent, EvidencePartition
from alpha.adaptive_weights.overlap_analysis import IndicatorOverlapEngine
from alpha.adaptive_weights.policy_registry import (
    CandidateWeightPolicyFactory,
    CandidateWeightPolicyRegistry,
)
from alpha.adaptive_weights.proposal_engine import AdaptiveWeightProposalEngine
from alpha.adaptive_weights.research_integration import (
    record_adaptive_weight_experiment,
    research_diagnostic_plugins,
)
from alpha.adaptive_weights.stability_analysis import ContributionStabilityEngine
from alpha.cli import app
from alpha.research.models import ResearchSubsystem
from alpha.research.research_registry import ResearchExperimentRegistry
from alpha.tradingview_research.weight_evidence import (
    TradingViewStrategyTesterImporter,
    TradingViewWeightEvidenceAdapter,
    frozen_weight_presets,
)
from tests.adaptive_weights.helpers import completed_evidence


def test_tradingview_csv_import_creates_matched_retracement_ablation(tmp_path) -> None:
    csv_path = tmp_path / "strategy_tester.csv"
    csv_path.write_text(
        "role,partition,symbol,sector,period_start,period_end,total_closed_trades,"
        "percent_profitable,profit_factor,expectancy_r,max_drawdown_pct,"
        "net_profit_pct,average_winner_r,average_loser_r,average_bars_in_trades\n"
        "ALPHA_BASELINE,HOLDOUT,ABC,TECH,2020-01-01,2024-12-31,50,55,1.3,"
        "0.20,8,15,1.5,-1,12\n"
        "TREATMENT,HOLDOUT,ABC,TECH,2020-01-01,2024-12-31,50,52,1.1,"
        "0.05,9,10,1.4,-1,11\n",
        encoding="utf-8",
    )
    presets = {item.name: item for item in frozen_weight_presets()}
    experiment = TradingViewStrategyTesterImporter().import_csv(
        csv_path,
        research_id="TRL-WEIGHT-001",
        baseline=presets["ALPHA_CANONICAL"],
        treatment=presets["NO_RETRACEMENT"],
    )
    evidence = TradingViewWeightEvidenceAdapter().to_matched_ablation(experiment)
    assert len(evidence) == 2
    assert {item.component for item in evidence} == {AlphaComponent.RETRACEMENT}
    assert {item.research_id for item in evidence} == {"TRL-WEIGHT-001"}


def test_evidence_json_and_csv_round_trip(tmp_path) -> None:
    evidence = tuple(completed_evidence(index) for index in range(3))
    json_path = tmp_path / "evidence.json"
    csv_path = tmp_path / "evidence.csv"
    export_evidence_json(evidence, json_path)
    export_evidence_csv(evidence, csv_path)
    assert load_evidence(json_path) == evidence
    assert load_evidence(csv_path) == evidence


def test_ird_registration_retains_adaptive_weight_metrics(tmp_path) -> None:
    evidence = tuple(
        completed_evidence(index, partition=tuple(EvidencePartition)[index % 4])
        for index in range(40)
    )
    contributions = MarginalContributionEngine().analyze(evidence)
    stabilities = ContributionStabilityEngine().analyze(evidence, contributions)
    confidences = ContributionConfidenceEngine(
        minimum_total_samples=10,
        minimum_holdout_samples=5,
        minimum_forward_samples=5,
    ).assess(evidence, contributions, stabilities)
    overlaps = IndicatorOverlapEngine().analyze(evidence)
    proposal = AdaptiveWeightProposalEngine().propose(
        contributions,
        stabilities,
        confidences,
        overlaps,
        evidence_count=len(evidence),
    )
    policy = CandidateWeightPolicyFactory().create(
        proposal,
        policy_id="ALPHA_WEIGHT_RESEARCH_0001",
        parent_policy="ALPHA_CANONICAL",
        conditional_weights=(),
        evidence_window="2020-01-01..2020-02-09",
        dataset_version="FIXTURE-DATA-V1",
        created_at=datetime(2025, 1, 1, tzinfo=UTC),
    )
    registry = ResearchExperimentRegistry(tmp_path / "research.json")
    assert record_adaptive_weight_experiment(
        policy, contributions, overlaps, stabilities, registry=registry
    )
    experiment = registry.load()[0]
    assert experiment.subsystem is ResearchSubsystem.ADAPTIVE_WEIGHTS
    metric_ids = {item.metric_id for item in experiment.treatment}
    assert "adaptive_weights.current_candidate_policy" in metric_ids
    assert "adaptive_weights.most_redundant_pair" in metric_ids
    assert research_diagnostic_plugins()[0].diagnostic_id == (
        "adaptive-indicator-weight-research"
    )


def test_adaptive_weights_cli_audit_and_report_are_research_only(
    tmp_path: Path,
) -> None:
    evidence = tuple(
        completed_evidence(index, partition=tuple(EvidencePartition)[index % 4])
        for index in range(16)
    )
    evidence_path = tmp_path / "evidence.json"
    export_evidence_json(evidence, evidence_path)
    runner = CliRunner()
    audit = runner.invoke(
        app,
        ["adaptive-weights", "--evidence", str(evidence_path), "audit"],
    )
    assert audit.exit_code == 0, audit.output
    assert "Completed Eligible Outcomes: 16" in audit.output
    assert "PRODUCTION_INFLUENCE=false" in audit.output
    json_result = runner.invoke(
        app,
        [
            "adaptive-weights",
            "--evidence",
            str(evidence_path),
            "--json",
            "contributions",
        ],
    )
    assert json_result.exit_code == 0, json_result.output
    payload = json.loads(json_result.output)
    assert payload["production_influence"] is False
    assert len(payload["contributions"]) == 10


def test_candidate_policy_registry_csv_json_exports(tmp_path) -> None:
    registry = CandidateWeightPolicyRegistry(tmp_path / "policies.json")
    assert registry.load() == ()
    registry.export_json(tmp_path / "export.json")
    registry.export_csv(tmp_path / "export.csv")
    assert "policies" in (tmp_path / "export.json").read_text(encoding="utf-8")
    assert "policy_id" in (tmp_path / "export.csv").read_text(encoding="utf-8")
