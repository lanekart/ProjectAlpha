from __future__ import annotations

import argparse
import csv
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb

DIAGNOSTIC_ONLY = True
PRODUCTION_INFLUENCE = False
DATE_RE = re.compile(r"(?<!\d)(20\d{2})[-_]?([01]\d)[-_]?([0-3]\d)(?!\d)")
TEXT_SUFFIXES = {".csv", ".json", ".jsonl", ".md", ".txt", ".py", ".toml", ".yaml", ".yml"}


@dataclass(frozen=True, slots=True)
class DatasetSpec:
    key: str
    name: str
    canonical_tables: tuple[str, ...]
    tokens: tuple[str, ...]
    blocking: bool


@dataclass(frozen=True, slots=True)
class ReconciliationRow:
    dataset_key: str
    dataset_name: str
    inventory_status: str
    primary_classification: str
    canonical_table: str
    canonical_row_count: int | None
    canonical_first_date: str | None
    canonical_last_date: str | None
    alternate_tables: str
    raw_files_found: int
    snapshot_files_found: int
    source_proof_found: bool
    parser_found: bool
    ingestion_command_found: bool
    tests_found: bool
    requested_period_coverage: str | None
    recoverable_without_download: bool
    estimated_recovery_complexity: str
    certification_blocker: bool
    evidence: str
    recommended_action: str
    diagnostic_only: bool = DIAGNOSTIC_ONLY
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class MissingSessionRow:
    session_date: str
    classification: str
    evidence: str


SPECS: tuple[DatasetSpec, ...] = (
    DatasetSpec("corporate_actions", "Corporate Actions", ("corporate_action",), ("corporate_action", "corporate-actions", "corp_action"), True),
    DatasetSpec("security_identity", "Security Identity History", ("security_identity",), ("security_identity", "security_master", "symbol_change", "isin"), True),
    DatasetSpec("listing_history", "Listing History", ("listing_history", "listed_security"), ("listing_history", "listing", "listed_security"), True),
    DatasetSpec("delisting_history", "Delisting/Suspension History", ("delisting_history", "suspension_history"), ("delist", "suspension", "scheme_of_arrangement"), True),
    DatasetSpec("trading_calendar", "Trading Calendar", ("trading_calendar", "trading_session", "exchange_holiday"), ("trading_calendar", "exchange_holiday", "holiday"), True),
    DatasetSpec("benchmark_history", "Benchmark History", ("index_candle", "benchmark_history", "index_price"), ("benchmark", "index_candle", "nifty", "indices"), True),
    DatasetSpec("sector_mapping", "Historical Sector Mapping", ("sector_mapping", "industry_mapping"), ("sector_mapping", "industry_mapping", "sector", "industry"), True),
    DatasetSpec("index_constituents", "Historical Index Constituents", ("index_constituent", "index_membership"), ("index_constituent", "index_membership", "constituent"), False),
)


def run_reconciliation(
    *,
    database: Path,
    repository_root: Path,
    snapshots: Path | None,
    inventory_csv: Path | None,
    period_start: date,
    period_end: date,
) -> tuple[tuple[ReconciliationRow, ...], tuple[MissingSessionRow, ...]]:
    inventory = _read_inventory(inventory_csv)
    tables = _table_names(database)
    files = tuple(_iter_files(repository_root))
    snapshot_files = tuple(_iter_files(snapshots)) if snapshots else ()
    rows = tuple(
        _reconcile_one(
            spec=spec,
            database=database,
            tables=tables,
            files=files,
            snapshot_files=snapshot_files,
            inventory_status=inventory.get(spec.key, "UNKNOWN"),
            period_start=period_start,
            period_end=period_end,
        )
        for spec in SPECS
    )
    sessions = _reconcile_sessions(
        database=database,
        files=files,
        period_start=period_start,
        period_end=period_end,
    )
    return rows, sessions


