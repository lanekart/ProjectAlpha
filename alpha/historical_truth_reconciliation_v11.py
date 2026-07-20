from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import cast

import duckdb

DIAGNOSTIC_ONLY = True
PRODUCTION_INFLUENCE = False
IGNORED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "artifacts",
}
GENERATED_NAMES = {
    "dataset_inventory.csv",
    "reconciliation_matrix.csv",
    "evidence_locations.csv",
    "coverage_report.csv",
    "missing_items.csv",
    "readiness_dashboard.csv",
}
VERIFIED_NSE_HOLIDAYS_2026 = {
    date(2026, 1, 15): "Maharashtra municipal corporation elections",
    date(2026, 1, 26): "Republic Day",
    date(2026, 3, 3): "Holi",
    date(2026, 3, 26): "Ram Navami",
    date(2026, 3, 31): "Mahavir Jayanti",
    date(2026, 4, 3): "Good Friday",
    date(2026, 4, 14): "Ambedkar Jayanti",
    date(2026, 5, 1): "Maharashtra Day",
    date(2026, 5, 28): "Bakri Id",
    date(2026, 6, 26): "Muharram",
}


@dataclass(frozen=True, slots=True)
class DatasetRule:
    key: str
    tokens: tuple[str, ...]
    required_columns: frozenset[str]
    date_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceRow:
    dataset_key: str
    relative_path: str
    role: str
    size_bytes: int
    row_count: int | None
    columns: str
    first_date: str | None
    last_date: str | None
    schema_match: bool
    usable_records: bool
    exclusion_reason: str


@dataclass(frozen=True, slots=True)
class DatasetPrecisionRow:
    dataset_key: str
    usable_raw_files: int
    generated_or_excluded_files: int
    code_files: int
    source_proof_files: int
    classification: str
    evidence_paths: str
    recommended_action: str
    diagnostic_only: bool = DIAGNOSTIC_ONLY
    production_influence: bool = PRODUCTION_INFLUENCE


@dataclass(frozen=True, slots=True)
class SessionRow:
    session_date: str
    classification: str
    evidence: str


RULES: tuple[DatasetRule, ...] = (
    DatasetRule(
        "corporate_actions",
        ("corporate_action", "corporate-actions", "corp_action"),
        frozenset({"symbol", "action_type"}),
        ("ex_date", "effective_date", "date"),
    ),
    DatasetRule(
        "security_identity",
        ("security_identity", "security_master", "symbol_change", "isin"),
        frozenset({"isin"}),
        ("valid_from", "effective_date", "date"),
    ),
    DatasetRule(
        "listing_history",
        ("listing_history", "listed_security", "listing"),
        frozenset({"symbol"}),
        ("listing_date", "effective_date", "date"),
    ),
    DatasetRule(
        "delisting_history",
        ("delist", "suspension", "scheme_of_arrangement"),
        frozenset({"symbol"}),
        ("delisting_date", "suspension_date", "effective_date", "date"),
    ),
    DatasetRule(
        "benchmark_history",
        ("benchmark", "index_candle", "nifty", "indices"),
        frozenset({"close"}),
        ("trading_date", "date"),
    ),
    DatasetRule(
        "sector_mapping",
        ("sector_mapping", "industry_mapping", "sector", "industry"),
        frozenset({"symbol"}),
        ("effective_date", "valid_from", "date"),
    ),
    DatasetRule(
        "index_constituents",
        ("index_constituent", "index_membership", "constituent"),
        frozenset({"symbol"}),
        ("effective_date", "as_of_date", "date"),
    ),
)


def run_precision_audit(
    *,
    repository_root: Path,
    database: Path,
    period_start: date,
    period_end: date,
) -> tuple[
    tuple[EvidenceRow, ...],
    tuple[DatasetPrecisionRow, ...],
    tuple[SessionRow, ...],
]:
    files = tuple(_iter_files(repository_root))
    evidence: list[EvidenceRow] = []
    for rule in RULES:
        for path in files:
            if not _matches_name(path.name, rule.tokens):
                continue
            evidence.append(_inspect_file(path, repository_root, rule))

    dataset_rows = tuple(
        _summarize_dataset(
            rule, tuple(row for row in evidence if row.dataset_key == rule.key)
        )
        for rule in RULES
    )
    sessions = _session_rows(database, period_start, period_end)
    return tuple(evidence), dataset_rows, sessions


