from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from alpha.historical_truth.cli import historical_truth_app
from alpha.historical_truth.complete_security_dataset_engine import (
    CompleteSecurityDatasetCertificationEngine,
    _verify_source_checksums,
)
from alpha.historical_truth.complete_security_dataset_exports import (
    CompleteSecurityDatasetArtifactExporter,
)
from alpha.historical_truth.complete_security_dataset_models import (
    CandleReconciliationState,
    IdentityState,
    MembershipState,
)
from alpha.historical_truth.complete_security_dataset_sources import (
    CompleteDatasetSourceInventory,
    DiscoverySourceSpec,
)

ISIN_A = "INE000A01018"
ISIN_B = "INE000B01017"


def _database(path: Path) -> Path:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """CREATE TABLE daily_candle(
                trading_date DATE, exchange VARCHAR, symbol VARCHAR,
                series VARCHAR, isin VARCHAR, open_price DOUBLE,
                high_price DOUBLE, low_price DOUBLE, close_price DOUBLE,
                volume BIGINT, source_sha256 VARCHAR)"""
        )
        connection.execute(
            """CREATE TABLE security_event(
                contract_version VARCHAR, event_id VARCHAR, exchange VARCHAR,
                event_type VARCHAR, effective_date DATE, announcement_date DATE,
                old_symbol VARCHAR, new_symbol VARCHAR, old_series VARCHAR,
                new_series VARCHAR, old_isin VARCHAR, new_isin VARCHAR,
                security_name VARCHAR, predecessor_identity VARCHAR,
                successor_identity VARCHAR, membership_effect VARCHAR,
                tradability_effect VARCHAR, official_source_id VARCHAR,
                document_location VARCHAR, admission_state VARCHAR,
                confidence_state VARCHAR)"""
        )
        connection.execute(
            """CREATE TABLE security_symbol_interval(
                contract_version VARCHAR, identity_key VARCHAR, symbol VARCHAR,
                valid_from DATE, valid_to DATE, source_event_ids VARCHAR,
                confidence_state VARCHAR, issue_codes VARCHAR)"""
        )
        connection.execute(
            """CREATE TABLE security_series_interval(
                contract_version VARCHAR, identity_key VARCHAR, series VARCHAR,
                valid_from DATE, valid_to DATE, source_event_ids VARCHAR,
                confidence_state VARCHAR, issue_codes VARCHAR)"""
        )
        connection.execute(
            """CREATE TABLE security_membership_interval(
                contract_version VARCHAR, identity_key VARCHAR, valid_from DATE,
                valid_to DATE, state VARCHAR, source_event_ids VARCHAR,
                identity_days BIGINT, issue_codes VARCHAR)"""
        )
        connection.execute(
            """CREATE TABLE security_tradability_interval(
                contract_version VARCHAR, identity_key VARCHAR, valid_from DATE,
                valid_to DATE, tradable BOOLEAN, state VARCHAR,
                source_event_ids VARCHAR, identity_days BIGINT,
                issue_codes VARCHAR)"""
        )
    return path


def _calendar(path: Path, *, end: date = date(2016, 1, 8)) -> Path:
    records = []
    current = date(2016, 1, 1)
    while current <= end:
        records.append(
            {
                "trading_date": current.isoformat(),
                "classification": (
                    "regular_session" if current.weekday() < 5 else "weekend"
                ),
            }
        )
        current = date.fromordinal(current.toordinal() + 1)
    path.write_text(json.dumps({"records": records, "sources": []}))
    return path


def _candle(
    connection: duckdb.DuckDBPyConnection,
    trading_date: date,
    symbol: str,
    isin: str | None,
    *,
    series: str = "EQ",
) -> None:
    connection.execute(
        "INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [trading_date, "NSE", symbol, series, isin, 100, 102, 99, 101, 1_000, "abc"],
    )


