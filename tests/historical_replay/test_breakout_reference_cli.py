from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from typer.testing import CliRunner

import alpha.cli as cli_module
from alpha.cli import app
from alpha.historical_replay import (
    BreakoutReconstructionCandidate,
    BreakoutReferenceConfiguration,
    BreakoutReferencePersistenceResult,
    BreakoutReferenceRepository,
    BreakoutReferenceSourceRun,
    HistoricalSecurityIdentity,
    PointInTimeBreakoutReferenceEngine,
    audit_breakout_reference_integrity,
    source_bar_from_values,
)


def _record():  # type: ignore[no-untyped-def]
    sessions = tuple(date(2024, 1, 1) + timedelta(days=index) for index in range(30))
    sessions = tuple(day for day in sessions if day.weekday() < 5)
    bars = tuple(
        source_bar_from_values(
            observed_on=day,
            open_price=100 + index,
            high_price=120 if index == 12 else 102 + index,
            low_price=99 + index,
            close_price=101 + index,
            volume=1000 + index,
        )
        for index, day in enumerate(sessions[:-1])
    )
    return PointInTimeBreakoutReferenceEngine(
        BreakoutReferenceConfiguration(
            minimum_lookback=10,
            reference_lookback=20,
        ),
        clock=datetime(2026, 1, 1, tzinfo=UTC),
    ).reconstruct(
        candidate=BreakoutReconstructionCandidate(
            replay_run_id="historical_replay|2024-01-29",
            candidate_id="cli-candidate",
            historical_symbol="CLITEST",
            observation_date=sessions[-1],
        ),
        bars=bars,
        identity=HistoricalSecurityIdentity(
            instrument_identifier="NSE-CLI",
            historical_symbol="CLITEST",
            exchange="NSE",
            security_master_version="pit-v1",
            evidence_reference="store#NSE-CLI",
            resolved=True,
        ),
        exchange_sessions=sessions,
    )


def _dataset(tmp_path: Path, monkeypatch) -> Path:  # type: ignore[no-untyped-def]
    path = tmp_path / "breakout-reference.json"
    BreakoutReferenceRepository(path).save_records((_record(),))
    monkeypatch.setenv("ALPHA_BREAKOUT_REFERENCE_DATASET", str(path))
    return path


def test_reconstruction_command_renders_dry_run(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    record = _record()
    persistence = BreakoutReferencePersistenceResult(
        path=tmp_path / "unused.json",
        created=1,
        reused=0,
        skipped=0,
        excluded=0,
        failed=0,
        dry_run=True,
        total_records=1,
    )
    source_run = BreakoutReferenceSourceRun(
        selected_candidates=1,
        records=(record,),
        integrity=audit_breakout_reference_integrity((record,)),
        persistence=persistence,
    )
    monkeypatch.setattr(
        cli_module,
        "reconstruct_breakout_references_from_project_sources",
        lambda **_: source_run,
    )

    result = CliRunner().invoke(
        app,
        ["replay", "breakout-reference-reconstruct", "--dry-run", "--limit", "1"],
    )

    assert result.exit_code == 0, result.output
    assert "Point-in-Time Breakout Reference Reconstruction" in result.output
    assert "DRY RUN - no records written" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output


def test_readiness_integrity_provenance_and_sample_commands(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    _dataset(tmp_path, monkeypatch)
    monkeypatch.setattr(cli_module, "count_filtered_replay_candidates", lambda **_: 1)
    runner = CliRunner()

    readiness = runner.invoke(app, ["replay", "breakout-reference-readiness"])
    integrity = runner.invoke(app, ["replay", "breakout-reference-integrity"])
    provenance = runner.invoke(app, ["replay", "breakout-reference-provenance"])
    sample = runner.invoke(app, ["replay", "breakout-reference-sample", "--limit", "1"])

    assert readiness.exit_code == 0, readiness.output
    assert "Overall Readiness Conclusion" in readiness.output
    assert integrity.exit_code == 0, integrity.output
    assert "Overall Integrity: PASS" in integrity.output
    assert provenance.exit_code == 0, provenance.output
    assert "raw_checksum=" in provenance.output
    assert sample.exit_code == 0, sample.output
    assert "CLITEST" in sample.output


def test_json_and_csv_exports_are_deterministic(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _dataset(tmp_path, monkeypatch)
    json_path = tmp_path / "sample.json"
    csv_path = tmp_path / "sample.csv"
    runner = CliRunner()

    json_result = runner.invoke(
        app,
        [
            "replay",
            "breakout-reference-sample",
            "--format",
            "json",
            "--output",
            str(json_path),
        ],
    )
    csv_result = runner.invoke(
        app,
        [
            "replay",
            "breakout-reference-sample",
            "--format",
            "csv",
            "--output",
            str(csv_path),
        ],
    )

    assert json_result.exit_code == 0, json_result.output
    assert csv_result.exit_code == 0, csv_result.output
    assert json.loads(json_path.read_text())[0]["candidate_id"] == "cli-candidate"
    assert csv_path.read_text().splitlines()[1].startswith("cli-candidate,")


def test_invalid_date_range_method_and_candidate_fail_clearly(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    _dataset(tmp_path, monkeypatch)
    runner = CliRunner()

    invalid_range = runner.invoke(
        app,
        [
            "replay",
            "breakout-reference-readiness",
            "--from-date",
            "2024-02-01",
            "--to-date",
            "2024-01-01",
        ],
    )
    invalid_method = runner.invoke(
        app,
        [
            "replay",
            "breakout-reference-reconstruct",
            "--reference-method",
            "future-best-level",
        ],
    )
    invalid_candidate = runner.invoke(
        app,
        [
            "replay",
            "breakout-reference-sample",
            "--candidate-id",
            "not-a-candidate",
        ],
    )

    assert invalid_range.exit_code != 0
    assert "to_date must be on or after from_date" in invalid_range.output
    assert invalid_method.exit_code != 0
    assert "unsupported reference method" in invalid_method.output
    assert invalid_candidate.exit_code != 0
    assert "candidate id not found" in invalid_candidate.output