def export_reconciliation(
    rows: tuple[ReconciliationRow, ...],
    missing_sessions: tuple[MissingSessionRow, ...],
    *,
    output: Path,
    period_start: date,
    period_end: date,
) -> tuple[Path, ...]:
    output.mkdir(parents=True, exist_ok=True)
    matrix = output / "reconciliation_matrix.csv"
    _write_csv(matrix, (asdict(row) for row in rows))

    evidence_locations = output / "evidence_locations.csv"
    _write_csv(
        evidence_locations,
        (
            {
                "dataset_key": row.dataset_key,
                "canonical_table": row.canonical_table,
                "alternate_tables": row.alternate_tables,
                "raw_files_found": row.raw_files_found,
                "snapshot_files_found": row.snapshot_files_found,
                "evidence": row.evidence,
            }
            for row in rows
        ),
    )

    canonical = output / "canonical_table_status.csv"
    _write_csv(
        canonical,
        (
            {
                "dataset_key": row.dataset_key,
                "canonical_table": row.canonical_table,
                "row_count": row.canonical_row_count,
                "first_date": row.canonical_first_date,
                "last_date": row.canonical_last_date,
                "classification": row.primary_classification,
            }
            for row in rows
        ),
    )

    ingestion = output / "ingestion_path_status.csv"
    _write_csv(
        ingestion,
        (
            {
                "dataset_key": row.dataset_key,
                "parser_found": row.parser_found,
                "ingestion_command_found": row.ingestion_command_found,
                "tests_found": row.tests_found,
                "recoverable_without_download": row.recoverable_without_download,
            }
            for row in rows
        ),
    )

    source_proof = output / "source_proof_status.csv"
    _write_csv(
        source_proof,
        (
            {
                "dataset_key": row.dataset_key,
                "source_proof_found": row.source_proof_found,
                "raw_files_found": row.raw_files_found,
                "snapshot_files_found": row.snapshot_files_found,
            }
            for row in rows
        ),
    )

    schema_mismatches = output / "schema_mismatches.csv"
    _write_csv(
        schema_mismatches,
        (asdict(row) for row in rows if row.primary_classification in {"INGESTED_NONCANONICAL", "SCHEMA_NOT_RECOGNISED"}),
    )

    recoverable = output / "recoverable_datasets.csv"
    _write_csv(recoverable, (asdict(row) for row in rows if row.recoverable_without_download))

    missing = output / "truly_missing_datasets.csv"
    _write_csv(missing, (asdict(row) for row in rows if row.primary_classification == "TRULY_MISSING"))

    sequence = output / "recommended_sequence.csv"
    ranked = sorted(rows, key=_sequence_key)
    _write_csv(
        sequence,
        (
            {
                "rank": rank,
                "dataset_key": row.dataset_key,
                "classification": row.primary_classification,
                "recoverable_without_download": row.recoverable_without_download,
                "recommended_action": row.recommended_action,
            }
            for rank, row in enumerate(ranked, start=1)
        ),
    )

    missing_sessions_path = output / "missing_sessions.csv"
    _write_csv(missing_sessions_path, (asdict(row) for row in missing_sessions))

    summary_payload = _summary(rows, missing_sessions, period_start, period_end)
    summary = output / "summary.json"
    summary.write_text(json.dumps(summary_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    report = output / "report.md"
    report.write_text(_render_report(rows, missing_sessions, summary_payload), encoding="utf-8")

    return (
        report,
        summary,
        matrix,
        evidence_locations,
        canonical,
        ingestion,
        source_proof,
        schema_mismatches,
        recoverable,
        missing,
        sequence,
        missing_sessions_path,
    )


def _reconcile_one(
    *,
    spec: DatasetSpec,
    database: Path,
    tables: tuple[str, ...],
    files: tuple[Path, ...],
    snapshot_files: tuple[Path, ...],
    inventory_status: str,
    period_start: date,
    period_end: date,
) -> ReconciliationRow:
    canonical_matches = tuple(table for table in tables if _base_name(table) in spec.canonical_tables)
    alternate_tables = tuple(
        table for table in tables if table not in canonical_matches and _matches(table, spec.tokens)
    )
    canonical_table = canonical_matches[0] if canonical_matches else ""
    row_count, first_date, last_date = _table_stats(
        database,
        canonical_table,
        period_start=period_start,
        period_end=period_end,
    )
    matching_files = tuple(path for path in files if _matches(str(path), spec.tokens))
    matching_snapshots = tuple(path for path in snapshot_files if _matches(str(path), spec.tokens))
    raw_files = tuple(path for path in matching_files if _is_raw_evidence(path))
    source_proof_found = any(_is_source_proof(path) for path in matching_files)
    parser_found = any(_is_parser(path) for path in matching_files)
    ingestion_command_found = any(_is_ingestion(path) for path in matching_files)
    tests_found = any("test" in path.name.lower() for path in matching_files)

    classification = _classify(
        canonical_exists=bool(canonical_matches),
        canonical_rows=row_count,
        alternate_tables=alternate_tables,
        raw_files=raw_files,
        source_proof_found=source_proof_found,
        parser_found=parser_found,
        inventory_status=inventory_status,
    )
    recoverable = classification in {
        "CANONICAL_TABLE_POPULATED_UNCERTIFIED",
        "RAW_DATA_PRESENT",
        "PARSED_NOT_INGESTED",
        "INGESTED_NONCANONICAL",
        "SCHEMA_NOT_RECOGNISED",
        "CERTIFICATION_LOGIC_GAP",
    }
    evidence = "; ".join(
        (
            f"canonical={canonical_table or 'none'}",
            f"canonical_rows={row_count if row_count is not None else 'unknown'}",
            f"alternate_tables={','.join(alternate_tables) or 'none'}",
            f"raw_files={len(raw_files)}",
            f"snapshot_files={len(matching_snapshots)}",
            f"source_proof={source_proof_found}",
            f"parser={parser_found}",
            f"ingestion={ingestion_command_found}",
        )
    )
    return ReconciliationRow(
        dataset_key=spec.key,
        dataset_name=spec.name,
        inventory_status=inventory_status,
        primary_classification=classification,
        canonical_table=canonical_table,
        canonical_row_count=row_count,
        canonical_first_date=first_date.isoformat() if first_date else None,
        canonical_last_date=last_date.isoformat() if last_date else None,
        alternate_tables=",".join(alternate_tables),
        raw_files_found=len(raw_files),
        snapshot_files_found=len(matching_snapshots),
        source_proof_found=source_proof_found,
        parser_found=parser_found,
        ingestion_command_found=ingestion_command_found,
        tests_found=tests_found,
        requested_period_coverage=_coverage(first_date, last_date, period_start, period_end),
        recoverable_without_download=recoverable,
        estimated_recovery_complexity=_complexity(classification),
        certification_blocker=spec.blocking and classification != "CERTIFIED_CANONICAL",
        evidence=evidence,
        recommended_action=_recommended_action(classification, spec.name),
    )


def _classify(
    *,
    canonical_exists: bool,
    canonical_rows: int | None,
    alternate_tables: tuple[str, ...],
    raw_files: tuple[Path, ...],
    source_proof_found: bool,
    parser_found: bool,
    inventory_status: str,
) -> str:
    if canonical_exists and canonical_rows and canonical_rows > 0:
        if inventory_status in {"COMPLETE", "CERTIFIED"}:
            return "CERTIFIED_CANONICAL"
        return "CANONICAL_TABLE_POPULATED_UNCERTIFIED"
    if alternate_tables:
        return "INGESTED_NONCANONICAL"
    if raw_files and parser_found:
        return "PARSED_NOT_INGESTED"
    if raw_files:
        return "RAW_DATA_PRESENT"
    if source_proof_found:
        return "SOURCE_PROOF_ONLY"
    if canonical_exists and canonical_rows == 0:
        return "CANONICAL_TABLE_EMPTY"
    if inventory_status not in {"MISSING", "UNKNOWN", "PRESENT_EMPTY"}:
        return "CERTIFICATION_LOGIC_GAP"
    return "TRULY_MISSING"


def _reconcile_sessions(
    *, database: Path, files: tuple[Path, ...], period_start: date, period_end: date
) -> tuple[MissingSessionRow, ...]:
    observed = _daily_candle_dates(database, period_start, period_end)
    expected = {
        period_start + timedelta(days=offset)
        for offset in range((period_end - period_start).days + 1)
        if (period_start + timedelta(days=offset)).weekday() < 5
    }
    holiday_evidence = _holiday_dates(files)
    return tuple(
        MissingSessionRow(
            session_date=session.isoformat(),
            classification="VERIFIED_EXCHANGE_HOLIDAY" if session in holiday_evidence else "UNRESOLVED",
            evidence=(
                "Matched repository holiday evidence"
                if session in holiday_evidence
                else "Absent from daily_candle and no certified holiday evidence found"
            ),
        )
        for session in sorted(expected - observed)
    )


def _daily_candle_dates(database: Path, start: date, end: date) -> frozenset[date]:
    if not database.exists():
        return frozenset()
    table = next((item for item in _table_names(database) if _base_name(item) == "daily_candle"), None)
    if table is None:
        return frozenset()
    date_column = _date_column(database, table)
    if date_column is None:
        return frozenset()
    query = (
        f'SELECT DISTINCT CAST("{date_column}" AS DATE) FROM {table} '
        f'WHERE CAST("{date_column}" AS DATE) BETWEEN ? AND ? ORDER BY 1'
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        return frozenset(row[0] for row in connection.execute(query, [start, end]).fetchall())


def _holiday_dates(files: tuple[Path, ...]) -> frozenset[date]:
    dates: set[date] = set()
    for path in files:
        if not _matches(str(path), ("holiday", "trading_calendar", "exchange_holiday")):
            continue
        dates.update(_dates_from_text(str(path)))
        if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= 2_000_000:
            try:
                dates.update(_dates_from_text(path.read_text(encoding="utf-8", errors="ignore")))
            except OSError:
                continue
    return frozenset(dates)


def _dates_from_text(value: str) -> set[date]:
    parsed: set[date] = set()
    for year, month, day in DATE_RE.findall(value):
        try:
            parsed.add(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    return parsed


def _table_names(database: Path) -> tuple[str, ...]:
    if not database.exists():
        return ()
    query = """
        SELECT table_schema || '.' || table_name
        FROM information_schema.tables
        WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
        ORDER BY 1
    """
    with duckdb.connect(str(database), read_only=True) as connection:
        return tuple(row[0] for row in connection.execute(query).fetchall())


def _table_stats(
    database: Path,
    table: str,
    *,
    period_start: date,
    period_end: date,
) -> tuple[int | None, date | None, date | None]:
    if not table:
        return None, None, None
    date_column = _date_column(database, table)
    with duckdb.connect(str(database), read_only=True) as connection:
        if date_column is None:
            row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
            return (int(row[0]) if row else None), None, None
        query = (
            f'SELECT COUNT(*), MIN(CAST("{date_column}" AS DATE)), '
            f'MAX(CAST("{date_column}" AS DATE)) FROM {table} '
            f'WHERE CAST("{date_column}" AS DATE) BETWEEN ? AND ?'
        )
        row = connection.execute(query, [period_start, period_end]).fetchone()
        if row is None:
            return None, None, None
        return int(row[0]), row[1], row[2]


def _date_column(database: Path, table: str) -> str | None:
    schema, name = table.split(".", maxsplit=1)
    query = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = ? AND table_name = ?
        ORDER BY ordinal_position
    """
    preferred = (
        "trading_date",
        "session_date",
        "trade_date",
        "effective_date",
        "ex_date",
        "as_of_date",
        "date",
        "valid_from",
    )
    with duckdb.connect(str(database), read_only=True) as connection:
        columns = {row[0] for row in connection.execute(query, [schema, name]).fetchall()}
    return next((column for column in preferred if column in columns), None)


def _read_inventory(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8") as handle:
        return {
            row["dataset_key"]: row.get("status", "UNKNOWN")
            for row in csv.DictReader(handle)
            if row.get("dataset_key")
        }


def _iter_files(root: Path | None) -> Iterable[Path]:
    if root is None or not root.exists():
        return ()
    ignored = {".git", ".venv", "__pycache__", ".mypy_cache", ".pytest_cache"}
    return (
        path
        for path in root.rglob("*")
        if path.is_file() and not any(part in ignored for part in path.parts)
    )


def _matches(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower().replace("-", "_")
    return any(token.lower().replace("-", "_") in lowered for token in tokens)


def _base_name(table: str) -> str:
    return table.rsplit(".", maxsplit=1)[-1].lower()


def _is_raw_evidence(path: Path) -> bool:
    lowered_name = path.name.lower()
    return path.suffix.lower() in {".csv", ".json", ".jsonl", ".parquet", ".zip"} and not any(
        token in lowered_name for token in ("test", "fixture", "report")
    )


def _is_source_proof(path: Path) -> bool:
    lowered = str(path).lower()
    return any(token in lowered for token in ("proof", "adapter", "source", "archive"))


def _is_parser(path: Path) -> bool:
    lowered = path.name.lower()
    return path.suffix == ".py" and any(token in lowered for token in ("parse", "parser", "adapter", "ingest"))


def _is_ingestion(path: Path) -> bool:
    lowered = str(path).lower()
    return path.suffix == ".py" and any(token in lowered for token in ("cli", "ingest", "loader", "import"))


def _coverage(
    first_date: date | None,
    last_date: date | None,
    period_start: date,
    period_end: date,
) -> str | None:
    if first_date is None or last_date is None:
        return None
    overlap_start = max(first_date, period_start)
    overlap_end = min(last_date, period_end)
    if overlap_end < overlap_start:
        return "0.00"
    requested_days = (period_end - period_start).days + 1
    covered_days = (overlap_end - overlap_start).days + 1
    return f"{min(100.0, covered_days / requested_days * 100):.2f}"


def _complexity(classification: str) -> str:
    if classification in {"CERTIFIED_CANONICAL", "CERTIFICATION_LOGIC_GAP"}:
        return "LOW"
    if classification in {"CANONICAL_TABLE_POPULATED_UNCERTIFIED", "PARSED_NOT_INGESTED", "INGESTED_NONCANONICAL"}:
        return "MEDIUM"
    return "HIGH"


def _recommended_action(classification: str, name: str) -> str:
    actions = {
        "CERTIFIED_CANONICAL": "No action required.",
        "CANONICAL_TABLE_POPULATED_UNCERTIFIED": f"Validate lineage and certify {name}.",
        "CANONICAL_TABLE_EMPTY": f"Trace ingestion inputs before acquiring new {name} data.",
        "RAW_DATA_PRESENT": f"Implement or connect the parser and ingest existing {name} evidence.",
        "SOURCE_PROOF_ONLY": f"Obtain usable records from the already-proven {name} source.",
        "PARSED_NOT_INGESTED": f"Run or repair the existing {name} ingestion path.",
        "INGESTED_NONCANONICAL": f"Map noncanonical {name} tables into historical truth.",
        "SCHEMA_NOT_RECOGNISED": f"Teach certification logic the existing {name} schema.",
        "CERTIFICATION_LOGIC_GAP": f"Repair {name} certification logic without downloading data.",
        "TRULY_MISSING": f"Plan governed acquisition for {name}.",
    }
    return actions.get(classification, f"Investigate {name} evidence manually.")


def _sequence_key(row: ReconciliationRow) -> tuple[int, int, str]:
    recoverable_rank = 0 if row.recoverable_without_download else 1
    blocking_rank = 0 if row.certification_blocker else 1
    priority = {
        "trading_calendar": 0,
        "corporate_actions": 1,
        "security_identity": 2,
        "listing_history": 3,
        "delisting_history": 4,
        "benchmark_history": 5,
        "sector_mapping": 6,
        "index_constituents": 7,
    }.get(row.dataset_key, 99)
    return recoverable_rank, blocking_rank, f"{priority:02d}:{row.dataset_key}"


def _summary(
    rows: tuple[ReconciliationRow, ...],
    missing_sessions: tuple[MissingSessionRow, ...],
    period_start: date,
    period_end: date,
) -> dict[str, object]:
    recoverable = [row.dataset_key for row in rows if row.recoverable_without_download]
    truly_missing = [row.dataset_key for row in rows if row.primary_classification == "TRULY_MISSING"]
    unresolved_sessions = [
        row.session_date for row in missing_sessions if row.classification == "UNRESOLVED"
    ]
    corporate = next(row for row in rows if row.dataset_key == "corporate_actions")
    return {
        "classification": "HISTORICAL_TRUTH_RECONCILIATION_V1",
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "production_influence": PRODUCTION_INFLUENCE,
        "recoverable_without_download": recoverable,
        "truly_missing": truly_missing,
        "apparent_missing_sessions": len(missing_sessions),
        "unresolved_missing_sessions": unresolved_sessions,
        "corporate_actions_next_milestone": corporate.primary_classification
        in {"CANONICAL_TABLE_EMPTY", "PARSED_NOT_INGESTED", "RAW_DATA_PRESENT"},
    }


def _render_report(
    rows: tuple[ReconciliationRow, ...],
    missing_sessions: tuple[MissingSessionRow, ...],
    summary: Mapping[str, object],
) -> str:
    lines = [
        "# Historical Truth Reconciliation v1",
        "",
        "**DIAGNOSTIC_ONLY / PRODUCTION_INFLUENCE=false**",
        "",
        f"- Period: **{summary['period_start']} to {summary['period_end']}**",
        f"- Recoverable without download: **{len(summary['recoverable_without_download'])}**",
        f"- Truly missing: **{len(summary['truly_missing'])}**",
        f"- Apparent missing sessions: **{summary['apparent_missing_sessions']}**",
        "",
        "## Dataset Reconciliation",
        "",
        "| Dataset | Inventory | Classification | Canonical rows | Recoverable |",
        "|---|---|---|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.dataset_name} | {row.inventory_status} | {row.primary_classification} | "
            f"{row.canonical_row_count if row.canonical_row_count is not None else 'UNKNOWN'} | "
            f"{'YES' if row.recoverable_without_download else 'NO'} |"
        )
    lines.extend(("", "## Apparent Missing Sessions", ""))
    if missing_sessions:
        lines.extend(("| Date | Classification | Evidence |", "|---|---|---|"))
        for row in missing_sessions:
            lines.append(f"| {row.session_date} | {row.classification} | {row.evidence} |")
    else:
        lines.append("No apparent missing weekday sessions were found.")
    lines.extend(
        (
            "",
            "## Required Conclusion",
            "",
            f"- Recoverable without downloads: **{', '.join(summary['recoverable_without_download']) or 'none'}**",
            f"- Truly missing: **{', '.join(summary['truly_missing']) or 'none'}**",
            f"- Unresolved OHLCV dates: **{', '.join(summary['unresolved_missing_sessions']) or 'none'}**",
            f"- Corporate Actions remains next milestone: **{summary['corporate_actions_next_milestone']}**",
            "",
            "No production signal, gate, portfolio, or risk policy was changed.",
            "",
            "**PRODUCTION_INFLUENCE=false**",
            "",
        )
    )
    return "\n".join(lines)


def _write_csv(path: Path, rows: Iterable[Mapping[str, object]]) -> None:
    materialized = list(rows)
    if not materialized:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(materialized[0]))
        writer.writeheader()
        writer.writerows(materialized)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Historical Truth Reconciliation v1")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--snapshots", type=Path)
    parser.add_argument("--inventory-csv", type=Path)
    parser.add_argument("--start", type=_parse_date, required=True)
    parser.add_argument("--end", type=_parse_date, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    rows, missing_sessions = run_reconciliation(
        database=args.database,
        repository_root=args.repository_root,
        snapshots=args.snapshots,
        inventory_csv=args.inventory_csv,
        period_start=args.start,
        period_end=args.end,
    )
    artifacts = export_reconciliation(
        rows,
        missing_sessions,
        output=args.output,
        period_start=args.start,
        period_end=args.end,
    )
    print("Historical Truth Reconciliation v1")
    print(f"Period: {args.start} to {args.end}")
    print("DIAGNOSTIC_ONLY=true")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Artifacts: {args.output} ({len(artifacts)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
