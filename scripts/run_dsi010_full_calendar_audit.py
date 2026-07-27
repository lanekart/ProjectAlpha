from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any

from alpha.decision_superiority.pre2016_calendar_sources import (
    validate_hash_bound_official_calendar_source,
)
from alpha.historical_truth.canonical import CanonicalPointInTimeWarehouse
from alpha.historical_truth.session_calendar import (
    CalendarCertificationState,
    OfficialSessionCalendarEngine,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _write_rows(
    path: Path,
    rows: list[dict[str, object]],
    fields: tuple[str, ...],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _calendar_sources(
    *,
    early_root: Path,
    later_root: Path,
    emergency_source: Path,
    additional_sources: tuple[Path, ...] = (),
    expected_source_count: int = 29,
) -> tuple[Path, ...]:
    early_sources = tuple(sorted((early_root / "sources").glob("*.json")))
    later_sources = tuple(sorted((later_root / "sources").glob("*.json")))
    if len(early_sources) != 15:
        raise RuntimeError(
            f"EXPECTED_15_EARLY_CALENDAR_SOURCES_FOUND_{len(early_sources)}"
        )
    if len(later_sources) != 13:
        raise RuntimeError(
            f"EXPECTED_13_LATER_CALENDAR_SOURCES_FOUND_{len(later_sources)}"
        )
    if not emergency_source.is_file():
        raise RuntimeError("EMERGENCY_CALENDAR_SOURCE_MISSING")
    missing_additional = tuple(
        source for source in additional_sources if not source.is_file()
    )
    if missing_additional:
        raise RuntimeError(
            "ADDITIONAL_CALENDAR_SOURCE_MISSING:"
            + ",".join(str(source) for source in missing_additional)
        )
    source_paths = (
        *early_sources,
        *later_sources,
        emergency_source,
        *additional_sources,
    )
    if len(source_paths) != expected_source_count:
        raise RuntimeError(
            "CALENDAR_SOURCE_COUNT_MISMATCH:"
            f"expected={expected_source_count}:observed={len(source_paths)}"
        )
    if len(set(source_paths)) != expected_source_count:
        raise RuntimeError("CALENDAR_SOURCE_PATH_DUPLICATION")
    return source_paths


def _validate_sources_and_special_sessions(
    *,
    source_paths: tuple[Path, ...],
    special_config: Path,
    expected_holiday_rows: int = 220,
) -> list[dict[str, object]]:
    configured = json.loads(special_config.read_text(encoding="utf-8"))
    if not isinstance(configured, dict):
        raise RuntimeError("SPECIAL_SESSION_CONFIG_INVALID")
    if configured.get("production_influence") is not False:
        raise RuntimeError("SPECIAL_SESSION_CONFIG_PRODUCTION_INFLUENCE_INVALID")
    if configured.get("classification_inferred_from_archive_status") is not False:
        raise RuntimeError("SPECIAL_SESSION_CONFIG_ARCHIVE_INFERENCE_INVALID")
    if configured.get("classification_inferred_from_observed_candles") is not False:
        raise RuntimeError("SPECIAL_SESSION_CONFIG_CANDLE_INFERENCE_INVALID")
    configured_rows = configured.get("special_sessions")
    if not isinstance(configured_rows, list):
        raise RuntimeError("SPECIAL_SESSION_CONFIG_ROWS_INVALID")
    configured_pairs = {
        (str(row["trading_date"]), str(row["source_id"]))
        for row in configured_rows
        if isinstance(row, dict)
    }
    if len(configured_pairs) != 11:
        raise RuntimeError(
            f"EXPECTED_11_CONFIGURED_SPECIAL_SESSIONS_FOUND_{len(configured_pairs)}"
        )

    source_pairs: set[tuple[str, str]] = set()
    source_lineage: list[dict[str, object]] = []
    covered_years: set[int] = set()
    holiday_rows = 0
    special_rows = 0
    for source_path in source_paths:
        payload = validate_hash_bound_official_calendar_source(
            source_path,
            require_capital_market_scope=True,
        )
        source_id = str(payload.get("source_id") or "")
        source_holidays = payload.get("holidays")
        source_specials = payload.get("special_sessions")
        source_years = payload.get("covered_years")
        if not source_id:
            raise RuntimeError(f"CALENDAR_SOURCE_ID_MISSING:{source_path}")
        if not isinstance(source_holidays, list):
            raise RuntimeError(f"CALENDAR_SOURCE_HOLIDAYS_INVALID:{source_id}")
        if not isinstance(source_specials, list):
            raise RuntimeError(f"CALENDAR_SOURCE_SPECIALS_INVALID:{source_id}")
        if not isinstance(source_years, list):
            raise RuntimeError(f"CALENDAR_SOURCE_YEARS_INVALID:{source_id}")
        holiday_rows += len(source_holidays)
        special_rows += len(source_specials)
        covered_years.update(int(year) for year in source_years)
        for row in source_specials:
            if not isinstance(row, dict):
                raise RuntimeError(f"CALENDAR_SPECIAL_ROW_INVALID:{source_id}")
            source_pairs.add((str(row.get("trading_date") or ""), source_id))
        source_lineage.append(
            {
                "source_id": source_id,
                "source_path": str(source_path),
                "source_json_sha256": _sha256(source_path),
                "source_document_sha256": payload.get("source_document_sha256"),
                "review_csv_sha256": payload.get("review_csv_sha256"),
                "covered_years": source_years,
                "segment_scope": payload.get("segment_scope"),
            }
        )

    if covered_years != set(range(2005, 2016)):
        raise RuntimeError(f"CALENDAR_COVERED_YEAR_MISMATCH:{sorted(covered_years)}")
    if holiday_rows != expected_holiday_rows:
        raise RuntimeError(
            "CALENDAR_HOLIDAY_ROW_COUNT_MISMATCH:"
            f"expected={expected_holiday_rows}:observed={holiday_rows}"
        )
    if special_rows != 11:
        raise RuntimeError(f"EXPECTED_11_SPECIAL_ROWS_FOUND_{special_rows}")
    if source_pairs != configured_pairs:
        raise RuntimeError(
            "GOVERNED_SPECIAL_SESSION_CONFIG_MISMATCH:"
            f"configured={sorted(configured_pairs)}:sources={sorted(source_pairs)}"
        )
    return source_lineage


def run_full_calendar_audit(
    *,
    merged_root: Path,
    early_root: Path,
    later_root: Path,
    emergency_source: Path,
    special_config: Path,
    audit_root: Path,
    source_population_run_id: int,
    additional_sources: tuple[Path, ...] = (),
    expected_source_count: int = 29,
    expected_holiday_rows: int = 220,
) -> Path:
    database = merged_root / "warehouse" / "historical_truth.duckdb"
    manifest = merged_root / "manifests" / "archive_manifest.jsonl"
    if not database.is_file():
        raise RuntimeError("GOVERNED_MERGED_DATABASE_MISSING")
    if not manifest.is_file():
        raise RuntimeError("GOVERNED_MERGED_MANIFEST_MISSING")
    source_paths = _calendar_sources(
        early_root=early_root,
        later_root=later_root,
        emergency_source=emergency_source,
        additional_sources=additional_sources,
        expected_source_count=expected_source_count,
    )
    source_lineage = _validate_sources_and_special_sessions(
        source_paths=source_paths,
        special_config=special_config,
        expected_holiday_rows=expected_holiday_rows,
    )

    audit_root.mkdir(parents=True, exist_ok=True)
    sources = tuple(
        OfficialSessionCalendarEngine.load_source(path) for path in source_paths
    )
    canonical = CanonicalPointInTimeWarehouse(database)
    engine = OfficialSessionCalendarEngine(canonical)
    report = engine.reconcile(
        date(2005, 1, 1),
        date(2015, 12, 31),
        sources,
    )
    engine_paths = engine.export(report, audit_root)

    annual_rows: list[dict[str, object]] = [
        {str(key): value for key, value in asdict(item).items()}
        for item in report.annual_summaries
    ]
    if not annual_rows:
        raise RuntimeError("FULL_CALENDAR_ANNUAL_SUMMARY_EMPTY")
    _write_rows(
        audit_root / "annual_audit.csv",
        annual_rows,
        tuple(annual_rows[0]),
    )
    record_rows: list[dict[str, object]] = [
        {
            "trading_date": record.trading_date.isoformat(),
            "classification": record.classification.value,
            "observed_candles": record.observed_candles,
            "description": record.description or "",
            "source_ids": ";".join(record.source_ids),
            "issue_codes": ";".join(record.issue_codes),
        }
        for record in report.records
    ]
    fields = (
        "trading_date",
        "classification",
        "observed_candles",
        "description",
        "source_ids",
        "issue_codes",
    )
    _write_rows(
        audit_root / "unresolved_dates.csv",
        [row for row in record_rows if row["classification"] == "unresolved_weekday"],
        fields,
    )
    _write_rows(
        audit_root / "conflicts.csv",
        [
            row
            for row in record_rows
            if "HOLIDAY_HAS_OBSERVED_CANDLES" in str(row["issue_codes"])
        ],
        fields,
    )
    _write_rows(
        audit_root / "missing_special_sessions.csv",
        [
            row
            for row in record_rows
            if "MISSING_OFFICIAL_SPECIAL_SESSION" in str(row["issue_codes"])
        ],
        fields,
    )
    _write_rows(
        audit_root / "unconfirmed_special_sessions.csv",
        [
            row
            for row in record_rows
            if "UNCONFIRMED_SPECIAL_SESSION" in str(row["issue_codes"])
        ],
        fields,
    )
    (audit_root / "source_lineage.json").write_text(
        json.dumps(source_lineage, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    latest_manifest: dict[str, dict[str, Any]] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise RuntimeError("MERGED_MANIFEST_ROW_INVALID")
        latest_manifest[str(payload.get("trading_date") or "")] = payload
    latest_status_counts: dict[str, int] = {}
    for payload in latest_manifest.values():
        status = str(payload.get("status") or "UNKNOWN")
        latest_status_counts[status] = latest_status_counts.get(status, 0) + 1

    certification_permitted = (
        report.certification_state is CalendarCertificationState.CERTIFIED
        and report.unresolved_weekday_count == 0
        and report.unconfirmed_special_session_count == 0
        and report.missing_special_session_count == 0
        and report.conflict_count == 0
    )
    summary: dict[str, object] = {
        "start_date": report.start_date.isoformat(),
        "end_date": report.end_date.isoformat(),
        "reviewed_source_count": len(source_paths),
        "covered_years": list(range(2005, 2016)),
        "official_holiday_count": report.official_holiday_count,
        "official_special_session_count": report.official_special_session_count,
        "expected_session_count": report.expected_session_count,
        "observed_session_count": report.observed_session_count,
        "unresolved_weekday_count": report.unresolved_weekday_count,
        "unconfirmed_special_session_count": report.unconfirmed_special_session_count,
        "missing_special_session_count": report.missing_special_session_count,
        "conflict_count": report.conflict_count,
        "certification_state": report.certification_state.value,
        "calendar_report_sha256": report.report_sha256,
        "database_path": str(database),
        "database_sha256": _sha256(database),
        "manifest_path": str(manifest),
        "manifest_sha256": _sha256(manifest),
        "latest_manifest_status_counts": dict(sorted(latest_status_counts.items())),
        "source_population_run_id": source_population_run_id,
        "full_2005_2015_audit_performed": True,
        "calendar_certification_permitted": certification_permitted,
        "classification_inferred_from_archive_status": False,
        "classification_inferred_from_observed_candles": False,
        "production_influence": False,
        "engine_artifacts": [str(path) for path in engine_paths],
    }
    summary_path = audit_root / "full_calendar_audit_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    evidence_paths = [
        database,
        manifest,
        merged_root / "merge_lineage.json",
        merged_root / "merge_summary.json",
        *(path for path in audit_root.rglob("*") if path.is_file()),
        *source_paths,
        special_config,
    ]
    with (audit_root / "evidence_hashes.txt").open(
        "w",
        encoding="utf-8",
    ) as handle:
        for path in sorted(set(evidence_paths), key=str):
            handle.write(f"{_sha256(path)}  {path}\n")

    print("===== DSI-010 FULL 2005-2015 CALENDAR AUDIT =====")
    for key, value in summary.items():
        print(f"{key}: {value}")
    return summary_path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--merged-root", type=Path, required=True)
    parser.add_argument("--early-root", type=Path, required=True)
    parser.add_argument("--later-root", type=Path, required=True)
    parser.add_argument("--emergency-source", type=Path, required=True)
    parser.add_argument("--special-config", type=Path, required=True)
    parser.add_argument("--audit-root", type=Path, required=True)
    parser.add_argument("--source-population-run-id", type=int, required=True)
    parser.add_argument(
        "--additional-source",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument("--expected-source-count", type=int, default=29)
    parser.add_argument("--expected-holiday-row-count", type=int, default=220)
    args = parser.parse_args()
    run_full_calendar_audit(
        merged_root=args.merged_root,
        early_root=args.early_root,
        later_root=args.later_root,
        emergency_source=args.emergency_source,
        special_config=args.special_config,
        audit_root=args.audit_root,
        source_population_run_id=args.source_population_run_id,
        additional_sources=tuple(args.additional_source),
        expected_source_count=args.expected_source_count,
        expected_holiday_rows=args.expected_holiday_row_count,
    )


if __name__ == "__main__":
    main()
