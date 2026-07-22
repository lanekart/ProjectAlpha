from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from alpha.historical_truth.cli import historical_truth_app
from alpha.historical_truth.security_population_repair_engine import (
    SecurityPopulationRepairEngine,
    _policy,
    _support_intervals,
    classify_instrument,
)
from alpha.historical_truth.security_population_repair_exports import (
    SecurityPopulationRepairArtifactExporter,
)
from alpha.historical_truth.security_population_repair_models import (
    InstrumentTaxonomyRecord,
    InstrumentType,
    SupportState,
)

ISIN = "INE000A01018"


@pytest.mark.parametrize(
    ("series", "flag", "name", "isin", "expected"),
    [
        ("EQ", "0", "ALPHA LIMITED", ISIN, InstrumentType.MAINBOARD_EQUITY),
        ("BE", "0", "ALPHA LIMITED", ISIN, InstrumentType.TRADE_FOR_TRADE_EQUITY),
        ("SM", "0", "ALPHA LIMITED", ISIN, InstrumentType.SME_EQUITY),
        ("ST", "0", "ALPHA LIMITED", ISIN, InstrumentType.SME_TRADE_FOR_TRADE),
        ("EQ", "4", "ALPHA ETF", "INF000A01018", InstrumentType.ETF),
        ("RR", "0", "ALPHA REIT", ISIN, InstrumentType.REIT),
        ("IV", "0", "ALPHA INVIT", ISIN, InstrumentType.INVIT),
        ("P1", "1", "PREFERENCE SHARE", ISIN, InstrumentType.PREFERENCE_SHARE),
        ("E1", "0", "PARTLY PAID", ISIN, InstrumentType.PARTLY_PAID_EQUITY),
        ("N1", "2", "ALPHA NCD", ISIN, InstrumentType.CORPORATE_DEBT),
        ("W1", "3", "ALPHA WARRANT", ISIN, InstrumentType.WARRANT),
        ("GB", "4", "SOVEREIGN GOLD", ISIN, InstrumentType.SOVEREIGN_GOLD_BOND),
        ("ZZ", None, "UNKNOWN", None, InstrumentType.UNKNOWN_SECURITY_TYPE),
    ],
)
def test_taxonomy(
    series: str,
    flag: str | None,
    name: str,
    isin: str | None,
    expected: InstrumentType,
) -> None:
    actual, _, _ = classify_instrument(
        symbol="ALPHA",
        series=series,
        isin=isin,
        security_name=name,
        security_type_flag=flag,
        official_instrument_type=None,
    )
    assert actual is expected


def test_rights_and_test_records_override_series() -> None:
    rights = classify_instrument(
        symbol="ALPHA-RE",
        series="EQ",
        isin=ISIN,
        security_name="RIGHTS ENTITLEMENT",
        security_type_flag="0",
        official_instrument_type=None,
    )[0]
    test = classify_instrument(
        symbol="011NSETEST",
        series="EQ",
        isin="DUMMYSAN005",
        security_name="TEST",
        security_type_flag="0",
        official_instrument_type=None,
    )[0]
    assert rights is InstrumentType.RIGHTS_ENTITLEMENT
    assert test is InstrumentType.TEST_OR_ADMINISTRATIVE_RECORD


def test_support_policy_separates_equity_etf_and_debt() -> None:
    def record(kind: InstrumentType) -> InstrumentTaxonomyRecord:
        return InstrumentTaxonomyRecord(
            "nse:isin:" + ISIN,
            "NSE",
            "ALPHA",
            "EQ",
            ISIN,
            "ALPHA",
            "0",
            None,
            kind,
            date(2020, 1, 1),
            None,
            "official",
            "fixture",
            "abc",
            "fixture",
            "HIGH",
            (),
        )

    assert _policy(record(InstrumentType.MAINBOARD_EQUITY)).support_state is (
        SupportState.TIER_A_CORE_EQUITY
    )
    assert _policy(record(InstrumentType.ETF)).support_state is (
        SupportState.SUPPORTED_SEPARATE_ASSET_CLASS
    )
    assert _policy(record(InstrumentType.CORPORATE_DEBT)).support_state is (
        SupportState.PRESERVED_UNSUPPORTED
    )


def test_current_record_is_not_projected_backward() -> None:
    identities = (
        {
            "identity_key": "nse:isin:" + ISIN,
            "first_evidence_date": date(2020, 1, 1),
            "last_evidence_date": date(2020, 1, 2),
        },
    )
    intervals = _support_intervals(
        identities,
        {},
        {"nse:isin:" + ISIN: SupportState.TIER_A_CORE_EQUITY},
        date(2016, 1, 1),
        date(2026, 7, 20),
    )
    assert intervals["nse:isin:" + ISIN] == (
        date(2020, 1, 1),
        date(2020, 1, 2),
        "PROVISIONAL_OBSERVATION_BOUND",
    )


