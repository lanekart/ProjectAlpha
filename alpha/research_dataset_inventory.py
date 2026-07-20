from __future__ import annotations

import argparse
import csv
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import duckdb

DIAGNOSTIC_ONLY = True
PRODUCTION_INFLUENCE = False


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
    coverage_percent: str | None
    certification_ready: bool
    limitation: str
    diagnostic_only: bool = DIAGNOSTIC_ONLY
    production_influence: bool = PRODUCTION_INFLUENCE


DATASETS: tuple[DatasetDefinition, ...] = (
    DatasetDefinition("daily_ohlcv", "Daily OHLCV", True, True, "Historical replay", ("price", "ohlcv", "bhavcopy", "market_data"), ("bhavcopy", "ohlcv", "prices")),
    DatasetDefinition("corporate_actions", "Corporate Actions", True, True, "Adjusted returns", ("corporate_action", "corp_action", "bonus", "split", "dividend"), ("corporate_action", "corp_action")),
    DatasetDefinition("security_identity", "Security Identity History", True, True, "Point-in-time identity", ("security_master", "identity", "isin", "symbol_history"), ("security_master", "identity", "symbol_change")),
    DatasetDefinition("listing_history", "Listing History", True, True, "Survivorship-free replay", ("listing", "listed_security"), ("listing", "listed")),
    DatasetDefinition("delisting_history", "Delisting/Suspension History", True, True, "Survivorship-free replay", ("delist", "suspension", "suspended"), ("delist", "suspension")),
    DatasetDefinition("trading_calendar", "Trading Calendar", True, True, "Session alignment", ("calendar", "trading_session", "holiday"), ("calendar", "holiday")),
    DatasetDefinition("benchmark_history", "Benchmark History", True, True, "Benchmark-relative returns", ("index_price", "benchmark", "nifty"), ("index", "benchmark", "nifty")),
    DatasetDefinition("sector_mapping", "Historical Sector Mapping", True, True, "Sector attribution", ("sector", "industry_mapping"), ("sector", "industry")),
    DatasetDefinition("index_constituents", "Historical Index Constituents", True, False, "Point-in-time universes", ("constituent", "index_membership"), ("constituent", "index_membership")),
    DatasetDefinition("market_breadth", "Market Breadth", False, False, "Market regime", ("breadth", "advance_decline"), ("breadth", "advance_decline")),
    DatasetDefinition("delivery_percentage", "Delivery Percentage", False, False, "Liquidity intelligence", ("delivery", "deliverable"), ("delivery", "deliverable")),
    DatasetDefinition("volatility_index", "Volatility Index", False, False, "Risk regime", ("vix", "volatility_index"), ("vix", "volatility")),
)


def build_inventory(*, year: int, database: Path, snapshots: Path | None) -> tuple[DatasetInventoryRow, ...]:
    tables = _table_metadata(database)
    files = tuple(_iter_files(snapshots))
    rows: list[DatasetInventoryRow] = []
    for definition in DATASETS:
        matched_tables = tuple(sorted(name for name in tables if _matches(name, definition.table_tokens)))
        matched_files = tuple(path for path in files if _matches(str(path).lower(), definition.path_tokens))
        row_count, first_date, last_date = _aggregate_table_evidence(database, matched_tables, year)
        coverage = _coverage_percent(year, first_date, last_date)
        present = bool(matched_tables or matched_files)
        status = "MISSING"
        limitation = "No matching warehouse table or snapshot/raw file found."
        ready = False
        if present:
            if row_count == 0 and matched_tables:
                status = "PRESENT_EMPTY"
                limitation = "Matching warehouse table exists but has no rows for the requested year."
            elif coverage is not None and coverage >= 95:
                status = "COMPLETE_CANDIDATE"
                limitation = "Presence and date span are adequate; dataset-specific integrity certification is still required."
                ready = True
            else:
                status = "PARTIAL"
                limitation = "Dataset evidence exists, but annual date-span coverage is incomplete or cannot be proven."
        evidence = "; ".join(filter(None, (
            f"tables={','.join(matched_tables)}" if matched_tables else "",
            f"files={len(matched_files)}" if matched_files else "",
        ))) or "none"
        rows.append(DatasetInventoryRow(
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
            coverage_percent=f"{coverage:.2f}" if coverage is not None else None,
            certification_ready=ready,
            limitation=limitation,
        ))
    return tuple(rows)


