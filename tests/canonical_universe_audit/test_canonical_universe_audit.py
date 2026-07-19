from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

import duckdb
import pandas as pd
import pytest
from typer.testing import CliRunner

from alpha.analysis.signals.daily_report import DailyMarketReport
from alpha.application.intelligence_inputs import IntelligenceInputBuilder
from alpha.canonical_universe_audit.canonical_runner import (
    CANONICAL_HISTORY_WINDOW,
    CanonicalAuditInputBuilder,
)
from alpha.canonical_universe_audit.engine import (
    AuditRunRequest,
    CanonicalUniverseAuditEngine,
    _bars_by_candidate,
    _gate_category,
)
from alpha.canonical_universe_audit.exporting import (
    CanonicalUniverseAuditExporter,
    load_audit_payload,
)
from alpha.canonical_universe_audit.models import (
    ACU_RUN_VERSION,
    CANONICAL_ENGINE_VERSION,
    DATASET_VERSION,
    EVIDENCE_LABELS,
    PRODUCTION_INFLUENCE,
    CandidateOutcomeRecord,
    CandidateRankingRecord,
    CanonicalUniverseAuditReport,
    DailyOpportunityRecord,
    DatasetManifest,
    ExecutiveSummary,
    GateAttributionRecord,
    GateCategory,
    LiquidityBucket,
    LiquidityCapacityRecord,
    MonthlyOpportunitySummary,
    OpportunityHeat,
    PeriodOpportunitySummary,
    SectorOpportunitySummary,
    SymbolOpportunitySummary,
)
from alpha.canonical_universe_audit.research_integration import (
    record_acu_experiment,
    research_diagnostic_plugins,
)
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.cli import app
from alpha.decision_intelligence import RejectionReasonCode
from alpha.research.research_registry import ResearchExperimentRegistry


def test_canonical_policy_is_frozen_and_diagnostic_only() -> None:
    assert CANONICAL_ENGINE_VERSION == "ALPHA_CANONICAL_v1.0"
    assert ACU_RUN_VERSION == "ACU-1"
    assert CANONICAL_HISTORY_WINDOW == 250
    assert DATASET_VERSION == "LEGACY_DATASET"
    assert EVIDENCE_LABELS == (
        "PROVISIONAL",
        "NOT AUTHORITATIVE",
        "LEGACY_DATASET",
    )
    assert PRODUCTION_INFLUENCE is False


def test_legacy_store_is_read_only_and_reports_actual_manifest(tmp_path: Path) -> None:
    database = _database(tmp_path, sessions=3, symbols=2)

    with LegacyMarketDataStore(database) as store:
        manifest = store.manifest()
        frame = store.find_by_trade_date(date(2024, 1, 3))

        assert manifest.rows == 6
        assert manifest.sessions == 3
        assert manifest.symbols == 2
        assert manifest.sector_rows == 0
        assert tuple(frame["symbol"]) == ("S00", "S01")
        with pytest.raises(duckdb.InvalidInputException):
            store.connection.execute("DELETE FROM daily_prices")


def test_bounded_history_builder_preserves_canonical_top_ten() -> None:
    prices = _price_frame(date(2024, 12, 31), symbols=12)
    analysis = DailyMarketReport().generate(prices)["analysis"]
    history = _history_frame(symbols=12, sessions=250)
    repository = _HistoryRepository(history)
    canonical = IntelligenceInputBuilder(
        price_repository=repository,
        history_window=250,
    ).build(observed_on=date(2024, 12, 31), analysis=analysis)
    assert len(repository.requests[-1]) == 12

    bounded_repository = _HistoryRepository(history)
    bounded = CanonicalAuditInputBuilder(
        price_repository=bounded_repository,
        history_window=250,
    ).build(observed_on=date(2024, 12, 31), analysis=analysis)

    assert len(bounded_repository.requests[-1]) == 10
    assert tuple(item.symbol for item in bounded.recommendation_candidates) == tuple(
        item.symbol for item in canonical.recommendation_candidates
    )
    assert all(
        len(item.price_history) == 250 for item in bounded.recommendation_candidates
    )


@pytest.mark.parametrize(
    ("code", "category"),
    (
        (RejectionReasonCode.WEAK_VERDICT, GateCategory.PRICE),
        (RejectionReasonCode.INSUFFICIENT_CAPACITY, GateCategory.VOLUME),
        (RejectionReasonCode.POOR_REWARD_RISK, GateCategory.RISK),
        (RejectionReasonCode.LATE_ENTRY, GateCategory.ENTRY_TIMING),
        (RejectionReasonCode.INSUFFICIENT_EVIDENCE, GateCategory.APPROVAL),
    ),
)
def test_gate_attribution_is_typed_and_deterministic(
    code: RejectionReasonCode,
    category: GateCategory,
) -> None:
    assert _gate_category(code) is category


