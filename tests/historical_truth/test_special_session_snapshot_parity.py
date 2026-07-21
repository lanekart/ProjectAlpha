from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.cli import historical_truth_app
from alpha.historical_truth.replay import HistoricalTruthReplayStore
from alpha.historical_truth.snapshots import (
    ImmutableMarketSnapshot,
    PointInTimeSnapshotEngine,
)
from alpha.historical_truth.special_session_snapshot_parity import (
    PRODUCTION_INFLUENCE,
    SnapshotFailureCode,
    SnapshotParityState,
    SnapshotParityStatus,
    SpecialSessionSnapshotParityEngine,
)

SPECIAL_DATE = date(2024, 11, 2)
REGULAR_DATE = date(2024, 11, 1)
FIXED_TIME = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def _canonical(
    tmp_path: Path,
    trading_dates: tuple[date, ...] = (SPECIAL_DATE,),
) -> CanonicalPointInTimeWarehouse:
    warehouse = CanonicalPointInTimeWarehouse(tmp_path / "truth.duckdb")
    for index, trading_date in enumerate(trading_dates):
        csv_path = tmp_path / f"source-{index}.csv"
        csv_path.write_text(
            "SYMBOL,SERIES,OPEN,HIGH,LOW,CLOSE,TOTTRDQTY,ISIN\n"
            f"ALPHA,EQ,{100 + index},110,95,108,1000,INE000000001\n"
            f"BETA,EQ,{200 + index},220,190,210,2000,INE000000002\n",
            encoding="utf-8",
        )
        warehouse.ingest_bhavcopy_csv(
            csv_path,
            trading_date=trading_date,
            source_sha256=f"source-{index}",
        )
    return warehouse