def export_precision_audit(
    evidence: tuple[EvidenceRow, ...],
    datasets: tuple[DatasetPrecisionRow, ...],
    sessions: tuple[SessionRow, ...],
    *,
    output: Path,
    period_start: date,
    period_end: date,
) -> tuple[Path, ...]:
    output.mkdir(parents=True, exist_ok=True)
    evidence_path = output / "evidence_precision.csv"
    dataset_path = output / "dataset_reconciliation.csv"
    sessions_path = output / "missing_sessions.csv"
    summary_path = output / "summary.json"
    report_path = output / "report.md"

    _write_csv(evidence_path, (asdict(row) for row in evidence))
    _write_csv(dataset_path, (asdict(row) for row in datasets))
    _write_csv(sessions_path, (asdict(row) for row in sessions))

    usable = [
        row.dataset_key
        for row in datasets
        if row.classification == "RAW_DATA_CONFIRMED"
    ]
    missing = [
        row.dataset_key
        for row in datasets
        if row.classification == "NO_USABLE_RAW_DATA"
    ]
    unresolved = [
        row.session_date for row in sessions if row.classification == "UNRESOLVED"
    ]
    summary: dict[str, object] = {
        "classification": "HISTORICAL_TRUTH_RECONCILIATION_V1_1",
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "production_influence": PRODUCTION_INFLUENCE,
        "raw_data_confirmed": usable,
        "no_usable_raw_data": missing,
        "verified_holidays": sum(
            row.classification == "VERIFIED_EXCHANGE_HOLIDAY" for row in sessions
        ),
        "unresolved_sessions": unresolved,
        "daily_ohlcv_coverage_percent": "100.00" if not unresolved else "UNKNOWN",
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        _render_report(datasets, sessions, summary), encoding="utf-8"
    )
    return evidence_path, dataset_path, sessions_path, summary_path, report_path


def _inspect_file(path: Path, root: Path, rule: DatasetRule) -> EvidenceRow:
    relative = path.relative_to(root).as_posix()
    role, exclusion = _role(path)
    size = path.stat().st_size
    row_count: int | None = None
    columns: tuple[str, ...] = ()
    first_date: date | None = None
    last_date: date | None = None

    if role == "RAW_CANDIDATE" and path.suffix.lower() == ".csv":
        row_count, columns, first_date, last_date = _inspect_csv(
            path, rule.date_columns
        )
    elif role == "RAW_CANDIDATE" and path.suffix.lower() in {".json", ".jsonl"}:
        row_count, columns = _inspect_json(path)

    normalized = {column.lower().strip() for column in columns}
    schema_match = rule.required_columns.issubset(normalized)
    usable = role == "RAW_CANDIDATE" and bool(row_count) and schema_match
    return EvidenceRow(
        dataset_key=rule.key,
        relative_path=relative,
        role=role,
        size_bytes=size,
        row_count=row_count,
        columns=",".join(columns),
        first_date=first_date.isoformat() if first_date else None,
        last_date=last_date.isoformat() if last_date else None,
        schema_match=schema_match,
        usable_records=usable,
        exclusion_reason=exclusion,
    )


def _summarize_dataset(
    rule: DatasetRule,
    rows: tuple[EvidenceRow, ...],
) -> DatasetPrecisionRow:
    usable = tuple(row for row in rows if row.usable_records)
    excluded = tuple(row for row in rows if row.exclusion_reason)
    code = tuple(row for row in rows if row.role == "CODE")
    proof = tuple(row for row in rows if row.role == "SOURCE_PROOF")
    if usable:
        classification = "RAW_DATA_CONFIRMED"
        action = f"Build governed ingestion for confirmed {rule.key} records."
    elif rows:
        classification = "EVIDENCE_ONLY_NO_USABLE_RAW_DATA"
        action = f"Do not ingest {rule.key}; inspect listed evidence paths first."
    else:
        classification = "NO_USABLE_RAW_DATA"
        action = f"Plan governed acquisition or source recovery for {rule.key}."
    return DatasetPrecisionRow(
        dataset_key=rule.key,
        usable_raw_files=len(usable),
        generated_or_excluded_files=len(excluded),
        code_files=len(code),
        source_proof_files=len(proof),
        classification=classification,
        evidence_paths=";".join(row.relative_path for row in rows),
        recommended_action=action,
    )


def _role(path: Path) -> tuple[str, str]:
    lowered_parts = {part.lower() for part in path.parts}
    if lowered_parts & IGNORED_PARTS:
        return "GENERATED_OR_IGNORED", "ignored directory"
    if path.name.lower() in GENERATED_NAMES:
        return "GENERATED_OR_IGNORED", "generated diagnostic output"
    if "test" in path.name.lower() or "fixture" in path.name.lower():
        return "FIXTURE", "test or fixture file"
    if path.suffix.lower() == ".py":
        lowered = path.name.lower()
        if any(token in lowered for token in ("adapter", "source", "archive", "proof")):
            return "SOURCE_PROOF", ""
        return "CODE", ""
    if path.suffix.lower() in {".md", ".txt", ".toml", ".yaml", ".yml"}:
        return "DOCUMENTATION", "non-data text file"
    if path.suffix.lower() in {".csv", ".json", ".jsonl", ".parquet", ".zip"}:
        return "RAW_CANDIDATE", ""
    return "OTHER", "unsupported file type"