def test_future_bar_adapter_normalizes_pandas_timestamp() -> None:
    frame = pd.DataFrame(
        (
            {
                "candidate_id": "2024-01-01|TEST",
                "symbol": "TEST",
                "trade_date": pd.Timestamp("2024-01-02"),
                "open": 100,
                "high": 105,
                "low": 99,
                "close": 104,
                "volume": 100_000,
            },
        )
    )

    bars = _bars_by_candidate(frame)["2024-01-01|TEST"]

    assert bars[0].observed_on == date(2024, 1, 2)
    assert type(bars[0].observed_on) is date


def test_small_universe_audit_runs_current_pipeline_and_exports(tmp_path: Path) -> None:
    database = _database(tmp_path, sessions=205, symbols=12)
    output = tmp_path / "acu"
    with LegacyMarketDataStore(database) as store:
        report = CanonicalUniverseAuditEngine().run(
            store=store,
            request=AuditRunRequest(
                start=date(2024, 7, 22),
                end=date(2024, 7, 23),
                generated_at=datetime(2024, 7, 24, tzinfo=UTC),
            ),
        )

    paths = CanonicalUniverseAuditExporter().export(
        report,
        output_directory=output,
    )
    payload = load_audit_payload(output)

    assert report.canonical_engine_version == CANONICAL_ENGINE_VERSION
    assert report.production_influence is False
    assert report.executive.total_sessions == 2
    assert report.executive.total_candidates == 20
    assert report.daily[-1].eligible_securities == 12
    assert len(paths) == 11
    assert (output / "opportunity_capacity.json").exists()
    assert (output / "opportunity_capacity.csv").exists()
    assert (output / "gate_attribution.csv").exists()
    assert (output / "sector_opportunities.csv").exists()
    assert (output / "daily_opportunities.csv").exists()
    assert (output / "monthly_summary.csv").exists()
    assert (output / "candidate_rankings.csv").exists()
    assert (output / "liquidity_capacity.csv").exists()
    assert (output / "symbol_statistics.csv").exists()
    assert (output / "executive_report.md").exists()
    assert payload["production_influence"] is False
    assert payload["dataset"]["labels"] == list(EVIDENCE_LABELS)
    assert "PROVISIONAL / NOT AUTHORITATIVE / LEGACY_DATASET" in (
        output / "executive_report.md"
    ).read_text(encoding="utf-8")


def test_export_is_deterministic_for_same_report(tmp_path: Path) -> None:
    report = _report()
    first = tmp_path / "first"
    second = tmp_path / "second"

    CanonicalUniverseAuditExporter().export(report, output_directory=first)
    CanonicalUniverseAuditExporter().export(report, output_directory=second)

    assert (first / "opportunity_capacity.json").read_bytes() == (
        second / "opportunity_capacity.json"
    ).read_bytes()
    assert (first / "candidate_rankings.csv").read_bytes() == (
        second / "candidate_rankings.csv"
    ).read_bytes()


@pytest.mark.parametrize(
    ("command", "expected"),
    (
        ("opportunities", "ACU Opportunity Capacity"),
        ("sectors", "ACU Sector Opportunities"),
        ("gates", "ACU Rejection Gate Attribution"),
        ("liquidity", "ACU Liquidity Capacity"),
        ("capacity", "ACU Portfolio Capacity Estimate"),
        ("report", "# Alpha Canonical Universe Opportunity Audit"),
    ),
)
def test_acu_cli_views_are_functional(
    tmp_path: Path,
    command: str,
    expected: str,
) -> None:
    output = tmp_path / "acu"
    CanonicalUniverseAuditExporter().export(_report(), output_directory=output)

    result = CliRunner().invoke(app, ["acu", command, "--output", str(output)])

    assert result.exit_code == 0, result.output
    assert expected in result.output
    assert "LEGACY_DATASET" in result.output