def _database(path: Path) -> Path:
    with duckdb.connect(str(path)) as connection:
        connection.execute(
            """CREATE TABLE complete_security_census(
                contract_version VARCHAR, exchange VARCHAR, symbol VARCHAR,
                series VARCHAR, isin VARCHAR, security_name VARCHAR,
                first_observed DATE, last_observed DATE, candle_rows BIGINT,
                source_ids VARCHAR, source_record_count BIGINT,
                supported_security_type BOOLEAN, identity_key VARCHAR)"""
        )
        connection.execute(
            """CREATE TABLE complete_security_identity(
                contract_version VARCHAR, identity_key VARCHAR, exchange VARCHAR,
                isin VARCHAR, current_symbol VARCHAR, current_series VARCHAR,
                current_name VARCHAR, first_evidence_date DATE,
                last_evidence_date DATE, identity_state VARCHAR,
                secondary_issue_codes VARCHAR, official_source_ids VARCHAR,
                synthetic_reason VARCHAR, candidate_independent BOOLEAN)"""
        )
        connection.execute(
            """CREATE TABLE security_identity_interval_complete(
                contract_version VARCHAR, identity_key VARCHAR, valid_from DATE,
                valid_to DATE, identity_state VARCHAR, source_event_ids VARCHAR,
                issue_codes VARCHAR)"""
        )
        for table in (
            "security_symbol_interval_complete",
            "security_series_interval_complete",
        ):
            connection.execute(
                f"""CREATE TABLE {table}(
                    contract_version VARCHAR, identity_key VARCHAR, value VARCHAR,
                    valid_from DATE, valid_to DATE, confidence_state VARCHAR,
                    source_event_ids VARCHAR, issue_codes VARCHAR)"""
            )
        connection.execute(
            """CREATE TABLE daily_candle(
                trading_date DATE, exchange VARCHAR, symbol VARCHAR, series VARCHAR,
                isin VARCHAR, open_price DOUBLE, high_price DOUBLE, low_price DOUBLE,
                close_price DOUBLE, volume BIGINT, source_sha256 VARCHAR)"""
        )
        key = "nse:isin:" + ISIN
        connection.execute(
            "INSERT INTO complete_security_census VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                "HTR-010A-v1.0.0",
                "NSE",
                "ALPHA",
                "EQ",
                ISIN,
                "ALPHA LIMITED",
                date(2020, 1, 1),
                date(2020, 1, 2),
                2,
                '["canonical_daily_candle"]',
                1,
                True,
                key,
            ],
        )
        connection.execute(
            "INSERT INTO complete_security_identity "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                "HTR-010A-v1.0.0",
                key,
                "NSE",
                ISIN,
                "ALPHA",
                "EQ",
                "ALPHA LIMITED",
                date(2020, 1, 1),
                date(2020, 1, 2),
                "PROVISIONAL_IDENTITY",
                "[]",
                "[]",
                None,
                True,
            ],
        )
        connection.execute(
            "INSERT INTO security_identity_interval_complete VALUES (?,?,?,?,?,?,?)",
            [
                "HTR-010A-v1.0.0",
                key,
                date(2020, 1, 1),
                date(2020, 1, 2),
                "PROVISIONAL_IDENTITY",
                "[]",
                "[]",
            ],
        )
        for table in (
            "security_symbol_interval_complete",
            "security_series_interval_complete",
        ):
            value = "ALPHA" if "symbol" in table else "EQ"
            connection.execute(
                f"INSERT INTO {table} VALUES (?,?,?,?,?,?,?,?)",
                [
                    "HTR-010A-v1.0.0",
                    key,
                    value,
                    date(2020, 1, 1),
                    date(2020, 1, 2),
                    "LOW",
                    "[]",
                    "[]",
                ],
            )
        for trading_date in (date(2020, 1, 1), date(2020, 1, 2)):
            connection.execute(
                "INSERT INTO daily_candle VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [trading_date, "NSE", "ALPHA", "EQ", ISIN, 1, 2, 1, 2, 10, "abc"],
            )
    return path


def _run(tmp_path: Path):
    database = _database(tmp_path / "truth.duckdb")
    root = tmp_path / "alpha_data"
    root.mkdir()
    prior = tmp_path / "htr010a"
    prior.mkdir()
    (prior / "htr010a_symbol_reuse.json").write_text("[]")
    output = tmp_path / "output"
    report = SecurityPopulationRepairEngine(database, root).run(
        htr010a_output=prior,
        start_date=date(2016, 1, 1),
        end_date=date(2026, 7, 20),
        output=output,
        refresh_sources=False,
        verify_only=True,
    )
    return database, root, prior, output, report


def test_engine_preserves_source_database_and_creates_sidecar(tmp_path: Path) -> None:
    database, _, _, output, report = _run(tmp_path)
    with duckdb.connect(str(database), read_only=True) as connection:
        tables = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
    assert "security_instrument_taxonomy" not in tables
    assert (output / "htr010a1_repair.duckdb").exists()
    assert report.production_influence is False
    assert report.population_summary.tier_a_identities == 1
    assert report.report_sha256 == report.calculated_sha256()


def test_exports_are_deterministic_and_complete(tmp_path: Path) -> None:
    _, _, _, _, report = _run(tmp_path)
    first = tmp_path / "first"
    second = tmp_path / "second"
    one = SecurityPopulationRepairArtifactExporter().export(report, first)
    two = SecurityPopulationRepairArtifactExporter().export(report, second)
    assert len(one) == len(two) == 38
    assert (first / "htr010a1_certification.json").read_bytes() == (
        second / "htr010a1_certification.json"
    ).read_bytes()


def test_cli_reports_governance_and_zero_replays(tmp_path: Path) -> None:
    database = _database(tmp_path / "truth.duckdb")
    root = tmp_path / "alpha_data"
    root.mkdir()
    prior = tmp_path / "htr010a"
    prior.mkdir()
    (prior / "htr010a_symbol_reuse.json").write_text(json.dumps([]))
    result = CliRunner().invoke(
        historical_truth_app,
        [
            "security-population-repair",
            "--database",
            str(database),
            "--root",
            str(root),
            "--htr010a-output",
            str(prior),
            "--output",
            str(tmp_path / "artifacts"),
            "--verify-only",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Full benchmark replays run: 0" in result.output
    assert "Candidate-based filtering: false" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output


def test_invalid_cli_date_fails_closed(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        historical_truth_app,
        ["security-population-repair", "--start", "bad-date"],
    )
    assert result.exit_code != 0