def _inspect_csv(
    path: Path,
    date_columns: tuple[str, ...],
) -> tuple[int, tuple[str, ...], date | None, date | None]:
    count = 0
    first: date | None = None
    last: date | None = None
    with path.open(newline="", encoding="utf-8", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        columns = tuple(reader.fieldnames or ())
        date_column = next((item for item in date_columns if item in columns), None)
        for row in reader:
            count += 1
            if date_column and row.get(date_column):
                parsed = _try_date(cast(str, row[date_column]))
                if parsed:
                    first = parsed if first is None or parsed < first else first
                    last = parsed if last is None or parsed > last else last
    return count, columns, first, last


def _inspect_json(path: Path) -> tuple[int | None, tuple[str, ...]]:
    try:
        if path.suffix.lower() == ".jsonl":
            rows = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        else:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload if isinstance(payload, list) else [payload]
    except (OSError, json.JSONDecodeError):
        return None, ()
    mappings = [row for row in rows if isinstance(row, Mapping)]
    columns = tuple(sorted({str(key) for row in mappings for key in row}))
    return len(mappings), columns


def _session_rows(database: Path, start: date, end: date) -> tuple[SessionRow, ...]:
    observed = _daily_candle_dates(database, start, end)
    weekdays = {
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() < 5
    }
    rows: list[SessionRow] = []
    for session in sorted(weekdays - observed):
        reason = VERIFIED_NSE_HOLIDAYS_2026.get(session)
        rows.append(
            SessionRow(
                session_date=session.isoformat(),
                classification=(
                    "VERIFIED_EXCHANGE_HOLIDAY" if reason else "UNRESOLVED"
                ),
                evidence=reason or "No verified exchange-holiday evidence registered",
            )
        )
    return tuple(rows)


def _daily_candle_dates(database: Path, start: date, end: date) -> frozenset[date]:
    if not database.exists():
        return frozenset()
    query = """
        SELECT DISTINCT CAST(trading_date AS DATE)
        FROM main.daily_candle
        WHERE CAST(trading_date AS DATE) BETWEEN ? AND ?
        ORDER BY 1
    """
    try:
        with duckdb.connect(str(database), read_only=True) as connection:
            return frozenset(
                row[0] for row in connection.execute(query, [start, end]).fetchall()
            )
    except duckdb.Error:
        return frozenset()


def _iter_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return ()
    return (
        path
        for path in root.rglob("*")
        if path.is_file()
        and not any(part.lower() in IGNORED_PARTS for part in path.parts)
    )


def _matches_name(name: str, tokens: tuple[str, ...]) -> bool:
    lowered = name.lower().replace("-", "_")
    return any(token.lower().replace("-", "_") in lowered for token in tokens)


def _try_date(value: str) -> date | None:
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _render_report(
    datasets: tuple[DatasetPrecisionRow, ...],
    sessions: tuple[SessionRow, ...],
    summary: Mapping[str, object],
) -> str:
    confirmed = cast(list[str], summary["raw_data_confirmed"])
    missing = cast(list[str], summary["no_usable_raw_data"])
    unresolved = cast(list[str], summary["unresolved_sessions"])
    lines = [
        "# Historical Truth Reconciliation v1.1",
        "",
        "**DIAGNOSTIC_ONLY / PRODUCTION_INFLUENCE=false**",
        "",
        f"- Confirmed raw datasets: **{len(confirmed)}**",
        f"- No usable raw data: **{len(missing)}**",
        f"- Verified exchange holidays: **{summary['verified_holidays']}**",
        f"- Daily OHLCV coverage: **{summary['daily_ohlcv_coverage_percent']}%**",
        "",
        "## Evidence Precision",
        "",
        "| Dataset | Classification | Usable raw files | Excluded/generated |",
        "|---|---|---:|---:|",
    ]
    for row in datasets:
        lines.append(
            f"| {row.dataset_key} | {row.classification} | "
            f"{row.usable_raw_files} | {row.generated_or_excluded_files} |"
        )
    lines.extend(("", "## Missing Sessions", ""))
    for session in sessions:
        lines.append(
            f"- {session.session_date}: {session.classification} — {session.evidence}"
        )
    lines.extend(
        (
            "",
            "## Required Conclusion",
            "",
            f"- Confirmed raw datasets: **{', '.join(confirmed) or 'none'}**",
            f"- No usable raw data: **{', '.join(missing) or 'none'}**",
            f"- Unresolved sessions: **{', '.join(unresolved) or 'none'}**",
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
    parser = argparse.ArgumentParser(description="Historical Truth Reconciliation v1.1")
    parser.add_argument("--repository-root", type=Path, default=Path("."))
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--start", type=_parse_date, required=True)
    parser.add_argument("--end", type=_parse_date, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    evidence, datasets, sessions = run_precision_audit(
        repository_root=args.repository_root,
        database=args.database,
        period_start=args.start,
        period_end=args.end,
    )
    artifacts = export_precision_audit(
        evidence,
        datasets,
        sessions,
        output=args.output,
        period_start=args.start,
        period_end=args.end,
    )
    print("Historical Truth Reconciliation v1.1")
    print("DIAGNOSTIC_ONLY=true")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Artifacts: {args.output} ({len(artifacts)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
