from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

import duckdb

DIAGNOSTIC_ONLY = True
PRODUCTION_INFLUENCE = False
DATE_COLUMNS = (
    "trading_date",
    "session_date",
    "trade_date",
    "date",
    "as_of_date",
    "effective_date",
)


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    key: str
    name: str
    required: bool
    blocking: bool
    capability: str
    table_tokens: tuple[str, ...]
    path_tokens: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DatasetInventoryRow:
    dataset_key: str
    dataset_name: str
    required: bool
    blocking: bool
    capability: str
    status: str
    evidence: str
    matched_tables: str
    matched_files: int
    row_count: int | None
    first_date: str | None
    last_date: str | None
    observed_sessions: int | None
    expected_sessions: int | None
    missing_sessions: int | None
    coverage_percent: str | None
    certification_ready: bool
    limitation: str
    diagnostic_only: bool = DIAGNOSTIC_ONLY
    production_influence: bool = PRODUCTION_INFLUENCE


DATASETS: tuple[DatasetDefinition, ...] = (
    DatasetDefinition(
        "daily_ohlcv",
        "Daily OHLCV",
        True,
        True,
        "Historical replay",
        ("price", "ohlcv", "bhavcopy", "market_data"),
        ("bhavcopy", "ohlcv", "prices"),
    ),
    DatasetDefinition(
        "corporate_actions",
        "Corporate Actions",
        True,
        True,
        "Adjusted returns",
        ("corporate_action", "corp_action", "bonus", "split", "dividend"),
        ("corporate_action", "corp_action"),
    ),
    DatasetDefinition(
        "security_identity",
        "Security Identity History",
        True,
        True,
        "Point-in-time identity",
        ("security_master", "identity", "isin", "symbol_history"),
        ("security_master", "identity", "symbol_change"),
    ),
    DatasetDefinition(
        "listing_history",
        "Listing History",
        True,
        True,
        "Survivorship-free replay",
        ("listing", "listed_security"),
        ("listing", "listed"),
    ),
    DatasetDefinition(
        "delisting_history",
        "Delisting/Suspension History",
        True,
        True,
        "Survivorship-free replay",
        ("delist", "suspension", "suspended"),
        ("delist", "suspension"),
    ),
    DatasetDefinition(
        "trading_calendar",
        "Trading Calendar",
        True,
        True,
        "Session alignment",
        ("calendar", "trading_session", "holiday"),
        ("calendar", "holiday"),
    ),
    DatasetDefinition(
        "benchmark_history",
        "Benchmark History",
        True,
        True,
        "Benchmark-relative returns",
        ("index_price", "benchmark", "nifty"),
        ("index", "benchmark", "nifty"),
    ),
    DatasetDefinition(
        "sector_mapping",
        "Historical Sector Mapping",
        True,
        True,
        "Sector attribution",
        ("sector", "industry_mapping"),
        ("sector", "industry"),
    ),
    DatasetDefinition(
        "index_constituents",
        "Historical Index Constituents",
        True,
        False,
        "Point-in-time universes",
        ("constituent", "index_membership"),
        ("constituent", "index_membership"),
    ),
    DatasetDefinition(
        "market_breadth",
        "Market Breadth",
        False,
        False,
        "Market regime",
        ("breadth", "advance_decline"),
        ("breadth", "advance_decline"),
    ),
    DatasetDefinition(
        "delivery_percentage",
        "Delivery Percentage",
        False,
        False,
        "Liquidity intelligence",
        ("delivery", "deliverable"),
        ("delivery", "deliverable"),
    ),
    DatasetDefinition(
        "volatility_index",
        "Volatility Index",
        False,
        False,
        "Risk regime",
        ("vix", "volatility_index"),
        ("vix", "volatility"),
    ),
)


