from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import duckdb

from alpha.benchmark_replay.models import (
    ApprovalStatistic,
    BenchmarkReplayReport,
    RejectionCategory,
)
from alpha.warehouse_delta_audit.delta_engines import (
    IndicatorDeltaEngine,
    PriceDeltaEngine,
    ReplayDeltaEngine,
    unavailable_corporate_action_deltas,
)
from alpha.warehouse_delta_audit.models import DeltaThresholdPolicy
from alpha.warehouse_delta_audit.sampling import (
    _eligible_equity_symbols,
    _materialize_comparison,
    _materialize_legacy,
)

PriceRow = tuple[str, date, float, float, float, float, float]


def _database(
    path: Path,
    rows: Sequence[PriceRow],
    duplicates: int = 0,
) -> None:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """
            CREATE TABLE daily_prices(
                symbol VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE,
                low DOUBLE, close DOUBLE, volume DOUBLE, sector VARCHAR,
                exchange VARCHAR
            )
            """
        )
        connection.executemany(
            "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'NSE')",
            rows,
        )
        connection.execute(
            "CREATE TABLE source_duplicates(symbol VARCHAR, "
            "duplicate_observations BIGINT)"
        )
        connection.execute(
            "CREATE TABLE source_invalid_rows(symbol VARCHAR, "
            "invalid_observations BIGINT)"
        )
        if duplicates:
            connection.execute(
                "INSERT INTO source_duplicates VALUES ('TEST', ?)",
                (duplicates,),
            )