def _governed_identity(
    connection: duckdb.DuckDBPyConnection,
    *,
    symbol: str = "ALPHA",
    isin: str = ISIN_A,
    listed: date = date(2016, 1, 1),
    end: date = date(2016, 1, 8),
) -> None:
    key = f"nse:isin:{isin}"
    connection.execute(
        "INSERT INTO security_event VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            "HTR-009A2-v1.0.0",
            "event-1",
            "NSE",
            "LISTED",
            listed,
            listed,
            None,
            symbol,
            None,
            "EQ",
            None,
            isin,
            f"{symbol} LIMITED",
            None,
            None,
            "OPEN",
            "OPEN",
            "official-listing",
            "fixture",
            "ADMITTED",
            "HIGH",
        ],
    )
    interval = ["HTR-009A2-v1.0.0", key, listed, end]
    connection.execute(
        "INSERT INTO security_symbol_interval VALUES (?,?,?,?,?,?,?,?)",
        [interval[0], key, symbol, listed, end, '["event-1"]', "HIGH", "[]"],
    )
    connection.execute(
        "INSERT INTO security_series_interval VALUES (?,?,?,?,?,?,?,?)",
        [interval[0], key, "EQ", listed, end, '["event-1"]', "HIGH", "[]"],
    )
    connection.execute(
        "INSERT INTO security_membership_interval VALUES (?,?,?,?,?,?,?,?)",
        [*interval, "CERTIFIED_ACTIVE_TRADABLE", '["event-1"]', 8, "[]"],
    )
    connection.execute(
        "INSERT INTO security_tradability_interval VALUES (?,?,?,?,?,?,?,?,?)",
        [*interval, True, "CERTIFIED_ACTIVE_TRADABLE", '["event-1"]', 8, "[]"],
    )


def _run(tmp_path: Path, *, configure: bool = True):
    database = _database(tmp_path / "truth.duckdb")
    with duckdb.connect(str(database)) as connection:
        _candle(connection, date(2016, 1, 4), "ALPHA", ISIN_A)
        _candle(connection, date(2016, 1, 5), "ALPHA", ISIN_A)
        if configure:
            _governed_identity(connection)
    root = tmp_path / "alpha_data"
    root.mkdir()
    report = CompleteSecurityDatasetCertificationEngine(database, root).run(
        calendar_report=_calendar(tmp_path / "calendar.json"),
        snapshot_root=root / "snapshots",
        start_date=date(2016, 1, 1),
        requested_end=date(2016, 1, 8),
        refresh_sources=False,
        verify_only=False,
    )
    return database, root, report


def test_governed_identity_and_certified_candles(tmp_path: Path) -> None:
    _, _, report = _run(tmp_path)
    identity = next(item for item in report.identities if item.isin == ISIN_A)
    assert identity.identity_state is IdentityState.GOVERNED_IDENTITY
    assert identity.candidate_independent is True
    assert report.candle_summary.certified_rows == 2
    assert report.production_influence is False


def test_candle_only_security_is_not_membership_certified(tmp_path: Path) -> None:
    _, _, report = _run(tmp_path, configure=False)
    assert report.identities[0].identity_state is IdentityState.PROVISIONAL_IDENTITY
    assert (
        report.membership_intervals[0].state
        is MembershipState.UNRESOLVED_NO_LISTING_EVIDENCE
    )
    assert (
        report.candle_reconciliation[0].state
        is CandleReconciliationState.PROVISIONAL_IN_INTERVAL
    )


def test_missing_isin_receives_stable_synthetic_identity(tmp_path: Path) -> None:
    database = _database(tmp_path / "truth.duckdb")
    with duckdb.connect(str(database)) as connection:
        _candle(connection, date(2016, 1, 4), "NOISIN", None)
    root = tmp_path / "alpha_data"
    root.mkdir()
    engine = CompleteSecurityDatasetCertificationEngine(database, root)
    kwargs = {
        "calendar_report": _calendar(tmp_path / "calendar.json"),
        "snapshot_root": root / "snapshots",
        "start_date": date(2016, 1, 1),
        "requested_end": date(2016, 1, 8),
        "refresh_sources": False,
        "verify_only": False,
    }
    first = engine.run(**kwargs)
    second = engine.run(**kwargs)
    assert first.identities[0].identity_key == second.identities[0].identity_key
    assert first.identities[0].identity_state is IdentityState.MISSING_IDENTITY_EVIDENCE