def test_acu_run_cli_exports_complete_artifacts(tmp_path: Path) -> None:
    database = _database(tmp_path, sessions=2, symbols=12)
    output = tmp_path / "acu"

    result = CliRunner().invoke(
        app,
        [
            "acu",
            "run",
            "--database",
            str(database),
            "--output",
            str(output),
            "--research-registry",
            str(tmp_path / "research.json"),
            "--quiet",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "ALPHA_CANONICAL_v1.0" in result.output
    assert "Production Influence: false" in result.output
    assert (output / "executive_report.md").exists()


def test_acu_research_registry_and_ird_plugin_are_isolated(tmp_path: Path) -> None:
    report = _report()
    registry = ResearchExperimentRegistry(tmp_path / "research.json")

    assert record_acu_experiment(report, registry=registry)
    assert not record_acu_experiment(report, registry=registry)
    assert registry.load()[0].production_influence is False
    plugin = research_diagnostic_plugins()[0]
    assert plugin.diagnostic_id == "canonical-universe-opportunity-audit"
    assert plugin.source_module == "alpha.canonical_universe_audit"


def test_report_rejects_any_production_influence() -> None:
    with pytest.raises(ValueError, match="cannot influence production"):
        replace(_report(), production_influence=True)


class _HistoryRepository:
    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.requests: list[tuple[str, ...]] = []

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        self.requests.append(symbols)
        return self.frame.loc[
            self.frame["symbol"].isin(symbols) & (self.frame["trade_date"] <= end_date)
        ].copy()


def _database(tmp_path: Path, *, sessions: int, symbols: int) -> Path:
    path = tmp_path / f"legacy-{sessions}-{symbols}.duckdb"
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE daily_prices (
            symbol VARCHAR,
            trade_date DATE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            sector VARCHAR,
            exchange VARCHAR
        )
        """
    )
    start = date(2024, 1, 1)
    rows = []
    for day in range(sessions):
        observed_on = start + timedelta(days=day)
        for symbol_index in range(symbols):
            price = Decimal("100") + Decimal(symbol_index * 3) + Decimal(day) / 10
            movement = Decimal(symbol_index - symbols // 2) / Decimal("100")
            rows.append(
                (
                    f"S{symbol_index:02d}",
                    observed_on,
                    float(price),
                    float(price + Decimal("2") + abs(movement)),
                    float(price - Decimal("1")),
                    float(price + movement),
                    100_000 + symbol_index * 10_000 + day,
                    None,
                    "NSE",
                )
            )
    connection.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    connection.close()
    return path


def _price_frame(observed_on: date, *, symbols: int) -> pd.DataFrame:
    rows = []
    for index in range(symbols):
        open_price = Decimal("100") + Decimal(index)
        rows.append(
            {
                "symbol": f"S{index:02d}",
                "trade_date": observed_on,
                "open": float(open_price),
                "high": float(open_price + Decimal("3")),
                "low": float(open_price - Decimal("2")),
                "close": float(open_price + Decimal(index - 5) / Decimal("10")),
                "volume": 100_000 + index * 10_000,
                "sector": None,
                "exchange": "NSE",
            }
        )
    return pd.DataFrame(rows)


def _history_frame(*, symbols: int, sessions: int) -> pd.DataFrame:
    rows = []
    start = date(2024, 1, 1)
    for day in range(sessions):
        observed_on = start + timedelta(days=day)
        for index in range(symbols):
            price = Decimal("80") + Decimal(index) + Decimal(day) / Decimal("20")
            rows.append(
                {
                    "symbol": f"S{index:02d}",
                    "trade_date": observed_on,
                    "open": price,
                    "high": price + Decimal("2"),
                    "low": price - Decimal("1"),
                    "close": price + Decimal("0.50"),
                    "volume": 100_000 + index * 10_000,
                    "sector": None,
                    "exchange": "NSE",
                }
            )
    return pd.DataFrame(rows)


def _report() -> CanonicalUniverseAuditReport:
    observed_on = date(2024, 1, 2)
    daily = DailyOpportunityRecord(
        observed_on=observed_on,
        universe_size=12,
        eligible_securities=12,
        technical_candidates=10,
        approval_candidates=1,
        institutional_approvals=1,
        portfolio_eligible=1,
        raw_approvals=1,
        independent_approvals=1,
        average_score=Decimal("75"),
        median_score=Decimal("75"),
        maximum_score=Decimal("88"),
        score_80_plus=1,
        score_90_plus=0,
        score_95_plus=0,
        estimated_invested_capital=Decimal("500000"),
        estimated_position_count=1,
        runtime_status="SUCCESS",
        runtime_error=None,
    )
    ranking = CandidateRankingRecord(
        observed_on=observed_on,
        rank=1,
        symbol="TEST",
        final_signal="BUY",
        score=Decimal("88"),
        confidence="HIGH",
        sector="UNKNOWN",
        liquidity_bucket=LiquidityBucket.HIGH,
        expected_r=Decimal("2"),
        suggested_priority="RESEARCH_PRIORITY_HIGH",
        approval_candidate=True,
        institutional_approved=True,
        portfolio_eligible=True,
        setup_type="BREAKOUT",
        setup_stage="ENTRY_READY",
        entry_price=Decimal("100"),
        initial_stop=Decimal("95"),
        target_1=Decimal("110"),
        expected_return=Decimal("0.10"),
        holding_period_days=20,
    )
    return CanonicalUniverseAuditReport(
        audit_id="ACU-1|ALPHA_CANONICAL_v1.0|2024-01-02|2024-01-02",
        generated_at=datetime(2024, 1, 3, tzinfo=UTC),
        canonical_engine_version=CANONICAL_ENGINE_VERSION,
        dataset=DatasetManifest(
            dataset_version=DATASET_VERSION,
            first_session=observed_on,
            last_session=observed_on,
            sessions=1,
            rows=12,
            symbols=12,
            exchange="NSE",
            sector_rows=0,
        ),
        daily=(daily,),
        rankings=(ranking,),
        gates=(
            GateAttributionRecord(
                observed_on=observed_on,
                symbol="OTHER",
                gate_code="WEAK_VERDICT",
                category=GateCategory.PRICE,
                explanation="Only BUY is deployable.",
                primary=True,
            ),
        ),
        outcomes=(
            CandidateOutcomeRecord(
                observed_on=observed_on,
                symbol="TEST",
                entered=True,
                completed=True,
                won=True,
                realized_return_pct=Decimal("5"),
                realized_r=Decimal("1"),
                holding_period_days=10,
                exit_reason="TARGET_1",
                evidence_note="Target reached.",
            ),
        ),
        monthly=(
            MonthlyOpportunitySummary(
                month="2024-01",
                trading_days=1,
                total_opportunities=1,
                average_opportunities_per_day=Decimal("1"),
                maximum_opportunities=1,
                heat=OpportunityHeat.AVERAGE,
            ),
        ),
        weekly=(
            PeriodOpportunitySummary(
                period="2024-W01",
                trading_days=1,
                total_opportunities=1,
                average_opportunities_per_day=Decimal("1"),
                maximum_opportunities_in_day=1,
            ),
        ),
        yearly=(
            PeriodOpportunitySummary(
                period="2024",
                trading_days=1,
                total_opportunities=1,
                average_opportunities_per_day=Decimal("1"),
                maximum_opportunities_in_day=1,
            ),
        ),
        sectors=(
            SectorOpportunitySummary(
                sector="UNKNOWN",
                candidates=1,
                approved_opportunities=1,
                average_opportunities_per_day=Decimal("1"),
                completed_outcomes=1,
                win_rate=Decimal("1"),
                average_realized_return_pct=Decimal("5"),
                average_expected_return=Decimal("0.10"),
            ),
        ),
        liquidity=(
            LiquidityCapacityRecord(
                symbol="TEST",
                average_daily_volume=Decimal("100000"),
                average_daily_turnover=Decimal("10000000"),
                free_float=None,
                liquidity_bucket=LiquidityBucket.HIGH,
                deployable_at_10_lakh=Decimal("100000"),
                deployable_at_50_lakh=Decimal("100000"),
                deployable_at_1_crore=Decimal("100000"),
                deployable_at_5_crore=Decimal("100000"),
                deployable_at_10_crore=Decimal("100000"),
            ),
        ),
        symbols=(
            SymbolOpportunitySummary(
                symbol="TEST",
                candidate_count=1,
                approval_count=1,
                portfolio_eligible_count=1,
                active_years=Decimal("1"),
                candidates_per_year=Decimal("1"),
                approvals_per_year=Decimal("1"),
                candidates_per_decade=Decimal("10"),
                average_score=Decimal("88"),
            ),
        ),
        executive=ExecutiveSummary(
            total_sessions=1,
            total_candidates=1,
            total_approval_candidates=1,
            total_institutional_approvals=1,
            total_portfolio_eligible=1,
            average_opportunities_per_day=Decimal("1"),
            median_opportunities_per_day=Decimal("1"),
            maximum_opportunities_per_day=1,
            average_opportunities_per_month=Decimal("1"),
            maximum_opportunities_per_month=1,
            zero_opportunity_days=0,
            one_opportunity_days=1,
            two_plus_opportunity_days=0,
            five_plus_opportunity_days=0,
            average_invested_percent=Decimal("5"),
            average_idle_percent=Decimal("95"),
            average_positions=Decimal("1"),
            average_score=Decimal("88"),
            median_score=Decimal("88"),
            score_80_plus=1,
            score_90_plus=0,
            score_95_plus=0,
            largest_gate="WEAK_VERDICT",
            largest_gate_rejections=1,
            raw_simultaneous_approvals=1,
            independent_simultaneous_approvals=1,
            completed_outcomes=1,
            win_rate=Decimal("1"),
            expected_payoff_pct=Decimal("5"),
            canonical_runtime_failure_days=0,
            scored_candidates=1,
            average_opportunities_per_week=Decimal("1"),
            median_opportunities_per_week=Decimal("1"),
            maximum_opportunities_per_week=1,
            average_opportunities_per_year=Decimal("1"),
            median_opportunities_per_year=Decimal("1"),
            maximum_opportunities_per_year=1,
            average_trades_per_symbol=Decimal("1"),
            median_trades_per_symbol=Decimal("1"),
            opportunity_day_clusters=1,
            longest_opportunity_day_streak=1,
            pending_outcomes=0,
            not_entered_outcomes=0,
        ),
        definitions=MappingProxyType({"production_influence": "false"}),
    )