def test_price_delta_classifies_exact_small_large_missing_and_duplicates(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "legacy.duckdb"
    comparison = tmp_path / "comparison.duckdb"
    base = date(2024, 1, 1)
    _database(
        legacy,
        [
            ("TEST", base, 100, 102, 99, 101, 1000),
            ("TEST", base + timedelta(days=1), 100, 102, 99, 101, 1000),
            ("TEST", base + timedelta(days=2), 100, 102, 99, 101, 1000),
            ("TEST", base + timedelta(days=3), 100, 102, 99, 101, 1000),
        ],
        duplicates=2,
    )
    _database(
        comparison,
        [
            ("TEST", base, 100, 102, 99, 101, 1000),
            ("TEST", base + timedelta(days=1), 100.01, 102, 99, 101, 1000),
            ("TEST", base + timedelta(days=2), 90, 102, 89, 91, 1500),
            ("TEST", base + timedelta(days=4), 100, 102, 99, 101, 1000),
        ],
        duplicates=1,
    )
    rows = PriceDeltaEngine().compare(
        legacy_sample=legacy,
        comparison_sample=comparison,
        thresholds=DeltaThresholdPolicy(),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.matched_observations == 3
    assert row.exact_observations == 1
    assert row.small_difference_observations == 1
    assert row.large_difference_observations == 1
    assert row.missing_from_comparison == 1
    assert row.missing_from_legacy == 1
    assert row.legacy_duplicate_observations == 2
    assert row.comparison_duplicate_observations == 1
    assert row.legacy_invalid_observations == 0
    assert row.comparison_invalid_observations == 0


def test_indicator_delta_detects_material_indicator_and_signal_changes(
    tmp_path: Path,
) -> None:
    legacy = tmp_path / "legacy.duckdb"
    comparison = tmp_path / "comparison.duckdb"
    start = date(2023, 1, 1)
    base_rows: list[PriceRow] = [
        (
            "TEST",
            start + timedelta(days=index),
            100 + index / 10,
            101 + index / 10,
            99 + index / 10,
            100 + index / 10,
            1000 + index,
        )
        for index in range(240)
    ]
    changed: list[PriceRow] = []
    for index, row in enumerate(base_rows):
        symbol, observed_on, open_price, high, low, close, volume = row
        changed_close = close * 0.80 if index >= 220 else close
        changed.append(
            (
                symbol,
                observed_on,
                open_price,
                max(high, changed_close + 1),
                min(low, changed_close - 1),
                changed_close,
                volume,
            )
        )
    _database(legacy, base_rows)
    _database(comparison, changed)
    records = IndicatorDeltaEngine().compare(
        legacy_sample=legacy,
        comparison_sample=comparison,
        symbols=("TEST",),
        thresholds=DeltaThresholdPolicy(),
    )
    assert {item.indicator for item in records} == {
        "EMA20",
        "EMA50",
        "EMA200",
        "ATR14",
        "SUPPORT60",
        "RESISTANCE60",
        "BREAKOUT20",
    }
    assert sum(item.material_changes for item in records) > 0
    assert sum(item.signal_changes for item in records) > 0


def test_missing_corporate_action_evidence_is_unknown_not_zero() -> None:
    records = unavailable_corporate_action_deltas()
    assert records
    assert all(item.indicator_changing_events is None for item in records)
    assert all(item.replay_changing_events is None for item in records)
    assert all(item.status == "UNKNOWN_SOURCE_UNAVAILABLE" for item in records)


def test_mixed_nse_csv_schemas_are_normalized_without_symbol_collision(
    tmp_path: Path,
) -> None:
    legacy_csv = tmp_path / "legacy.csv"
    udiff_csv = tmp_path / "udiff.csv"
    legacy_csv.write_text(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TIMESTAMP,ISIN\n"
        "TEST,EQ,100,102,99,101,1000,01-Jan-2024,INE000000001\n"
    )
    udiff_csv.write_text(
        "TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol,TradDt,ISIN\n"
        "TEST,EQ,101,103,100,102,1100,2024-01-02,INE000000001\n"
    )
    destination = tmp_path / "comparison.duckdb"
    _materialize_comparison(
        files=(legacy_csv, udiff_csv),
        destination=destination,
        symbols=("TEST",),
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
    )
    with duckdb.connect(str(destination), read_only=True) as connection:
        rows = connection.execute(
            "SELECT symbol, trade_date, close FROM daily_prices ORDER BY trade_date"
        ).fetchall()
    assert rows == [
        ("TEST", date(2024, 1, 1), 101.0),
        ("TEST", date(2024, 1, 2), 102.0),
    ]


def test_equity_population_excludes_debt_and_fund_isins(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TIMESTAMP,ISIN\n"
        "STOCK,EQ,100,102,99,101,1000,01-Jan-2024,INE000000001\n"
        "ETF,EQ,100,102,99,101,1000,01-Jan-2024,INF000000001\n"
        "BOND,N1,100,102,99,101,1000,01-Jan-2024,INE000000002\n"
    )
    symbols = _eligible_equity_symbols(
        (source,),
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
    )
    assert symbols == ("STOCK",)


def test_malformed_ohlc_bar_is_counted_and_excluded(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,TIMESTAMP,ISIN\n"
        "TEST,EQ,100,102,99,110,1000,01-Jan-2024,INE000000001\n"
    )
    destination = tmp_path / "comparison.duckdb"
    _materialize_comparison(
        files=(source,),
        destination=destination,
        symbols=("TEST",),
        start=date(2024, 1, 1),
        end=date(2024, 1, 1),
    )
    with duckdb.connect(str(destination), read_only=True) as connection:
        valid = connection.execute("SELECT COUNT(*) FROM daily_prices").fetchone()
        invalid = connection.execute(
            "SELECT invalid_observations FROM source_invalid_rows WHERE symbol='TEST'"
        ).fetchone()
    assert valid == (0,)
    assert invalid == (1,)


def test_malformed_legacy_bar_is_counted_and_excluded(tmp_path: Path) -> None:
    source = tmp_path / "legacy-source.duckdb"
    destination = tmp_path / "legacy-sample.duckdb"
    with duckdb.connect(str(source)) as connection:
        connection.execute(
            """
            CREATE TABLE daily_prices(
                symbol VARCHAR, trade_date DATE, open DOUBLE, high DOUBLE,
                low DOUBLE, close DOUBLE, volume DOUBLE, sector VARCHAR,
                exchange VARCHAR
            )
            """
        )
        connection.execute(
            "INSERT INTO daily_prices VALUES "
            "('TEST', '2024-01-01', 100, 102, 99, 110, 1000, NULL, 'NSE')"
        )
    _materialize_legacy(
        source=source,
        destination=destination,
        symbols=("TEST",),
        start=date(2024, 1, 1),
        end=date(2024, 1, 1),
    )
    with duckdb.connect(str(destination), read_only=True) as connection:
        valid = connection.execute("SELECT COUNT(*) FROM daily_prices").fetchone()
        invalid = connection.execute(
            "SELECT invalid_observations FROM source_invalid_rows WHERE symbol='TEST'"
        ).fetchone()
    assert valid == (0,)
    assert invalid == (1,)


def test_candidate_and_decision_delta_detects_approval_change() -> None:
    observed_on = date(2024, 5, 1)
    legacy_row = ApprovalStatistic(
        observed_on=observed_on,
        symbol="TEST",
        approved=False,
        opportunity_score=Decimal("65"),
        opportunity_grade="REJECT",
        final_signal="BUY",
        primary_reason_code="WEAK_SETUP",
        rejection_category=RejectionCategory.APPROVAL,
        explanation="Rejected.",
    )
    comparison_row = ApprovalStatistic(
        observed_on=observed_on,
        symbol="TEST",
        approved=True,
        opportunity_score=Decimal("80"),
        opportunity_grade="ACCEPTED",
        final_signal="BUY",
        primary_reason_code="ACCEPTED",
        rejection_category=RejectionCategory.UNKNOWN,
        explanation="Accepted.",
    )
    legacy = cast(
        BenchmarkReplayReport,
        SimpleNamespace(approval_statistics=(legacy_row,)),
    )
    comparison = cast(
        BenchmarkReplayReport,
        SimpleNamespace(approval_statistics=(comparison_row,)),
    )
    engine = ReplayDeltaEngine()
    candidates = engine.candidate_deltas(
        legacy=legacy,
        comparison=comparison,
        thresholds=DeltaThresholdPolicy(),
    )
    decisions = engine.decision_deltas(
        legacy=legacy,
        comparison=comparison,
        thresholds=DeltaThresholdPolicy(),
    )
    assert candidates[0].candidate_on_both == 1
    assert candidates[0].score_shifted == 1
    assert decisions[0].severity.value == "CRITICAL"
    assert decisions[0].legacy_approved is False
    assert decisions[0].comparison_approved is True


def test_replay_delta_uses_actual_report_values_without_fabrication() -> None:
    def report(
        candidates: int,
        approvals: int,
        trades: int,
        expectancy: Decimal | None,
        drawdown: Decimal,
        capture: Decimal | None,
    ) -> BenchmarkReplayReport:
        return cast(
            BenchmarkReplayReport,
            SimpleNamespace(
                candidate_statistics=(
                    SimpleNamespace(
                        technical_candidates=candidates,
                        institutional_approvals=approvals,
                    ),
                ),
                portfolio_statistics=SimpleNamespace(
                    logical_trades=trades,
                    win_rate_percent=None,
                    expectancy_percent=expectancy,
                    maximum_drawdown_percent=drawdown,
                ),
                opportunity_capture=(
                    SimpleNamespace(
                        opportunity_definition="ALL",
                        capture_rate_percent=capture,
                    ),
                ),
            ),
        )

    rows = ReplayDeltaEngine().replay_deltas(
        legacy=report(10, 1, 0, None, Decimal("0"), None),
        comparison=report(12, 2, 0, None, Decimal("0"), None),
    )
    indexed = {item.metric: item for item in rows}
    assert indexed["candidates"].delta == Decimal("2")
    assert indexed["approvals"].delta == Decimal("1")
    assert indexed["expectancy"].delta is None
    assert indexed["opportunity_capture"].delta is None
