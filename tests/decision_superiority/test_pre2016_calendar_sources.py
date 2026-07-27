from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import duckdb
import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.decision_superiority.pre2016_calendar_sources import (
    build_reviewed_official_calendar_source,
    discover_pre2016_calendar_evidence,
    export_pre2016_calendar_discovery,
)
from alpha.decision_superiority.pre2016_external_validation_models import (
    Pre2016ExternalValidationError,
)
from alpha.historical_truth.session_calendar import OfficialSessionCalendarEngine


def test_discovery_preserves_unavailable_and_weekend_sessions(tmp_path: Path) -> None:
    database = tmp_path / "historical_truth.duckdb"
    connection = duckdb.connect(str(database))
    try:
        connection.execute("create table daily_candle (trading_date date)")
        connection.execute("insert into daily_candle values (date '2005-01-08')")
    finally:
        connection.close()

    manifest = tmp_path / "archive_manifest.jsonl"
    rows = (
        {
            "exchange": "nse",
            "dataset": "bhavcopy",
            "trading_date": "2005-01-03",
            "status": "downloaded",
        },
        {
            "exchange": "nse",
            "dataset": "bhavcopy",
            "trading_date": "2005-01-26",
            "status": "unavailable",
            "error": "official archive returned HTTP 404",
            "source_url": "https://nsearchives.nseindia.com/example.zip",
        },
    )
    manifest.write_text(
        "".join(json.dumps(row) + "\n" for row in rows),
        encoding="utf-8",
    )

    result = discover_pre2016_calendar_evidence(
        database=database,
        manifest=manifest,
    )

    assert len(result.unavailable_rows) == 1
    assert result.unavailable_rows[0]["manifest_status_normalized"] == "unavailable"
    assert result.unavailable_rows[0]["classification"] == "UNREVIEWED"
    assert result.unavailable_rows[0]["inferred_from_http_404"] is False
    assert len(result.weekend_session_rows) == 1
    assert str(result.weekend_session_rows[0]["trading_date"]) == "2005-01-08"
    assert result.weekend_session_rows[0]["inferred_from_observation"] is False

    paths = export_pre2016_calendar_discovery(result, tmp_path / "output")
    assert len(paths) == 4
    summary = json.loads(paths[-1].read_text(encoding="utf-8"))
    assert summary["archive_unavailable_count"] == 1
    assert summary["observed_weekend_session_count"] == 1
    assert summary["calendar_certification_permitted"] is False


def test_reviewed_source_is_hash_bound_and_calendar_compatible(tmp_path: Path) -> None:
    source_document = tmp_path / "nse_holidays_2005.html"
    source_document.write_text("official NSE holiday circular", encoding="utf-8")
    review_csv = tmp_path / "review.csv"
    _write_review(
        review_csv,
        rows=(
            {
                "trading_date": "2005-01-26",
                "classification": "HOLIDAY",
                "description": "Republic Day",
                "review_state": "VERIFIED_OFFICIAL_EVIDENCE",
            },
            {
                "trading_date": "2005-11-02",
                "classification": "SPECIAL_SESSION",
                "description": "Muhurat Trading",
                "review_state": "VERIFIED_OFFICIAL_EVIDENCE",
            },
        ),
    )
    output = tmp_path / "official_calendar_2005.json"

    path = build_reviewed_official_calendar_source(
        review_csv=review_csv,
        source_document=source_document,
        source_url="https://nsearchives.nseindia.com/content/circulars/example.htm",
        source_id="NSE_CM_2005_CALENDAR",
        covered_years=(2005,),
        output=output,
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["covered_years"] == [2005]
    assert (
        payload["source_document_sha256"]
        == hashlib.sha256(source_document.read_bytes()).hexdigest()
    )
    assert (
        payload["review_csv_sha256"]
        == hashlib.sha256(review_csv.read_bytes()).hexdigest()
    )
    assert payload["classification_inferred_from_archive_status"] is False
    assert payload["classification_inferred_from_observed_candles"] is False

    loaded = OfficialSessionCalendarEngine.load_source(path)
    assert loaded.covered_years == (2005,)
    assert loaded.holidays[0].trading_date.isoformat() == "2005-01-26"
    assert loaded.special_sessions[0].trading_date.isoformat() == "2005-11-02"


def test_source_builder_rejects_nonofficial_url(tmp_path: Path) -> None:
    source_document = tmp_path / "source.html"
    source_document.write_text("source", encoding="utf-8")
    review_csv = tmp_path / "review.csv"
    _write_review(
        review_csv,
        rows=(
            {
                "trading_date": "2005-01-26",
                "classification": "HOLIDAY",
                "description": "Republic Day",
                "review_state": "VERIFIED_OFFICIAL_EVIDENCE",
            },
        ),
    )

    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_OFFICIAL_SOURCE_URL_INVALID",
    ):
        build_reviewed_official_calendar_source(
            review_csv=review_csv,
            source_document=source_document,
            source_url="https://example.com/holidays",
            source_id="NSE_CM_2005_CALENDAR",
            covered_years=(2005,),
            output=tmp_path / "output.json",
        )


def test_source_builder_rejects_unverified_rows(tmp_path: Path) -> None:
    source_document = tmp_path / "source.html"
    source_document.write_text("source", encoding="utf-8")
    review_csv = tmp_path / "review.csv"
    _write_review(
        review_csv,
        rows=(
            {
                "trading_date": "2005-01-26",
                "classification": "HOLIDAY",
                "description": "Republic Day",
                "review_state": "PENDING_OFFICIAL_EVIDENCE",
            },
        ),
    )

    with pytest.raises(
        Pre2016ExternalValidationError,
        match="PRE2016_CALENDAR_REVIEW_NOT_VERIFIED",
    ):
        build_reviewed_official_calendar_source(
            review_csv=review_csv,
            source_document=source_document,
            source_url="https://www.nseindia.com/resources/holidays",
            source_id="NSE_CM_2005_CALENDAR",
            covered_years=(2005,),
            output=tmp_path / "output.json",
        )


def test_calendar_source_commands_are_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])
    assert result.exit_code == 0
    assert "decision-superiority-pre2016-calendar-discovery" in result.stdout
    assert "decision-superiority-pre2016-calendar-source-build" in result.stdout


def _write_review(
    path: Path,
    *,
    rows: tuple[dict[str, str], ...],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "trading_date",
                "classification",
                "description",
                "review_state",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)