def build_inventory(
    *,
    year: int,
    database: Path,
    snapshots: Path | None,
) -> tuple[DatasetInventoryRow, ...]:
    tables = _table_metadata(database)
    files = tuple(_iter_files(snapshots))
    rows: list[DatasetInventoryRow] = []

    for definition in DATASETS:
        matched_tables = tuple(
            sorted(
                name
                for name in tables
                if _matches(name, definition.table_tokens)
            )
        )
        matched_files = tuple(
            path
            for path in files
            if _matches(str(path).lower(), definition.path_tokens)
        )
        row_count, observed_dates = _aggregate_table_evidence(
            database,
            matched_tables,
            year,
        )
        first_date = min(observed_dates) if observed_dates else None
        last_date = max(observed_dates) if observed_dates else None
        observed_sessions = len(observed_dates) if observed_dates else None
        expected_sessions = _expected_weekday_sessions(year, last_date)
        coverage = _session_coverage(observed_sessions, expected_sessions)
        missing_sessions = (
            max(expected_sessions - observed_sessions, 0)
            if expected_sessions is not None and observed_sessions is not None
            else None
        )

        present = bool(matched_tables or matched_files)
        status = "MISSING"
        limitation = "No matching warehouse table or snapshot/raw file found."
        ready = False

        if present:
            if row_count == 0 and matched_tables:
                status = "PRESENT_EMPTY"
                limitation = (
                    "Matching warehouse table exists but has no rows for "
                    "the requested year."
                )
            elif coverage is not None and coverage >= 95:
                status = "COMPLETE_CANDIDATE"
                limitation = (
                    "Observed session coverage is adequate; dataset-specific "
                    "integrity certification is still required."
                )
                ready = True
            else:
                status = "PARTIAL"
                limitation = (
                    "Dataset evidence exists, but trading-session coverage is "
                    "incomplete or cannot be proven."
                )

        evidence_parts = (
            f"tables={','.join(matched_tables)}" if matched_tables else "",
            f"files={len(matched_files)}" if matched_files else "",
        )
        evidence = "; ".join(filter(None, evidence_parts)) or "none"
        rows.append(
            DatasetInventoryRow(
                dataset_key=definition.key,
                dataset_name=definition.name,
                required=definition.required,
                blocking=definition.blocking,
                capability=definition.capability,
                status=status,
                evidence=evidence,
                matched_tables="|".join(matched_tables),
                matched_files=len(matched_files),
                row_count=row_count,
                first_date=first_date.isoformat() if first_date else None,
                last_date=last_date.isoformat() if last_date else None,
                observed_sessions=observed_sessions,
                expected_sessions=expected_sessions,
                missing_sessions=missing_sessions,
                coverage_percent=(
                    f"{coverage:.2f}" if coverage is not None else None
                ),
                certification_ready=ready,
                limitation=limitation,
            )
        )

    return tuple(rows)