def _calendar_report(
    tmp_path: Path,
    special_dates: tuple[date, ...] = (SPECIAL_DATE,),
) -> Path:
    payload: dict[str, object] = {
        "contract_version": "HTR-007-v1.0.0",
        "certification_state": "certified",
        "sources": [],
        "records": [
            {
                "trading_date": item.isoformat(),
                "classification": "special_session",
                "observed_candles": True,
                "description": "Official NSE Muhurat session",
                "source_ids": [f"nse-calendar:{item.year}"],
                "issue_codes": [],
            }
            for item in special_dates
        ],
    }
    payload["report_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    path = tmp_path / "htr007_session_calendar.json"
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _engine(
    tmp_path: Path,
    warehouse: CanonicalPointInTimeWarehouse,
) -> tuple[SpecialSessionSnapshotParityEngine, PointInTimeSnapshotEngine]:
    snapshots = PointInTimeSnapshotEngine(warehouse, tmp_path / "snapshots")
    engine = SpecialSessionSnapshotParityEngine(
        warehouse,
        snapshots,
        clock=lambda: FIXED_TIME,
    )
    return engine, snapshots


def _persist_mutated(
    snapshots: PointInTimeSnapshotEngine,
    trading_date: date,
    *,
    metadata_date: date | None = None,
    exchange: str | None = None,
    symbol_count: int | None = None,
    candle_close: float | None = None,
    source_database: str | None = None,
) -> Path:
    snapshot = snapshots.build(trading_date, generated_at=FIXED_TIME)
    metadata = replace(
        snapshot.metadata,
        trading_date=metadata_date or snapshot.metadata.trading_date,
        exchange=exchange or snapshot.metadata.exchange,
        symbol_count=(
            symbol_count if symbol_count is not None else snapshot.metadata.symbol_count
        ),
        source_database=source_database or snapshot.metadata.source_database,
    )
    candles = snapshot.candles
    if candle_close is not None:
        first = candles[0]
        changed = replace(
            first,
            close_price=candle_close,
            high_price=max(first.high_price, candle_close),
        )
        candles = (changed, *candles[1:])
    checksum = PointInTimeSnapshotEngine._content_sha256(metadata, candles)
    mutated = ImmutableMarketSnapshot(
        metadata=metadata,
        candles=candles,
        content_sha256=checksum,
    )
    path = snapshots.path_for(trading_date)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            PointInTimeSnapshotEngine._serialise(mutated),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_official_weekend_without_snapshot_is_discovered_and_created(
    tmp_path: Path,
) -> None:
    warehouse = _canonical(tmp_path)
    calendar = _calendar_report(tmp_path)
    engine, snapshots = _engine(tmp_path, warehouse)

    report = engine.run(
        calendar,
        start_date=SPECIAL_DATE,
        end_date=SPECIAL_DATE,
    )

    record = report.records[0]
    assert record.pre_run_snapshot_state == "missing"
    assert record.snapshot_status is SnapshotParityStatus.CREATED
    assert record.snapshot_created
    assert record.snapshot_verification_valid
    assert record.canonical_snapshot_row_match
    assert record.canonical_snapshot_content_match
    assert record.snapshot_symbol_count == 2
    assert record.snapshot_total_volume == 3000
    assert snapshots.path_for(SPECIAL_DATE).is_file()
    assert report.summary.final_parity_state is (
        SnapshotParityState.COMPLETE_SNAPSHOT_PARITY
    )


def test_ordinary_weekend_filter_is_not_applicable(tmp_path: Path) -> None:
    warehouse = _canonical(tmp_path, (SPECIAL_DATE, date(2024, 11, 3)))
    calendar = _calendar_report(tmp_path)
    engine, snapshots = _engine(tmp_path, warehouse)

    report = engine.run(
        calendar,
        start_date=SPECIAL_DATE,
        end_date=date(2024, 11, 3),
        selected_dates=(date(2024, 11, 3),),
    )

    record = report.records[0]
    assert record.snapshot_status is SnapshotParityStatus.NOT_APPLICABLE
    assert record.snapshot_failure_code is (
        SnapshotFailureCode.NOT_OFFICIAL_SPECIAL_SESSION
    )
    assert not snapshots.path_for(date(2024, 11, 3)).exists()


def test_official_session_without_canonical_candles_fails_closed(
    tmp_path: Path,
) -> None:
    warehouse = _canonical(tmp_path, ())
    calendar = _calendar_report(tmp_path)
    engine, _ = _engine(tmp_path, warehouse)

    report = engine.run(
        calendar,
        start_date=SPECIAL_DATE,
        end_date=SPECIAL_DATE,
    )

    assert report.records[0].snapshot_failure_code is (
        SnapshotFailureCode.CANONICAL_SESSION_MISSING
    )
    assert report.summary.final_parity_state is (
        SnapshotParityState.INSUFFICIENT_EVIDENCE
    )


def test_repeated_date_filters_are_deduplicated_and_sorted(tmp_path: Path) -> None:
    second = date(2025, 10, 21)
    warehouse = _canonical(tmp_path, (SPECIAL_DATE, second))
    calendar = _calendar_report(tmp_path, (SPECIAL_DATE, second))
    engine, _ = _engine(tmp_path, warehouse)

    report = engine.run(
        calendar,
        start_date=SPECIAL_DATE,
        end_date=second,
        selected_dates=(second, SPECIAL_DATE, second),
    )

    assert tuple(item.trading_date for item in report.records) == (
        SPECIAL_DATE,
        second,
    )


def test_full_window_missing_snapshot_discovery(tmp_path: Path) -> None:
    warehouse = _canonical(tmp_path, (REGULAR_DATE, SPECIAL_DATE))
    calendar = _calendar_report(tmp_path)
    engine, snapshots = _engine(tmp_path, warehouse)
    snapshots.persist(snapshots.build(REGULAR_DATE, generated_at=FIXED_TIME))

    report = engine.run(
        calendar,
        start_date=REGULAR_DATE,
        end_date=SPECIAL_DATE,
        verify_only=True,
    )

    assert report.summary.canonical_observed_dates == 2
    assert report.summary.snapshot_files_present == 1
    assert report.summary.missing_snapshot_dates == (SPECIAL_DATE,)
    assert report.records[0].snapshot_status is SnapshotParityStatus.MISSING


def test_valid_existing_snapshot_is_reused_without_rewrite(tmp_path: Path) -> None:
    warehouse = _canonical(tmp_path)
    calendar = _calendar_report(tmp_path)
    engine, snapshots = _engine(tmp_path, warehouse)
    path = snapshots.persist(snapshots.build(SPECIAL_DATE, generated_at=FIXED_TIME))
    before = path.read_bytes()
    before_mtime = path.stat().st_mtime_ns

    first = engine.run(
        calendar,
        start_date=SPECIAL_DATE,
        end_date=SPECIAL_DATE,
    )
    second = engine.run(
        calendar,
        start_date=SPECIAL_DATE,
        end_date=SPECIAL_DATE,
        verify_only=True,
    )

    assert first.records[0].snapshot_status is SnapshotParityStatus.REUSED
    assert second.records[0].snapshot_status is SnapshotParityStatus.VERIFIED
    assert path.read_bytes() == before
    assert path.stat().st_mtime_ns == before_mtime
    assert first.records[0].snapshot_content_sha256 == (
        second.records[0].snapshot_content_sha256
    )


def test_invalid_checksum_is_rejected(tmp_path: Path) -> None:
    warehouse = _canonical(tmp_path)
    calendar = _calendar_report(tmp_path)
    engine, snapshots = _engine(tmp_path, warehouse)
    path = snapshots.persist(snapshots.build(SPECIAL_DATE, generated_at=FIXED_TIME))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["candles"][0]["close_price"] = 109.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    record = engine.run(
        calendar,
        start_date=SPECIAL_DATE,
        end_date=SPECIAL_DATE,
    ).records[0]

    assert record.snapshot_failure_code is (
        SnapshotFailureCode.SNAPSHOT_CHECKSUM_MISMATCH
    )
    assert record.snapshot_status is SnapshotParityStatus.INVALID


@pytest.mark.parametrize(
    ("mutation", "failure"),
    (
        ({"metadata_date": REGULAR_DATE}, SnapshotFailureCode.SNAPSHOT_DATE_MISMATCH),
        ({"exchange": "bse"}, SnapshotFailureCode.SNAPSHOT_EXCHANGE_MISMATCH),
        ({"symbol_count": 99}, SnapshotFailureCode.SNAPSHOT_SYMBOL_COUNT_MISMATCH),
        (
            {"candle_close": 109.0},
            SnapshotFailureCode.SNAPSHOT_CANDLE_CONTENT_MISMATCH,
        ),
        (
            {"source_database": "/different/truth.duckdb"},
            SnapshotFailureCode.SNAPSHOT_METADATA_MISMATCH,
        ),
    ),
)
def test_checksum_valid_snapshot_mismatches_fail_closed(
    tmp_path: Path,
    mutation: dict[str, object],
    failure: SnapshotFailureCode,
) -> None:
    warehouse = _canonical(tmp_path)
    calendar = _calendar_report(tmp_path)
    engine, snapshots = _engine(tmp_path, warehouse)
    _persist_mutated(snapshots, SPECIAL_DATE, **mutation)  # type: ignore[arg-type]

    record = engine.run(
        calendar,
        start_date=SPECIAL_DATE,
        end_date=SPECIAL_DATE,
    ).records[0]

    assert record.snapshot_failure_code is failure


def test_unreadable_snapshot_is_rejected(tmp_path: Path) -> None:
    warehouse = _canonical(tmp_path)
    calendar = _calendar_report(tmp_path)
    engine, snapshots = _engine(tmp_path, warehouse)
    path = snapshots.path_for(SPECIAL_DATE)
    path.parent.mkdir(parents=True)
    path.write_text("{not-json", encoding="utf-8")

    record = engine.run(
        calendar,
        start_date=SPECIAL_DATE,
        end_date=SPECIAL_DATE,
    ).records[0]

    assert record.snapshot_failure_code is SnapshotFailureCode.SNAPSHOT_READ_FAILED


def test_immutable_persist_conflict_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warehouse = _canonical(tmp_path)
    calendar = _calendar_report(tmp_path)
    engine, snapshots = _engine(tmp_path, warehouse)

    def conflict(snapshot: ImmutableMarketSnapshot) -> Path:
        del snapshot
        raise FileExistsError("immutable conflict")

    monkeypatch.setattr(snapshots, "persist", conflict)
    record = engine.run(
        calendar,
        start_date=SPECIAL_DATE,
        end_date=SPECIAL_DATE,
    ).records[0]

    assert record.snapshot_failure_code is (
        SnapshotFailureCode.IMMUTABLE_SNAPSHOT_CONFLICT
    )
    assert record.snapshot_status is SnapshotParityStatus.CONFLICT


def test_replay_initializes_only_after_all_missing_snapshots_are_repaired(
    tmp_path: Path,
) -> None:
    warehouse = _canonical(tmp_path, (REGULAR_DATE, SPECIAL_DATE))
    calendar = _calendar_report(tmp_path)
    engine, snapshots = _engine(tmp_path, warehouse)
    snapshots.persist(snapshots.build(REGULAR_DATE, generated_at=FIXED_TIME))
    with pytest.raises(ValueError, match="immutable snapshot missing"):
        HistoricalTruthReplayStore(
            database_path=warehouse.database_path,
            snapshot_root=snapshots.snapshot_root,
            start=REGULAR_DATE,
            end=SPECIAL_DATE,
        )

    report = engine.run(
        calendar,
        start_date=REGULAR_DATE,
        end_date=SPECIAL_DATE,
    )
    replay = HistoricalTruthReplayStore(
        database_path=warehouse.database_path,
        snapshot_root=snapshots.snapshot_root,
        start=REGULAR_DATE,
        end=SPECIAL_DATE,
    )

    assert report.complete
    assert replay.manifest().sessions == 2
    replay.close()


def test_exports_and_cli_are_deterministic_and_policy_isolated(
    tmp_path: Path,
) -> None:
    warehouse = _canonical(tmp_path)
    calendar = _calendar_report(tmp_path)
    engine, _ = _engine(tmp_path, warehouse)
    report = engine.run(
        calendar,
        start_date=SPECIAL_DATE,
        end_date=SPECIAL_DATE,
    )
    paths = engine.export(report, tmp_path / "artifacts")

    assert len(paths) == 7
    assert all(path.exists() for path in paths)
    assert PRODUCTION_INFLUENCE is False
    help_result = CliRunner().invoke(historical_truth_app, ["--help"])
    assert help_result.exit_code == 0
    assert "special-session-snapshot-repair" in help_result.stdout
