from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

from alpha.historical_truth import (
    CanonicalPointInTimeWarehouse,
    HistoricalTruthWarehouse,
    PointInTimeSnapshotEngine,
)
from alpha.historical_truth.integrity import (
    HistoricalTruthIntegrityAudit,
    UnavailableClassification,
)


def _audit(tmp_path: Path) -> HistoricalTruthIntegrityAudit:
    root = tmp_path / "alpha_data"
    archive = HistoricalTruthWarehouse(root)
    canonical = CanonicalPointInTimeWarehouse(
        root / "warehouse" / "historical_truth.duckdb"
    )
    snapshots = PointInTimeSnapshotEngine(canonical, root / "snapshots")
    return HistoricalTruthIntegrityAudit(
        archive,
        canonical,
        snapshots,
        holiday_dates=frozenset({date(2026, 7, 16)}),
    )


def _ingest_valid_day(engine: HistoricalTruthIntegrityAudit) -> None:
    csv_path = engine.archive.root / "valid.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.write_text(
        "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,ISIN\n"
        "ABC,EQ,100,110,95,108,1000,INE000A01001\n",
        encoding="utf-8",
    )
    engine.canonical.ingest_bhavcopy_csv(
        csv_path,
        trading_date=date(2026, 7, 17),
    )
    snapshot = engine.snapshots.build(
        date(2026, 7, 17),
        generated_at=datetime(2026, 7, 20, tzinfo=UTC),
    )
    engine.snapshots.persist(snapshot)


def test_missing_dates_require_explicit_holiday_evidence(tmp_path: Path) -> None:
    engine = _audit(tmp_path)
    _ingest_valid_day(engine)

    report = engine.audit(
        date(2026, 7, 16),
        date(2026, 7, 20),
        as_of_date=date(2026, 7, 20),
    )

    classifications = {
        item.trading_date: item.classification for item in report.missing_dates
    }
    assert classifications[date(2026, 7, 16)] == (
        UnavailableClassification.HOLIDAY.value
    )
    assert classifications[date(2026, 7, 20)] == (
        UnavailableClassification.DATA_NOT_RELEASED.value
    )
    assert report.summary.expected_trading_days == 2
    assert report.summary.observed_trading_days == 1
    assert report.summary.coverage_ratio == 0.5


def test_invalid_ohlc_has_per_symbol_evidence(tmp_path: Path) -> None:
    engine = _audit(tmp_path)
    engine.canonical.initialise()
    with engine.canonical._connect() as connection:
        connection.execute(
            """
            INSERT INTO daily_candle VALUES (
                ?, 'nse', 'BROKEN', 'EQ', 'INE000B01002',
                100, 90, 95, 110, 0, 'source'
            )
            """,
            [date(2026, 7, 17)],
        )

    report = engine.audit(
        date(2026, 7, 17),
        date(2026, 7, 17),
        as_of_date=date(2026, 7, 20),
    )

    finding = next(
        item for item in report.security_findings if item.code == "INVALID_OHLC"
    )
    assert finding.symbol == "BROKEN"
    assert "open=100.0" in finding.evidence
    assert "high<open" in finding.evidence
    assert "high<close" in finding.evidence
    assert report.summary.zero_volume_anomalies == 1
    assert report.summary.candle_replay_ready is False
    assert report.summary.full_evidence_replay_ready is False


def test_snapshot_integrity_and_exports_are_deterministic(tmp_path: Path) -> None:
    engine = _audit(tmp_path)
    _ingest_valid_day(engine)
    report = engine.audit(
        date(2026, 7, 17),
        date(2026, 7, 17),
        as_of_date=date(2026, 7, 20),
    )

    first = engine.export(report, tmp_path / "first")
    second = engine.export(report, tmp_path / "second")

    assert report.summary.snapshots_valid == 1
    assert report.summary.candle_replay_ready is True
    assert report.summary.full_evidence_replay_ready is False
    assert [path.name for path in first] == [
        "historical_truth_integrity.json",
        "historical_truth_integrity.csv",
        "historical_truth_integrity.md",
    ]
    assert [path.read_bytes() for path in first] == [
        path.read_bytes() for path in second
    ]
    payload = json.loads(first[0].read_text(encoding="utf-8"))
    assert payload["summary"]["coverage_ratio"] == 1.0
    assert "NON_CANDLE_EVIDENCE_NOT_AUDITED" in payload["replay_blockers"]


def test_cross_series_isin_and_t0_exception_do_not_block_replay(
    tmp_path: Path,
) -> None:
    engine = _audit(tmp_path)
    engine.canonical.initialise()
    with engine.canonical._connect() as connection:
        connection.executemany(
            """
            INSERT INTO daily_candle VALUES (
                ?, 'nse', ?, ?, 'INE669E01016',
                ?, ?, ?, ?, 1000, 'source'
            )
            """,
            [
                (date(2026, 7, 17), "IDEA", "EQ", 11.0, 11.5, 10.8, 11.2),
                (date(2026, 7, 17), "IDEA", "T0", 11.27, 11.27, 11.27, 10.98),
            ],
        )
    snapshot = engine.snapshots.build(
        date(2026, 7, 17),
        generated_at=datetime(2026, 7, 20, tzinfo=UTC),
    )
    engine.snapshots.persist(snapshot)

    report = engine.audit(
        date(2026, 7, 17),
        date(2026, 7, 17),
        as_of_date=date(2026, 7, 20),
    )

    assert report.summary.duplicate_isins == 0
    assert report.summary.invalid_ohlc == 0
    assert report.summary.series_ohlc_exceptions == 1
    assert report.summary.candle_replay_ready is True
    finding = next(
        item
        for item in report.security_findings
        if item.code == "SERIES_SPECIFIC_OHLC"
    )
    assert finding.symbol == "IDEA"
    assert finding.series == "T0"
    assert finding.severity == "warning"


def test_same_isin_and_series_with_multiple_symbols_is_duplicate(
    tmp_path: Path,
) -> None:
    engine = _audit(tmp_path)
    engine.canonical.initialise()
    with engine.canonical._connect() as connection:
        connection.executemany(
            """
            INSERT INTO daily_candle VALUES (
                ?, 'nse', ?, 'EQ', 'INE000A01001',
                100, 110, 95, 108, 1000, 'source'
            )
            """,
            [
                (date(2026, 7, 17), "OLD"),
                (date(2026, 7, 17), "NEW"),
            ],
        )

    report = engine.audit(
        date(2026, 7, 17),
        date(2026, 7, 17),
        as_of_date=date(2026, 7, 20),
    )

    assert report.summary.duplicate_isins == 1
    assert "DUPLICATE_ISIN" in {
        item.code for item in report.security_findings
    }