def test_same_symbol_different_isin_is_never_joined(tmp_path: Path) -> None:
    database = _database(tmp_path / "truth.duckdb")
    with duckdb.connect(str(database)) as connection:
        _candle(connection, date(2016, 1, 4), "REUSED", ISIN_A)
        _candle(connection, date(2016, 1, 5), "REUSED", ISIN_B)
    root = tmp_path / "alpha_data"
    root.mkdir()
    report = CompleteSecurityDatasetCertificationEngine(database, root).run(
        calendar_report=_calendar(tmp_path / "calendar.json"),
        snapshot_root=root / "snapshots",
        start_date=date(2016, 1, 1),
        requested_end=date(2016, 1, 8),
        refresh_sources=False,
        verify_only=False,
    )
    assert {item.identity_key for item in report.identities} == {
        f"nse:isin:{ISIN_A}",
        f"nse:isin:{ISIN_B}",
    }
    assert len(report.symbol_reuse) == 1


def test_unsupported_series_is_explicit(tmp_path: Path) -> None:
    database = _database(tmp_path / "truth.duckdb")
    with duckdb.connect(str(database)) as connection:
        _candle(connection, date(2016, 1, 4), "BOND", ISIN_A, series="N1")
    root = tmp_path / "alpha_data"
    root.mkdir()
    report = CompleteSecurityDatasetCertificationEngine(database, root).run(
        calendar_report=_calendar(tmp_path / "calendar.json"),
        snapshot_root=root / "snapshots",
        start_date=date(2016, 1, 1),
        requested_end=date(2016, 1, 8),
        refresh_sources=False,
        verify_only=False,
    )
    assert report.population_summary.unsupported_security_types == 1
    assert report.candle_summary.unsupported_series_rows == 1


def test_point_in_time_view_does_not_show_future_listing(tmp_path: Path) -> None:
    database, _, _ = _run(tmp_path)
    with duckdb.connect(str(database), read_only=True) as connection:
        before = connection.execute(
            """SELECT COUNT(*) FROM complete_point_in_time_universe
               WHERE ? BETWEEN valid_from AND valid_to""",
            [date(2015, 12, 31)],
        ).fetchone()
        during = connection.execute(
            """SELECT COUNT(*) FROM complete_point_in_time_universe
               WHERE ? BETWEEN valid_from AND valid_to""",
            [date(2016, 1, 4)],
        ).fetchone()
    assert before == (0,)
    assert during and during[0] >= 1


def test_last_candle_is_not_treated_as_termination(tmp_path: Path) -> None:
    _, _, report = _run(tmp_path, configure=False)
    assert report.terminations == ()
    assert report.certification_matrix[0].termination_coverage == "UNKNOWN_OR_ACTIVE"


def test_verify_only_reuses_persisted_report(tmp_path: Path) -> None:
    database, root, report = _run(tmp_path)
    reused = CompleteSecurityDatasetCertificationEngine(database, root).run(
        calendar_report=tmp_path / "missing-is-not-read.json",
        snapshot_root=root / "snapshots",
        start_date=date(2016, 1, 1),
        requested_end=None,
        refresh_sources=False,
        verify_only=True,
    )
    assert reused.report_sha256 == report.report_sha256


def test_verify_only_rejects_changed_source_bytes(tmp_path: Path) -> None:
    database, root, _ = _run(tmp_path)
    source = root / "raw" / "nse" / "security_identity" / "historical"
    source.mkdir(parents=True)
    # Persist a report carrying an immutable source, then alter the retained bytes.
    store = CompleteDatasetSourceInventory(root)
    spec = DiscoverySourceSpec(
        "test-source",
        "SUSPENSION_AND_RESTORATION",
        "https://www.nseindia.com/regulations/listing-compliance",
        "fixture-v1",
    )
    acquired = store._acquire(spec, _Session())  # noqa: SLF001
    assert acquired.source_path
    Path(acquired.source_path).write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        _verify_source_checksums((acquired,))