def export_inventory(rows: tuple[DatasetInventoryRow, ...], *, year: int, output: Path) -> tuple[Path, ...]:
    output.mkdir(parents=True, exist_ok=True)
    required = tuple(row for row in rows if row.required)
    blockers = tuple(row for row in rows if row.blocking and not row.certification_ready)
    ready_count = sum(row.certification_ready for row in required)
    score = round((ready_count / len(required)) * 100, 2) if required else 0.0
    certification = "CERTIFIED" if not blockers else "NOT_CERTIFIED"
    next_action = blockers[0].dataset_name if blockers else "Freeze the certified 2026 research dataset."

    dataset_inventory = output / "dataset_inventory.csv"
    _write_csv(dataset_inventory, (asdict(row) for row in rows))
    capability_matrix = output / "capability_matrix.csv"
    _write_csv(capability_matrix, ({
        "capability": row.capability,
        "dataset_key": row.dataset_key,
        "status": "READY" if row.certification_ready else "BLOCKED" if row.blocking else "PARTIAL",
        "missing_dependency": "" if row.certification_ready else row.dataset_name,
    } for row in rows))
    coverage_report = output / "coverage_report.csv"
    _write_csv(coverage_report, ({
        "dataset_key": row.dataset_key,
        "status": row.status,
        "row_count": row.row_count,
        "first_date": row.first_date,
        "last_date": row.last_date,
        "coverage_percent": row.coverage_percent,
    } for row in rows))
    missing_items = output / "missing_items.csv"
    _write_csv(missing_items, (asdict(row) for row in rows if not row.certification_ready))
    readiness_dashboard = output / "readiness_dashboard.csv"
    _write_csv(readiness_dashboard, ({
        "research_area": row.dataset_name,
        "capability": row.capability,
        "status": row.status,
        "blocking": row.blocking,
        "recommended_action": row.limitation,
    } for row in rows))

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
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    certification_path = output / "certification.json"
    certification_path.write_text(json.dumps({
        "year": year,
        "status": certification,
        "coverage_score_percent": f"{score:.2f}",
        "blocking_datasets": [row.dataset_key for row in blockers],
        "diagnostic_only": DIAGNOSTIC_ONLY,
        "production_influence": PRODUCTION_INFLUENCE,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    report_path = output / "report.md"
    report_path.write_text(_render_report(rows, summary), encoding="utf-8")
    return (report_path, summary_path, dataset_inventory, capability_matrix, coverage_report, certification_path, missing_items, readiness_dashboard)


def _render_report(rows: tuple[DatasetInventoryRow, ...], summary: dict[str, object]) -> str:
    lines = [
        f"# Research Dataset Inventory — {summary['year']}",
        "",
        "**DIAGNOSTIC_ONLY / PRODUCTION_INFLUENCE=false**",
        "",
        f"- Certification: **{summary['certification']}**",
        f"- Coverage score: **{summary['coverage_score_percent']}%**",
        f"- Blocking datasets: **{summary['blocking_dataset_count']}**",
        f"- Recommended next action: **{summary['recommended_next_action']}**",
        "",
        "## Dataset Readiness",
        "",
        "| Dataset | Capability | Status | Coverage | Blocking |",
        "|---|---|---|---:|---:|",
    ]
    for row in rows:
        lines.append(f"| {row.dataset_name} | {row.capability} | {row.status} | {row.coverage_percent or 'UNKNOWN'}% | {'YES' if row.blocking else 'NO'} |")
    lines.extend(("", "## Scientific Boundary", "", "- This command inventories evidence; it does not download, normalize, adjust, or promote data.", "- Presence does not equal integrity certification.", "- Unknown coverage remains explicit and is never treated as complete.", "- No production threshold, signal, gate, or portfolio policy is changed.", "", "**PRODUCTION_INFLUENCE=false**", ""))
    return "\n".join(lines)


def _table_metadata(database: Path) -> dict[str, tuple[str, ...]]:
    if not database.exists():
        return {}
    connection = duckdb.connect(str(database), read_only=True)
    try:
        rows = connection.execute("SELECT table_schema, table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE'").fetchall()
        result: dict[str, tuple[str, ...]] = {}
        for schema, table in rows:
            columns = connection.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position", [schema, table]).fetchall()
            result[f"{schema}.{table}".lower()] = tuple(str(column[0]).lower() for column in columns)
        return result
    finally:
        connection.close()


def _aggregate_table_evidence(database: Path, tables: tuple[str, ...], year: int) -> tuple[int | None, date | None, date | None]:
    if not database.exists() or not tables:
        return None, None, None
    connection = duckdb.connect(str(database), read_only=True)
    try:
        total = 0
        earliest: date | None = None
        latest: date | None = None
        used = False
        for qualified in tables:
            schema, table = qualified.split(".", 1)
            columns = [row[0].lower() for row in connection.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = ? AND table_name = ? ORDER BY ordinal_position", [schema, table]).fetchall()]
            date_column = next((column for column in ("trading_date", "session_date", "trade_date", "date", "as_of_date", "effective_date") if column in columns), None)
            identifier = f'"{schema}"."{table}"'
            if date_column:
                result = connection.execute(f'SELECT COUNT(*), MIN("{date_column}"), MAX("{date_column}") FROM {identifier} WHERE EXTRACT(year FROM "{date_column}") = ?', [year]).fetchone()
                count, minimum, maximum = result
                total += int(count)
                if minimum is not None:
                    minimum = minimum if isinstance(minimum, date) else minimum.date()
                    maximum = maximum if isinstance(maximum, date) else maximum.date()
                    earliest = minimum if earliest is None else min(earliest, minimum)
                    latest = maximum if latest is None else max(latest, maximum)
                used = True
            else:
                total += int(connection.execute(f"SELECT COUNT(*) FROM {identifier}").fetchone()[0])
                used = True
        return (total if used else None), earliest, latest
    except duckdb.Error:
        return None, None, None
    finally:
        connection.close()


def _coverage_percent(year: int, first_date: date | None, last_date: date | None) -> float | None:
    if first_date is None or last_date is None:
        return None
    expected_start = date(year, 1, 1)
    expected_end = date(year, 12, 31)
    observed_start = max(first_date, expected_start)
    observed_end = min(last_date, expected_end)
    if observed_end < observed_start:
        return 0.0
    return min(100.0, ((observed_end - observed_start).days + 1) / ((expected_end - expected_start).days + 1) * 100)


def _iter_files(root: Path | None) -> Iterable[Path]:
    if root is None or not root.exists():
        return ()
    return (path for path in root.rglob("*") if path.is_file())


def _matches(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in tokens)


def _write_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    materialized = list(rows)
    if not materialized:
        path.write_text("\n", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(materialized[0]))
        writer.writeheader()
        writer.writerows(materialized)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inventory and certify a Project Alpha research dataset year.")
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--database", type=Path, default=Path("alpha_data/warehouse/historical_truth.duckdb"))
    parser.add_argument("--historical-truth-snapshots", type=Path, default=Path("alpha_data/snapshots"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/research_dataset_inventory/2026"))
    args = parser.parse_args(argv)
    rows = build_inventory(year=args.year, database=args.database, snapshots=args.historical_truth_snapshots)
    paths = export_inventory(rows, year=args.year, output=args.output)
    summary = json.loads((args.output / "summary.json").read_text(encoding="utf-8"))
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
