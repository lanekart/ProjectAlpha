from __future__ import annotations

import csv
import json
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.cli import historical_truth_app
from alpha.historical_truth.replay_eligibility_exports import (
    ReplayEligibilityArtifactExporter,
)
from alpha.historical_truth.replay_eligibility_integrity import (
    ReplayEligibilityIntegrityEngine,
)
from alpha.historical_truth.replay_eligibility_models import (
    CANONICAL_MINIMUM_HISTORY_SESSIONS,
    PRODUCTION_INFLUENCE,
    CertificationState,
    CorporateActionSeverity,
    EligibilityAuditPolicy,
    ReplayEligibilityIntegrityReport,
    ReplayReadinessClassification,
    SurvivorshipRisk,
)
from alpha.historical_truth.snapshots import PointInTimeSnapshotEngine


@pytest.fixture(scope="module")
def evidence(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    root = tmp_path_factory.mktemp("htr008")
    database = root / "historical_truth.duckdb"
    snapshots_root = root / "snapshots"
    benchmark = root / "benchmark"
    calendar = root / "calendar.json"
    sessions = _sessions(210)
    _build_database(database, sessions)
    warehouse = CanonicalPointInTimeWarehouse(database)
    snapshot_engine = PointInTimeSnapshotEngine(warehouse, snapshots_root)
    for trading_date in sessions:
        snapshot_engine.persist(
            snapshot_engine.build(
                trading_date,
                generated_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
    _calendar(calendar, sessions)
    _benchmark(benchmark, sessions)
    engine = ReplayEligibilityIntegrityEngine(
        database,
        snapshots_root,
        policy=EligibilityAuditPolicy(
            minimum_history_sessions=CANONICAL_MINIMUM_HISTORY_SESSIONS,
            maximum_unexplained_gap_sessions=5,
        ),
    )
    report = engine.run(
        calendar_report=calendar,
        benchmark_output=benchmark,
        start_date=sessions[0],
        end_date=sessions[-1],
    )
    return {
        "root": root,
        "database": database,
        "snapshots": snapshots_root,
        "benchmark": benchmark,
        "calendar": calendar,
        "sessions": sessions,
        "engine": engine,
        "report": report,
    }


def test_stable_governed_identity_is_replay_ready(evidence: dict[str, object]) -> None:
    record = _record(evidence, "INE000A01001")

    assert record.identity_governed is True
    assert record.primary_classification is ReplayReadinessClassification.REPLAY_READY
    assert record.valid_candle_sessions == len(evidence["sessions"])
    assert record.first_200_session_date == evidence["sessions"][199]
    assert record.replay_eligible_security_days == len(evidence["sessions"]) - 199


def test_exact_and_insufficient_point_in_time_depth(
    evidence: dict[str, object],
) -> None:
    exact = _record(evidence, "INE000B01002")
    short = _record(evidence, "INE000C01003")

    assert exact.valid_candle_sessions == 200
    assert exact.first_200_session_date is not None
    assert exact.replay_eligible_security_days == 1
    assert short.valid_candle_sessions == 199
    assert short.first_200_session_date is None
    assert short.primary_classification is (
        ReplayReadinessClassification.INSUFFICIENT_VALID_HISTORY
    )


def test_future_rows_never_satisfy_earlier_history(evidence: dict[str, object]) -> None:
    record = _record(evidence, "INE000A01001")
    sessions = evidence["sessions"]

    assert record.first_20_session_date == sessions[19]
    assert record.first_50_session_date == sessions[49]
    assert record.first_100_session_date == sessions[99]
    assert record.first_150_session_date == sessions[149]
    assert record.first_200_session_date == sessions[199]
    assert record.first_500_session_date is None
    assert record.first_1000_session_date is None


def test_internal_gaps_are_measured_on_official_sessions(
    evidence: dict[str, object],
) -> None:
    record = _record(evidence, "INE000D01004")

    assert record.valid_candle_sessions == 200
    assert record.unexplained_missing_sessions == 10
    assert record.longest_unexplained_internal_gap == 10
    assert record.unexplained_internal_gap_count == 1
    assert record.primary_classification is (
        ReplayReadinessClassification.INTERNAL_CANDLE_GAPS
    )


def test_invalid_candle_and_unsupported_series_fail_visible(
    evidence: dict[str, object],
) -> None:
    invalid = _record(evidence, "INE000E01005")
    unsupported = _record(evidence, "INE000F01006")

    assert invalid.invalid_candle_sessions == 1
    assert invalid.primary_classification is (
        ReplayReadinessClassification.INVALID_CANDLE_CONTAMINATION
    )
    assert unsupported.primary_classification is (
        ReplayReadinessClassification.UNSUPPORTED_SERIES
    )
    assert unsupported.invalid_candle_sessions == 0
    report = evidence["report"]
    assert isinstance(report, ReplayEligibilityIntegrityReport)
    assert report.candle_quality.unsupported_series_ohlc_exceptions == 1


def test_symbol_reuse_and_supported_symbol_change_are_distinguished(
    evidence: dict[str, object],
) -> None:
    reused = _record(evidence, "INE000G01007")
    renamed = _record(evidence, "INE000I01009")
    report = evidence["report"]

    assert reused.primary_classification is (
        ReplayReadinessClassification.SYMBOL_REUSE_CONFLICT
    )
    assert renamed.symbols == ("NEWNAME", "OLDNAME")
    assert renamed.primary_classification is ReplayReadinessClassification.REPLAY_READY
    assert report.population.symbol_reuse_cases == 1
    assert report.population.supported_symbol_changes == 1


def test_identity_overlap_and_future_mapping_leakage_are_detected(
    evidence: dict[str, object],
) -> None:
    overlap = _record(evidence, "INE000J01010")
    future = _record(evidence, "INE000K01011")

    assert overlap.primary_classification is (
        ReplayReadinessClassification.IDENTITY_INTERVAL_OVERLAP
    )
    assert future.identity_governed is False
    assert "CANDLE_OUTSIDE_IDENTITY_INTERVAL" in future.secondary_issue_codes
    assert future.survivorship_risk is SurvivorshipRisk.UNKNOWN


def test_split_discontinuity_is_blocking(evidence: dict[str, object]) -> None:
    record = _record(evidence, "INE000L01012")
    report = evidence["report"]
    action = next(
        item
        for item in report.corporate_actions
        if item.identity_key == record.identity_key
    )

    assert action.event_type == "SPLIT"
    assert action.severity is CorporateActionSeverity.BLOCKING
    assert action.raw_overnight_discontinuity is not None
    assert record.primary_classification is (
        ReplayReadinessClassification.CORPORATE_ACTION_CONTAMINATION
    )


def test_normal_volatility_without_event_is_not_falsely_classified(
    evidence: dict[str, object],
) -> None:
    stable = _record(evidence, "INE000A01001")
    report = evidence["report"]

    assert stable.corporate_action_count == 0
    assert all(
        item.identity_key != stable.identity_key for item in report.corporate_actions
    )
    assert stable.primary_classification is not (
        ReplayReadinessClassification.CORPORATE_ACTION_CONTAMINATION
    )


def test_candidate_exposure_maps_ready_and_blocked_identities(
    evidence: dict[str, object],
) -> None:
    report = evidence["report"]
    by_class = {item.certification_class: item for item in report.candidate_exposure}

    assert by_class["REPLAY_READY"].technical_candidates == 1
    assert by_class["REPLAY_READY"].buy_candidates == 1
    assert by_class["INSUFFICIENT_VALID_HISTORY"].technical_candidates == 1
    assert by_class["CORPORATE_ACTION_CONTAMINATION"].strong_buy_candidates == 1


def test_certification_and_reconciliation_are_diagnostic_only(
    evidence: dict[str, object],
) -> None:
    report = evidence["report"]

    assert report.certification.primary_state is (
        CertificationState.BLOCKED_POINT_IN_TIME_UNIVERSE
    )
    assert report.baseline.eligible_securities == 3
    assert report.reconciliation.identities_with_200_valid_sessions >= 1
    assert report.production_influence is False
    assert PRODUCTION_INFLUENCE is False


def test_snapshot_mismatch_is_reported_without_mutation(
    evidence: dict[str, object],
) -> None:
    engine = evidence["engine"]
    sessions = evidence["sessions"]
    path = engine.snapshots.path_for(sessions[0], exchange="nse")
    before = path.read_bytes()
    payload = json.loads(before)
    payload["content_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    try:
        audit = engine._snapshot_audit(((sessions[0], "regular_session"),))
    finally:
        path.write_bytes(before)

    assert audit.invalid_dates == (sessions[0],)
    assert path.read_bytes() == before


def test_exports_are_deterministic_and_complete(
    evidence: dict[str, object],
) -> None:
    report = evidence["report"]
    root = evidence["root"]
    exporter = ReplayEligibilityArtifactExporter()

    first = exporter.export(report, root / "export-one")
    second = exporter.export(report, root / "export-two")

    assert len(first) == 27
    assert [path.name for path in first] == [path.name for path in second]
    assert [path.read_bytes() for path in first] == [
        path.read_bytes() for path in second
    ]
    assert (root / "export-one" / "htr008_certification.md").is_file()


def test_filters_are_deterministic(evidence: dict[str, object]) -> None:
    engine = evidence["engine"]
    records = evidence["report"].records

    filtered = engine._filter_records(
        records,
        symbols=("AAA",),
        isins=(),
        years=(),
        classifications=(),
        issue_codes=(),
        only_not_ready=False,
    )

    assert len(filtered) == 1
    assert filtered[0].symbol == "AAA"


def test_cli_rejects_minimum_history_change(evidence: dict[str, object]) -> None:
    result = CliRunner().invoke(
        historical_truth_app,
        [
            "replay-eligibility-integrity-audit",
            "--database",
            str(evidence["database"]),
            "--calendar-report",
            str(evidence["calendar"]),
            "--snapshot-root",
            str(evidence["snapshots"]),
            "--benchmark-output",
            str(evidence["benchmark"]),
            "--start",
            str(evidence["sessions"][0]),
            "--end",
            str(evidence["sessions"][-1]),
            "--minimum-history-sessions",
            "199",
        ],
    )

    assert result.exit_code == 2
    assert "HTR-008 preserves" in result.output
    assert "canonical 200-session threshold" in result.output


def test_cli_generates_certification_artifacts(evidence: dict[str, object]) -> None:
    output = evidence["root"] / "cli-output"
    result = CliRunner().invoke(
        historical_truth_app,
        [
            "replay-eligibility-integrity-audit",
            "--database",
            str(evidence["database"]),
            "--calendar-report",
            str(evidence["calendar"]),
            "--snapshot-root",
            str(evidence["snapshots"]),
            "--benchmark-output",
            str(evidence["benchmark"]),
            "--start",
            str(evidence["sessions"][0]),
            "--end",
            str(evidence["sessions"][-1]),
            "--minimum-history-sessions",
            "200",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "HTR-008 Replay Eligibility Integrity" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output
    assert (output / "htr008_replay_eligibility_integrity.json").is_file()
    assert (output / "baseline" / "htr008_baseline.json").is_file()


@pytest.mark.parametrize(
    ("action_type", "discontinuity", "factor", "expected"),
    [
        ("SPLIT", -0.5, 0.5, CorporateActionSeverity.BLOCKING),
        ("BONUS", -0.3, None, CorporateActionSeverity.BLOCKING),
        ("RIGHTS", -0.21, None, CorporateActionSeverity.HIGH),
        ("MERGER", -0.4, None, CorporateActionSeverity.BLOCKING),
        ("DEMERGER", -0.4, None, CorporateActionSeverity.BLOCKING),
        ("SYMBOL_CHANGE", 0.01, None, CorporateActionSeverity.NONE),
    ],
)
def test_corporate_action_severity_is_deterministic(
    action_type: str,
    discontinuity: float,
    factor: float | None,
    expected: CorporateActionSeverity,
) -> None:
    assert (
        ReplayEligibilityIntegrityEngine._action_severity(
            action_type=action_type,
            discontinuity=discontinuity,
            factor=factor,
        )
        is expected
    )


def test_report_hash_changes_when_evidence_changes(evidence: dict[str, object]) -> None:
    report = evidence["report"]
    changed = replace(
        report,
        records=report.records[:-1],
        report_sha256="",
    )

    assert changed.calculated_sha256() != report.report_sha256


def _record(evidence: dict[str, object], isin: str):
    report = evidence["report"]
    return next(record for record in report.records if isin in record.isins)


def _sessions(count: int) -> tuple[date, ...]:
    sessions: list[date] = []
    current = date(2020, 1, 1)
    while len(sessions) < count:
        if current.weekday() < 5:
            sessions.append(current)
        current += timedelta(days=1)
    special = date(2020, 3, 7)
    sessions.append(special)
    return tuple(sorted(sessions))


def _build_database(database: Path, sessions: tuple[date, ...]) -> None:
    warehouse = CanonicalPointInTimeWarehouse(database)
    warehouse.initialise()
    candles: list[tuple[object, ...]] = []
    lineage: list[tuple[object, ...]] = []

    def add(
        symbol: str,
        isin: str | None,
        selected: tuple[date, ...],
        *,
        series: str = "EQ",
        invalid_on: date | None = None,
        split_on: date | None = None,
    ) -> None:
        for index, trading_date in enumerate(selected):
            price = 100.0 + index / 10
            if split_on is not None and trading_date >= split_on:
                price /= 2
            high = price + 2
            low = price - 2
            close = price + 1
            if trading_date == invalid_on:
                high = price - 3
            row = (
                trading_date,
                "nse",
                symbol,
                series,
                isin,
                price,
                high,
                low,
                close,
                1000 + index,
                "source",
            )
            candles.append(row)
            lineage.append(
                (
                    trading_date,
                    "nse",
                    symbol,
                    series,
                    "source",
                    "https://nse.example/source",
                    "raw/source.csv",
                    "normalized/source.csv",
                )
            )

    add("AAA", "INE000A01001", sessions)
    add("EXACT", "INE000B01002", sessions[:200])
    add("SHORT", "INE000C01003", sessions[:199])
    add("GAP", "INE000D01004", sessions[:100] + sessions[110:210])
    add("BAD", "INE000E01005", sessions, invalid_on=sessions[100])
    add(
        "BESERIES",
        "INE000F01006",
        sessions,
        series="BE",
        invalid_on=sessions[100],
    )
    add("REUSE", "INE000G01007", sessions[:100])
    add("REUSE", "INE000H01008", sessions[110:])
    add("OLDNAME", "INE000I01009", sessions[:100])
    add("NEWNAME", "INE000I01009", sessions[100:])
    add("OVERA", "INE000J01010", sessions[:110])
    add("OVERB", "INE000J01010", sessions[100:])
    add("FUTURE", "INE000K01011", sessions)
    add("SPLIT", "INE000L01012", sessions, split_on=sessions[105])
    add("NOISIN", None, sessions)

    identities = [
        ("nse", "AAA", "EQ", "INE000A01001", sessions[0], sessions[-1]),
        ("nse", "EXACT", "EQ", "INE000B01002", sessions[0], sessions[199]),
        ("nse", "SHORT", "EQ", "INE000C01003", sessions[0], sessions[198]),
        ("nse", "GAP", "EQ", "INE000D01004", sessions[0], sessions[209]),
        ("nse", "BAD", "EQ", "INE000E01005", sessions[0], sessions[-1]),
        ("nse", "BESERIES", "BE", "INE000F01006", sessions[0], sessions[-1]),
        ("nse", "REUSE", "EQ", "INE000G01007", sessions[0], sessions[99]),
        ("nse", "REUSE", "EQ", "INE000H01008", sessions[110], sessions[-1]),
        ("nse", "OLDNAME", "EQ", "INE000I01009", sessions[0], sessions[99]),
        ("nse", "NEWNAME", "EQ", "INE000I01009", sessions[100], sessions[-1]),
        ("nse", "OVERA", "EQ", "INE000J01010", sessions[0], sessions[109]),
        ("nse", "OVERB", "EQ", "INE000J01010", sessions[100], sessions[-1]),
        ("nse", "FUTURE", "EQ", "INE000K01011", sessions[20], sessions[-1]),
        ("nse", "SPLIT", "EQ", "INE000L01012", sessions[0], sessions[-1]),
    ]
    with duckdb.connect(str(database)) as connection:
        connection.executemany(
            "INSERT INTO daily_candle VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            candles,
        )
        connection.executemany(
            "INSERT INTO candle_ingestion_lineage VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            lineage,
        )
        connection.executemany(
            "INSERT INTO security_identity VALUES (?, ?, ?, ?, ?, ?)",
            identities,
        )
        connection.execute(
            """
            INSERT INTO corporate_action VALUES (
                'nse', 'INE000L01012', 'SPLIT', 'SPLIT', ?, 2, 1, 'action-source'
            )
            """,
            [sessions[105]],
        )


def _calendar(path: Path, sessions: tuple[date, ...]) -> None:
    records = [
        {
            "trading_date": str(trading_date),
            "classification": (
                "special_session" if trading_date.weekday() >= 5 else "regular_session"
            ),
            "observed_candles": True,
        }
        for trading_date in sessions
    ]
    path.write_text(
        json.dumps(
            {
                "certification_state": "certified",
                "expected_session_count": len(sessions),
                "records": records,
            }
        ),
        encoding="utf-8",
    )


def _benchmark(path: Path, sessions: tuple[date, ...]) -> None:
    path.mkdir()
    (path / "decision_eligibility.csv").write_text(
        "status,minimum_complete_history_sessions,replay_sessions,"
        "eligible_securities,eligible_security_days,raw_technical_candidates,"
        "raw_buy_or_strong_buy_signals,institutional_approvals,production_influence\n"
        f"ELIGIBLE_POPULATION_AVAILABLE,200,{len(sessions)},3,13,3,2,0,False\n",
        encoding="utf-8",
    )
    approvals = [
        (sessions[-1], "AAA", "BUY"),
        (sessions[198], "SHORT", "WATCHLIST"),
        (sessions[-1], "SPLIT", "STRONG_BUY"),
    ]
    with (path / "approval_statistics.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(
            [
                "observed_on",
                "symbol",
                "approved",
                "opportunity_score",
                "opportunity_grade",
                "final_signal",
                "primary_reason_code",
                "rejection_category",
                "explanation",
            ]
        )
        for trading_date, symbol, signal in approvals:
            writer.writerow(
                [
                    trading_date,
                    symbol,
                    False,
                    70,
                    "REJECT",
                    signal,
                    "WEAK",
                    "Test",
                    "Test",
                ]
            )
    (path / "top_rejection_reasons.csv").write_text(
        "reason_code,rejected_candidates\nWEAK,3\n",
        encoding="utf-8",
    )
    (path / "trade_log.csv").write_text("symbol,entry_date\n", encoding="utf-8")
    (path / "manifest.json").write_text(
        json.dumps({"run_id": "CABR_TEST"}),
        encoding="utf-8",
    )