def test_exports_are_deterministic(tmp_path: Path) -> None:
    _, _, report = _run(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    CompleteSecurityDatasetArtifactExporter().export(report, first)
    CompleteSecurityDatasetArtifactExporter().export(report, second)
    assert (first / "htr010a_certification.json").read_bytes() == (
        second / "htr010a_certification.json"
    ).read_bytes()
    assert len(tuple(first.iterdir())) == 38


def test_cli_prints_governance_and_zero_replays(tmp_path: Path) -> None:
    database = _database(tmp_path / "truth.duckdb")
    with duckdb.connect(str(database)) as connection:
        _candle(connection, date(2016, 1, 4), "ALPHA", ISIN_A)
        _governed_identity(connection)
    root = tmp_path / "alpha_data"
    root.mkdir()
    result = CliRunner().invoke(
        historical_truth_app,
        [
            "complete-security-dataset-certify",
            "--database",
            str(database),
            "--calendar-report",
            str(_calendar(tmp_path / "calendar.json")),
            "--snapshot-root",
            str(root / "snapshots"),
            "--root",
            str(root),
            "--start",
            "2016-01-01",
            "--end",
            "2016-01-08",
            "--output",
            str(tmp_path / "artifacts"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Candidate-shaped acquisition: false" in result.output
    assert "Full benchmark replays run: 0" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output


class _Response:
    status_code = 200
    content = b"<html>official suspension index</html>"
    headers = {"Content-Type": "text/html"}
    url = "https://www.nseindia.com/regulations/listing-compliance"
    history: tuple[object, ...] = ()

    def raise_for_status(self) -> None:
        return None


class _Session:
    def get(self, *_args: object, **_kwargs: object) -> _Response:
        return _Response()


def test_official_discovery_bytes_are_immutable_and_reusable(tmp_path: Path) -> None:
    store = CompleteDatasetSourceInventory(
        tmp_path,
        now=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    spec = DiscoverySourceSpec(
        "test-source",
        "SUSPENSION_AND_RESTORATION",
        "https://www.nseindia.com/regulations/listing-compliance",
        "fixture-v1",
    )
    acquired = store._acquire(spec, _Session())  # noqa: SLF001
    reused = store._reuse_or_missing(spec)  # noqa: SLF001
    assert acquired.sha256 == reused.sha256
    assert (
        acquired.source_path
        and Path(acquired.source_path).read_bytes() == _Response.content
    )


def test_no_candidate_tables_are_required(tmp_path: Path) -> None:
    database, _, report = _run(tmp_path)
    with duckdb.connect(str(database), read_only=True) as connection:
        candidate_tables = connection.execute(
            """SELECT COUNT(*) FROM information_schema.tables
               WHERE table_name LIKE '%candidate%'"""
        ).fetchone()
    assert candidate_tables == (0,)
    assert all(item.candidate_independent for item in report.identities)


@pytest.mark.parametrize("state", ["GOVERNED_IDENTITY", "PROVISIONAL_IDENTITY"])
def test_identity_state_filter_is_diagnostic_only(tmp_path: Path, state: str) -> None:
    database, root, full = _run(tmp_path)
    filtered = CompleteSecurityDatasetCertificationEngine(database, root).run(
        calendar_report=tmp_path / "unused.json",
        snapshot_root=root / "snapshots",
        start_date=date(2016, 1, 1),
        requested_end=None,
        refresh_sources=False,
        verify_only=True,
        identity_states=(IdentityState(state),),
    )
    assert len(filtered.identities) <= len(full.identities)
    with duckdb.connect(str(database), read_only=True) as connection:
        persisted = connection.execute(
            "SELECT COUNT(*) FROM complete_security_identity"
        ).fetchone()
    assert persisted == (len(full.identities),)
