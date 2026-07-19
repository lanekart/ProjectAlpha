from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from alpha.cli import app
from alpha.data_value_audit import (
    PRODUCTION_INFLUENCE,
    DataValueAuditExporter,
    build_default_audit,
    default_dataset_registry,
)
from alpha.data_value_audit.models import (
    CostStatus,
    DatasetReportCard,
    ImpactLevel,
    ReplayMetric,
    ROIClass,
)
from alpha.data_value_audit.rendering import render_audit

runner = CliRunner()

REQUIRED_DATASET_IDS = {
    "official_nse_daily_history",
    "official_bse_daily_history",
    "corporate_actions",
    "splits",
    "bonuses",
    "rights",
    "dividends",
    "mergers",
    "demergers",
    "security_master",
    "isin_history",
    "listing_history",
    "delisting_history",
    "symbol_history",
    "historical_index_ohlc",
    "historical_index_membership",
    "delivery_data",
    "delivery_quantity",
    "delivery_percentage",
    "ownership_data",
    "promoter_holdings",
    "fii_holdings",
    "dii_holdings",
    "mutual_fund_holdings",
    "earnings_data",
    "earnings_dates",
    "earnings_revisions",
    "earnings_surprises",
    "market_breadth",
    "india_vix",
    "risk_free_rate",
}

REQUIRED_ARTIFACTS = {
    "dataset_report_cards.csv",
    "information_gain.csv",
    "decision_gain.csv",
    "dependency_graph.csv",
    "cost_model.csv",
    "roi_matrix.csv",
    "procurement_strategy.md",
    "budget_0.md",
    "budget_1L.md",
    "budget_5L.md",
    "budget_unlimited.md",
    "executive_report.md",
}


def test_registry_covers_every_required_candidate_and_is_stable() -> None:
    first = default_dataset_registry()
    second = default_dataset_registry()
    ids = tuple(item.dataset_id for item in first)

    assert first == second
    assert len(first) == 34
    assert len(ids) == len(set(ids))
    assert REQUIRED_DATASET_IDS <= set(ids)


def test_information_decision_and_infrastructure_scores_are_bounded() -> None:
    report = build_default_audit()

    for card in report.cards:
        assert 0 <= card.information.score <= 100
        assert 0 <= card.decision.score <= 100
        assert 0 <= card.infrastructure.score <= 100
        assert 0 <= card.gross_value_score <= 100
        assert card.information.rationale.startswith("Ordinal evidence rubric")
        assert card.candidate.evidence_sources


def test_replay_gain_is_categorical_and_never_fabricates_uplift() -> None:
    report = build_default_audit()

    for card in report.cards:
        assert card.replay.overall in set(ImpactLevel)
        assert {impact.metric for impact in card.replay.impacts} == set(ReplayMetric)
        for impact in card.replay.impacts:
            assert (
                "no numeric replay improvement is estimated" in impact.reason
                or "effect remains unknown" in impact.reason
            )


def test_published_costs_and_unknown_costs_remain_distinct() -> None:
    cards = _cards()

    assert cards["official_nse_daily_history"].cost.annual_cost_inr == 100_000
    assert cards["security_master"].cost.annual_cost_inr == 215_000
    assert cards["corporate_actions"].cost.annual_cost_inr == 500_000
    assert cards["historical_index_membership"].cost.status is CostStatus.QUOTE_REQUIRED
    assert cards["historical_index_membership"].priority_index is None
    assert cards["historical_index_membership"].roi_class is ROIClass.UNKNOWN
    assert cards["delivery_percentage"].cost.status is CostStatus.BUNDLED
    assert cards["delivery_percentage"].priority_index is None


def test_dependencies_and_sensitivity_report_lost_unlocks() -> None:
    report = build_default_audit()
    edges = {
        (item.source_dataset_id, item.relationship, item.target)
        for item in report.dependencies
    }
    sensitivity = {item.dataset_id: item for item in report.sensitivity}

    assert ("security_master", "REQUIRED_BY", "corporate_actions") in edges
    assert ("corporate_actions", "UNLOCKS", "valid_performance") in edges
    assert sensitivity["security_master"].dependent_unlocks_lost > 0
    assert sensitivity["security_master"].value_score_lost > 0


def test_budget_strategies_obey_caps_and_dependency_order() -> None:
    plans = {plan.budget_id: plan for plan in build_default_audit().budgets}

    assert plans["budget_0"].known_annual_spend_inr == 0
    assert plans["budget_1L"].selected_dataset_ids == ("official_nse_daily_history",)
    assert plans["budget_1L"].known_annual_spend_inr == 100_000
    assert plans["budget_5L"].known_annual_spend_inr == 435_000
    assert plans["budget_5L"].unallocated_inr == 65_000
    assert plans["budget_unlimited"].selected_dataset_ids[:3] == (
        "official_nse_daily_history",
        "security_master",
        "corporate_actions",
    )
    assert plans["budget_unlimited"].known_annual_spend_inr == 935_000


def test_export_bundle_is_exact_and_deterministic(tmp_path: Path) -> None:
    report = build_default_audit()
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_paths = DataValueAuditExporter().export(report, first)
    second_paths = DataValueAuditExporter().export(report, second)

    assert {path.name for path in first_paths} == REQUIRED_ARTIFACTS
    assert {path.name for path in second_paths} == REQUIRED_ARTIFACTS
    for filename in REQUIRED_ARTIFACTS:
        assert (first / filename).read_bytes() == (second / filename).read_bytes()
    budget_page = (first / "budget_1L.md").read_text(encoding="utf-8")
    assert (
        "# If I had only ₹1 lakh to spend this year, what should I buy first—and why?"
        in budget_page
    )
    assert "PRODUCTION_INFLUENCE=false" in budget_page


def test_audit_rendering_identifies_required_decisions() -> None:
    rendered = render_audit(build_default_audit())

    assert "Highest Estimable ROI: Official NSE Daily History" in rendered
    assert "Lowest Estimable ROI:" in rendered
    assert "Biggest Infrastructure Unlock: Corporate Actions" in rendered
    assert "Biggest Replay Improvement: Corporate Actions" in rendered
    assert "Biggest Feature Improvement: Delivery Percentage" in rendered
    assert "Cheapest High-value Purchase: Official NSE Daily History" in rendered
    assert "Unknown prices are never treated as free" in rendered


def test_all_data_value_cli_commands_render_and_export(tmp_path: Path) -> None:
    commands = {
        "audit": "Data Value & ROI Audit",
        "roi": "Data Value ROI Matrix",
        "budgets": "Data Procurement Budgets",
        "report": "# Project Alpha Data Value & ROI Audit",
    }
    for command, expected in commands.items():
        output = tmp_path / command
        result = runner.invoke(
            app,
            ["data-value", command, "--output", str(output)],
        )
        assert result.exit_code == 0, result.stdout
        assert expected in result.stdout
        assert "PRODUCTION_INFLUENCE=false" in result.stdout
        assert {path.name for path in output.iterdir()} == REQUIRED_ARTIFACTS


def test_dvra_is_diagnostic_only() -> None:
    report = build_default_audit()

    assert PRODUCTION_INFLUENCE is False
    assert report.production_influence is False
    assert all(card.candidate.dataset_id for card in report.cards)


def _cards() -> dict[str, DatasetReportCard]:
    return {card.candidate.dataset_id: card for card in build_default_audit().cards}