def export_inventory(
    rows: tuple[DatasetInventoryRow, ...],
    *,
    year: int,
    output: Path,
) -> tuple[Path, ...]:
    output.mkdir(parents=True, exist_ok=True)
    required = tuple(row for row in rows if row.required)
    blockers = tuple(
        row
        for row in rows
        if row.blocking and not row.certification_ready
    )
    ready_count = sum(row.certification_ready for row in required)
    score = round((ready_count / len(required)) * 100, 2) if required else 0.0
    certification = "CERTIFIED" if not blockers else "NOT_CERTIFIED"
    next_action = (
        blockers[0].dataset_name
        if blockers
        else f"Freeze the certified {year} research dataset."
    )

    dataset_inventory = output / "dataset_inventory.csv"
    _write_csv(dataset_inventory, (asdict(row) for row in rows))

    capability_matrix = output / "capability_matrix.csv"
    _write_csv(
        capability_matrix,
        (
            {
                "capability": row.capability,
                "dataset_key": row.dataset_key,
                "status": (
                    "READY"
                    if row.certification_ready
                    else "BLOCKED"
                    if row.blocking
                    else "PARTIAL"
                ),
                "missing_dependency": (
                    "" if row.certification_ready else row.dataset_name
                ),
            }
            for row in rows
        ),
    )

    coverage_report = output / "coverage_report.csv"
    _write_csv(
        coverage_report,
        (
            {
                "dataset_key": row.dataset_key,
                "status": row.status,
                "row_count": row.row_count,
                "first_date": row.first_date,
                "last_date": row.last_date,
                "observed_sessions": row.observed_sessions,
                "expected_sessions": row.expected_sessions,
                "missing_sessions": row.missing_sessions,
                "coverage_percent": row.coverage_percent,
            }
            for row in rows
        ),
    )

    missing_items = output / "missing_items.csv"
    _write_csv(
        missing_items,
        (asdict(row) for row in rows if not row.certification_ready),
    )

    readiness_dashboard = output / "readiness_dashboard.csv"
    _write_csv(
        readiness_dashboard,
        (
            {
                "research_area": row.dataset_name,
                "capability": row.capability,
                "status": row.status,
                "blocking": row.blocking,
                "recommended_action": row.limitation,
            }
            for row in rows
        ),
    )

    summary = {
        "classification": "RESEARCH_DATASET_INVENTORY_V1",
        "year": year,
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "production_influence": PRODUCTION_INFLUENCE,
        "dataset_count": len(rows),
        "required_dataset_count": len(required),
        "required_ready_count": ready_count,
        "blocking_dataset_count": len(blockers),
        "coverage_score_percent": f"{score:.2f}",
        "certification": certification,
        "blocking_datasets": [row.dataset_key for row in blockers],
        "recommended_next_action": next_action,
    }

    summary_path = output / "summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    certification_path = output / "certification.json"
    certification_payload = {
        "year": year,
        "status": certification,
        "coverage_score_percent": f"{score:.2f}",
        "blocking_datasets": [row.dataset_key for row in blockers],
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "production_influence": PRODUCTION_INFLUENCE,
    }
    certification_path.write_text(
        json.dumps(certification_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    report_path = output / "report.md"
    report_path.write_text(_render_report(rows, summary), encoding="utf-8")

    return (
        report_path,
        summary_path,
        dataset_inventory,
        capability_matrix,
        coverage_report,
        certification_path,
        missing_items,
        readiness_dashboard,
    )


def _render_report(
    rows: tuple[DatasetInventoryRow, ...],
    summary: dict[str, object],
) -> str:
    lines = [
        f"# Research Dataset Inventory — {summary['year']}",
        "",
        "**DIAGNOSTIC_ONLY / PRODUCTION_INFLUENCE=false**",
        "",
        f"- Certification: **{summary['certification']}**",
        f"- Coverage score: **{summary['coverage_score_percent']}%**",
        f"- Blocking datasets: **{summary['blocking_dataset_count']}**",
        (
            "- Recommended next action: "
            f"**{summary['recommended_next_action']}**"
        ),
        "",
        "## Dataset Readiness",
        "",
        "| Dataset | Status | Observed | Expected | Coverage | Blocking |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for row in rows:
        coverage = (
            f"{row.coverage_percent}%"
            if row.coverage_percent is not None
            else "UNKNOWN"
        )
        lines.append(
            f"| {row.dataset_name} | {row.status} | "
            f"{row.observed_sessions or 'UNKNOWN'} | "
            f"{row.expected_sessions or 'UNKNOWN'} | {coverage} | "
            f"{'YES' if row.blocking else 'NO'} |"
        )
    lines.extend(
        (
            "",
            "## Scientific Boundary",
            "",
            "- This command inventories evidence; it does not download data.",
            "- Weekdays are a provisional expected-session proxy until the ",
            "  official trading calendar is certified.",
            "- Presence does not equal integrity certification.",
            "- Unknown coverage is never treated as complete.",
            "- No production signal, gate, or portfolio policy is changed.",
            "",
            "**PRODUCTION_INFLUENCE=false**",
            "",
        )
    )
    return "\n".join(lines)


def _table_metadata(database: Path) -> dict[str, tuple[str, ...]]:
    if not database.exists():
        return {}
    connection = duckdb.connect(str(database), read_only=True)
    try:
        rows = connection.execute(
            "SELECT table_schema, table_name "
            "FROM information_schema.tables "
            "WHERE table_type = 'BASE TABLE'"
        ).fetchall()
        result: dict[str, tuple[str, ...]] = {}
        for schema, table in rows:
            columns = connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? "
                "ORDER BY ordinal_position",
                [schema, table],
            ).fetchall()
            key = f"{schema}.{table}".lower()
            result[key] = tuple(str(column[0]).lower() for column in columns)
        return result
    finally:
        connection.close()


def _aggregate_table_evidence(
    database: Path,
    tables: tuple[str, ...],
    year: int,
) -> tuple[int | None, frozenset[date]]:
    if not database.exists() or not tables:
        return None, frozenset()
    connection = duckdb.connect(str(database), read_only=True)
    try:
        total = 0
        observed_dates: set[date] = set()
        used = False
        for qualified in tables:
            schema, table = qualified.split(".", 1)
            columns = connection.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = ? AND table_name = ? "
                "ORDER BY ordinal_position",
                [schema, table],
            ).fetchall()
            column_names = [str(row[0]).lower() for row in columns]
            date_column = next(
                (column for column in DATE_COLUMNS if column in column_names),
                None,
            )
            identifier = f'"{schema}"."{table}"'
            if date_column is not None:
                rows = connection.execute(
                    f'SELECT "{date_column}" FROM {identifier} '
                    f'WHERE EXTRACT(year FROM "{date_column}") = ?',
                    [year],
                ).fetchall()
                total += len(rows)
                for row in rows:
                    value = row[0]
                    if value is None:
                        continue
                    observed_dates.add(
                        value if isinstance(value, date) else value.date()
                    )
                used = True
            else:
                result = connection.execute(
                    f"SELECT COUNT(*) FROM {identifier}"
                ).fetchone()
                if result is None:
                    continue
                total += int(result[0])
                used = True
        return (total if used else None), frozenset(observed_dates)
    except duckdb.Error:
        return None, frozenset()
    finally:
        connection.close()


def _expected_weekday_sessions(
    year: int,
    observed_end: date | None,
) -> int | None:
    if observed_end is None:
        return None
    start = date(year, 1, 1)
    end = min(observed_end, date(year, 12, 31))
    if end < start:
        return 0
    return sum(
        1
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() < 5
    )


def _session_coverage(
    observed_sessions: int | None,
    expected_sessions: int | None,
) -> float | None:
    if observed_sessions is None or expected_sessions is None:
        return None
    if expected_sessions == 0:
        return 0.0
    return min(100.0, observed_sessions / expected_sessions * 100)


def _iter_files(root: Path | None) -> Iterable[Path]:
    if root is None or not root.exists():
        return ()
    return (path for path in root.rglob("*") if path.is_file())


def _matches(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in tokens)


def _write_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    materialized = tuple(rows)
    if not materialized:
        path.write_text("\n", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(materialized[0]))
        writer.writeheader()
        writer.writerows(materialized)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory and certify a Project Alpha research dataset year."
    )
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("alpha_data/warehouse/historical_truth.duckdb"),
    )
    parser.add_argument(
        "--historical-truth-snapshots",
        type=Path,
        default=Path("alpha_data/snapshots"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/research_dataset_inventory/2026"),
    )
    args = parser.parse_args(argv)
    rows = build_inventory(
        year=args.year,
        database=args.database,
        snapshots=args.historical_truth_snapshots,
    )
    paths = export_inventory(rows, year=args.year, output=args.output)
    summary = json.loads(
        (args.output / "summary.json").read_text(encoding="utf-8")
    )
    print("Research Dataset Inventory")
    print(f"Year: {args.year}")
    print(f"Certification: {summary['certification']}")
    print(f"Coverage score: {summary['coverage_score_percent']}%")
    print("DIAGNOSTIC_ONLY=true")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Artifacts: {args.output} ({len(paths)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
