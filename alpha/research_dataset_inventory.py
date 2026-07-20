from __future__ import annotations

import argparse
import csv
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
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
    "ex_date",
    "valid_from",
)


@dataclass(frozen=True, slots=True)
class DatasetDefinition:
    key: str
    name: str
    required: bool
    blocking: bool
    capability: str
    table_names: tuple[str, ...]
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


@dataclass(frozen=True, slots=True)
class TableEvidence:
    row_count: int | None
    observed_dates: frozenset[date]


@dataclass(frozen=True, slots=True)
class SnapshotEvidence:
    dates: frozenset[date]
    availability_counts: Mapping[str, int]
    invalid_files: int


DATASETS: tuple[DatasetDefinition, ...] = (
    DatasetDefinition(
        "daily_ohlcv",
        "Daily OHLCV",
        True,
        True,
        "Historical replay",
        ("daily_candle",),
        ("bhavcopy", "daily_candle"),
    ),
    DatasetDefinition(
        "corporate_actions",
        "Corporate Actions",
        True,
        True,
        "Adjusted returns",
        ("corporate_action",),
        ("corporate_action",),
    ),
    DatasetDefinition(
        "security_identity",
        "Security Identity History",
        True,
        True,
        "Point-in-time identity",
        ("security_identity",),
        ("security_master", "symbol_change"),
    ),
    DatasetDefinition(
        "listing_history",
        "Listing History",
        True,
        True,
        "Survivorship-free replay",
        ("listing_history", "listed_security"),
        ("listing",),
    ),
    DatasetDefinition(
        "delisting_history",
        "Delisting/Suspension History",
        True,
        True,
        "Survivorship-free replay",
        ("delisting_history", "suspension_history"),
        ("delist", "suspension"),
    ),
    DatasetDefinition(
        "trading_calendar",
        "Trading Calendar",
        True,
        True,
        "Session alignment",
        ("trading_calendar", "trading_session", "exchange_holiday"),
        ("holiday", "trading_calendar"),
    ),
    DatasetDefinition(
        "benchmark_history",
        "Benchmark History",
        True,
        True,
        "Benchmark-relative returns",
        ("index_candle", "benchmark_history", "index_price"),
        ("indices", "benchmark", "nifty"),
    ),
    DatasetDefinition(
        "sector_mapping",
        "Historical Sector Mapping",
        True,
        True,
        "Sector attribution",
        ("sector_mapping", "industry_mapping"),
        ("sector", "industry"),
    ),
    DatasetDefinition(
        "index_constituents",
        "Historical Index Constituents",
        True,
        False,
        "Point-in-time universes",
        ("index_constituent", "index_membership"),
        ("constituent", "index_membership"),
    ),
    DatasetDefinition(
        "market_breadth",
        "Market Breadth",
        False,
        False,
        "Market regime",
        ("market_breadth", "advance_decline"),
        ("breadth", "advance_decline"),
    ),
    DatasetDefinition(
        "delivery_percentage",
        "Delivery Percentage",
        False,
        False,
        "Liquidity intelligence",
        ("delivery_percentage", "delivery_history"),
        ("delivery", "deliverable"),
    ),
    DatasetDefinition(
        "volatility_index",
        "Volatility Index",
        False,
        False,
        "Risk regime",
        ("volatility_index", "vix_history"),
        ("vix", "volatility"),
    ),
)


def build_inventory(
    *,
    year: int,
    database: Path,
    snapshots: Path | None,
    as_of: date | None = None,
) -> tuple[DatasetInventoryRow, ...]:
    period_start = date(year, 1, 1)
    period_end = _resolve_period_end(year, as_of)
    tables = _table_metadata(database)
    files = tuple(_iter_files(snapshots))
    snapshot_evidence = _snapshot_evidence(
        snapshots,
        period_start=period_start,
        period_end=period_end,
    )
    rows: list[DatasetInventoryRow] = []

    for definition in DATASETS:
        matched_tables = _matched_tables(tables, definition.table_names)
        matched_files = tuple(
            path
            for path in files
            if _matches(str(path).lower(), definition.path_tokens)
        )
        table_evidence = _aggregate_table_evidence(
            database,
            matched_tables,
            period_start=period_start,
            period_end=period_end,
        )
        row = _build_row(
            definition=definition,
            database=database,
            matched_tables=matched_tables,
            matched_files=matched_files,
            table_evidence=table_evidence,
            snapshot_evidence=snapshot_evidence,
            period_start=period_start,
            period_end=period_end,
        )
        rows.append(row)

    return tuple(rows)


def export_inventory(
    rows: tuple[DatasetInventoryRow, ...],
    *,
    year: int,
    output: Path,
    as_of: date | None = None,
) -> tuple[Path, ...]:
    output.mkdir(parents=True, exist_ok=True)
    period_end = _resolve_period_end(year, as_of)
    required = tuple(row for row in rows if row.required)
    blockers = tuple(
        row for row in rows if row.blocking and not row.certification_ready
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
                "status": _capability_status(row),
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
        "period_end": period_end.isoformat(),
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
        "period_end": period_end.isoformat(),
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


def _build_row(
    *,
    definition: DatasetDefinition,
    database: Path,
    matched_tables: tuple[str, ...],
    matched_files: tuple[Path, ...],
    table_evidence: TableEvidence,
    snapshot_evidence: SnapshotEvidence,
    period_start: date,
    period_end: date,
) -> DatasetInventoryRow:
    if definition.key == "daily_ohlcv":
        return _daily_ohlcv_row(
            definition=definition,
            matched_tables=matched_tables,
            matched_files=matched_files,
            table_evidence=table_evidence,
            snapshot_evidence=snapshot_evidence,
            period_start=period_start,
            period_end=period_end,
        )
    if definition.key == "security_identity":
        return _identity_row(
            definition=definition,
            database=database,
            matched_tables=matched_tables,
            matched_files=matched_files,
            table_evidence=table_evidence,
            snapshot_evidence=snapshot_evidence,
            period_start=period_start,
            period_end=period_end,
        )
    if definition.key == "trading_calendar" and not matched_tables:
        return _derived_calendar_row(
            definition=definition,
            snapshot_evidence=snapshot_evidence,
            period_start=period_start,
            period_end=period_end,
            matched_files=matched_files,
        )
    return _generic_row(
        definition=definition,
        matched_tables=matched_tables,
        matched_files=matched_files,
        table_evidence=table_evidence,
        snapshot_evidence=snapshot_evidence,
        period_start=period_start,
        period_end=period_end,
    )


def _daily_ohlcv_row(
    *,
    definition: DatasetDefinition,
    matched_tables: tuple[str, ...],
    matched_files: tuple[Path, ...],
    table_evidence: TableEvidence,
    snapshot_evidence: SnapshotEvidence,
    period_start: date,
    period_end: date,
) -> DatasetInventoryRow:
    observed_dates = table_evidence.observed_dates
    expected = _weekday_count(period_start, period_end)
    observed = len(observed_dates) if observed_dates else None
    coverage = _session_coverage(observed, expected)
    snapshot_dates = snapshot_evidence.dates
    missing_snapshots = observed_dates - snapshot_dates
    extra_snapshots = snapshot_dates - observed_dates
    reconciled = bool(observed_dates) and not missing_snapshots and not extra_snapshots
    status = "MISSING"
    ready = False
    limitation = "Canonical daily_candle rows were not found for the period."
    if table_evidence.row_count == 0 and matched_tables:
        status = "PRESENT_EMPTY"
        limitation = "The daily_candle table exists but has no period rows."
    elif observed_dates:
        if reconciled and snapshot_evidence.invalid_files == 0:
            status = "COMPLETE_CANDIDATE"
            ready = True
            limitation = (
                "Warehouse sessions reconcile with dated historical-truth "
                "snapshots. Official-calendar certification remains separate."
            )
        else:
            status = "PARTIAL"
            limitation = (
                f"Snapshot reconciliation failed: missing={len(missing_snapshots)}, "
                f"extra={len(extra_snapshots)}, "
                f"invalid={snapshot_evidence.invalid_files}."
            )
    evidence = _evidence_text(
        matched_tables,
        matched_files,
        extras=(
            f"warehouse_sessions={len(observed_dates)}",
            f"snapshot_sessions={len(snapshot_dates)}",
        ),
    )
    return _row(
        definition=definition,
        status=status,
        evidence=evidence,
        matched_tables=matched_tables,
        matched_files=matched_files,
        row_count=table_evidence.row_count,
        observed_dates=observed_dates,
        expected_sessions=expected if observed_dates else None,
        coverage=coverage,
        ready=ready,
        limitation=limitation,
    )


def _identity_row(
    *,
    definition: DatasetDefinition,
    database: Path,
    matched_tables: tuple[str, ...],
    matched_files: tuple[Path, ...],
    table_evidence: TableEvidence,
    snapshot_evidence: SnapshotEvidence,
    period_start: date,
    period_end: date,
) -> DatasetInventoryRow:
    total, with_isin = _candle_isin_coverage(
        database,
        period_start=period_start,
        period_end=period_end,
    )
    isin_coverage = (with_isin / total * 100) if total else None
    snapshot_identity = snapshot_evidence.availability_counts.get("identity", 0)
    has_dedicated_rows = bool(table_evidence.row_count)
    present = bool(matched_tables or matched_files or with_isin or snapshot_identity)
    status = "MISSING"
    limitation = "No point-in-time identity evidence was found."
    if present:
        status = "PARTIAL"
        limitation = (
            "Candle ISIN and/or snapshot identity evidence exists, but the "
            "dedicated effective-dated identity history is not complete."
        )
        if has_dedicated_rows and isin_coverage is not None and isin_coverage >= 99:
            status = "COMPLETE_CANDIDATE"
            limitation = (
                "Dedicated identity history and near-complete candle ISIN "
                "coverage exist; transition integrity still requires audit."
            )
    evidence = _evidence_text(
        matched_tables,
        matched_files,
        extras=(
            f"candle_rows={total}",
            f"candle_isin_rows={with_isin}",
            (
                f"candle_isin_coverage={isin_coverage:.2f}%"
                if isin_coverage is not None
                else "candle_isin_coverage=UNKNOWN"
            ),
            f"identity_snapshots={snapshot_identity}",
        ),
    )
    return _row(
        definition=definition,
        status=status,
        evidence=evidence,
        matched_tables=matched_tables,
        matched_files=matched_files,
        row_count=table_evidence.row_count,
        observed_dates=table_evidence.observed_dates,
        expected_sessions=None,
        coverage=isin_coverage,
        ready=status == "COMPLETE_CANDIDATE",
        limitation=limitation,
    )


def _derived_calendar_row(
    *,
    definition: DatasetDefinition,
    snapshot_evidence: SnapshotEvidence,
    period_start: date,
    period_end: date,
    matched_files: tuple[Path, ...],
) -> DatasetInventoryRow:
    observed = snapshot_evidence.dates
    expected = _weekday_count(period_start, period_end)
    coverage = _session_coverage(len(observed) if observed else None, expected)
    status = "DERIVED_ONLY" if observed else "MISSING"
    limitation = (
        "Observed sessions can be derived from snapshots, but the official "
        "exchange trading calendar and holiday evidence are not certified."
        if observed
        else "No official or derived session evidence was found."
    )
    return _row(
        definition=definition,
        status=status,
        evidence=_evidence_text(
            (),
            matched_files,
            extras=(f"derived_snapshot_sessions={len(observed)}",),
        ),
        matched_tables=(),
        matched_files=matched_files,
        row_count=None,
        observed_dates=observed,
        expected_sessions=expected if observed else None,
        coverage=coverage,
        ready=False,
        limitation=limitation,
    )


def _generic_row(
    *,
    definition: DatasetDefinition,
    matched_tables: tuple[str, ...],
    matched_files: tuple[Path, ...],
    table_evidence: TableEvidence,
    snapshot_evidence: SnapshotEvidence,
    period_start: date,
    period_end: date,
) -> DatasetInventoryRow:
    snapshot_key = {
        "corporate_actions": "corporate_actions",
        "benchmark_history": "indices",
        "delivery_percentage": "delivery",
        "volatility_index": "vix",
    }.get(definition.key)
    snapshot_count = (
        snapshot_evidence.availability_counts.get(snapshot_key, 0)
        if snapshot_key
        else 0
    )
    present = bool(matched_tables or matched_files or snapshot_count)
    status = "MISSING"
    limitation = "No matching warehouse, archive, or snapshot evidence found."
    ready = False
    observed_dates = table_evidence.observed_dates
    expected = _weekday_count(period_start, period_end)
    observed = len(observed_dates) if observed_dates else None
    coverage = _session_coverage(observed, expected)
    if table_evidence.row_count == 0 and matched_tables and not snapshot_count:
        status = "PRESENT_EMPTY"
        limitation = "A canonical table exists but has no rows for the period."
    elif present:
        status = "PARTIAL"
        limitation = (
            "Dataset evidence exists, but annual completeness and "
            "dataset-specific integrity are not yet proven."
        )
        if observed_dates and coverage is not None and coverage >= 95:
            status = "COMPLETE_CANDIDATE"
            ready = True
            limitation = (
                "Observed period coverage is adequate; dataset-specific "
                "integrity certification is still required."
            )
    evidence = _evidence_text(
        matched_tables,
        matched_files,
        extras=(f"available_snapshots={snapshot_count}",) if snapshot_key else (),
    )
    return _row(
        definition=definition,
        status=status,
        evidence=evidence,
        matched_tables=matched_tables,
        matched_files=matched_files,
        row_count=table_evidence.row_count,
        observed_dates=observed_dates,
        expected_sessions=expected if observed_dates else None,
        coverage=coverage,
        ready=ready,
        limitation=limitation,
    )


def _row(
    *,
    definition: DatasetDefinition,
    status: str,
    evidence: str,
    matched_tables: tuple[str, ...],
    matched_files: tuple[Path, ...],
    row_count: int | None,
    observed_dates: frozenset[date],
    expected_sessions: int | None,
    coverage: float | None,
    ready: bool,
    limitation: str,
) -> DatasetInventoryRow:
    first_date = min(observed_dates) if observed_dates else None
    last_date = max(observed_dates) if observed_dates else None
    observed_sessions = len(observed_dates) if observed_dates else None
    missing_sessions = (
        max(expected_sessions - observed_sessions, 0)
        if expected_sessions is not None and observed_sessions is not None
        else None
    )
    return DatasetInventoryRow(
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
        coverage_percent=f"{coverage:.2f}" if coverage is not None else None,
        certification_ready=ready,
        limitation=limitation,
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
        f"- Period end: **{summary['period_end']}**",
        f"- Certification: **{summary['certification']}**",
        f"- Coverage score: **{summary['coverage_score_percent']}%**",
        f"- Blocking datasets: **{summary['blocking_dataset_count']}**",
        (f"- Recommended next action: **{summary['recommended_next_action']}**"),
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
            (
                "- Weekdays are a provisional expected-session proxy until the "
                "official trading calendar is certified."
            ),
            "- Daily OHLCV readiness requires warehouse/snapshot reconciliation.",
            "- Embedded candle ISINs do not replace effective-dated identity history.",
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
            result[f"{schema}.{table}".lower()] = tuple(
                str(column[0]).lower() for column in columns
            )
        return result
    finally:
        connection.close()


def _aggregate_table_evidence(
    database: Path,
    tables: tuple[str, ...],
    *,
    period_start: date,
    period_end: date,
) -> TableEvidence:
    if not database.exists() or not tables:
        return TableEvidence(None, frozenset())
    connection = duckdb.connect(str(database), read_only=True)
    try:
        total = 0
        dates: set[date] = set()
        used = False
        for qualified in tables:
            schema, table = qualified.split(".", 1)
            columns = _columns(connection, schema, table)
            date_column = next(
                (column for column in DATE_COLUMNS if column in columns),
                None,
            )
            identifier = f'"{schema}"."{table}"'
            if date_column is None:
                result = connection.execute(
                    f"SELECT COUNT(*) FROM {identifier}"
                ).fetchone()
                if result is not None:
                    total += int(result[0])
                    used = True
                continue
            rows = connection.execute(
                f'SELECT "{date_column}", COUNT(*) FROM {identifier} '
                f'WHERE "{date_column}" BETWEEN ? AND ? '
                f'GROUP BY "{date_column}" ORDER BY "{date_column}"',
                [period_start, period_end],
            ).fetchall()
            for value, count in rows:
                normalized = _as_date(value)
                if normalized is not None:
                    dates.add(normalized)
                total += int(count)
            used = True
        return TableEvidence(total if used else None, frozenset(dates))
    except duckdb.Error:
        return TableEvidence(None, frozenset())
    finally:
        connection.close()


def _candle_isin_coverage(
    database: Path,
    *,
    period_start: date,
    period_end: date,
) -> tuple[int, int]:
    if not database.exists():
        return 0, 0
    connection = duckdb.connect(str(database), read_only=True)
    try:
        if not _table_exists(connection, "main", "daily_candle"):
            return 0, 0
        result = connection.execute(
            "SELECT COUNT(*), "
            "COUNT(*) FILTER (WHERE isin IS NOT NULL AND TRIM(isin) <> '') "
            "FROM main.daily_candle WHERE trading_date BETWEEN ? AND ?",
            [period_start, period_end],
        ).fetchone()
        if result is None:
            return 0, 0
        return int(result[0]), int(result[1])
    except duckdb.Error:
        return 0, 0
    finally:
        connection.close()


def _snapshot_evidence(
    root: Path | None,
    *,
    period_start: date,
    period_end: date,
) -> SnapshotEvidence:
    dates: set[date] = set()
    availability_counts: dict[str, int] = {}
    invalid = 0
    if root is None or not root.exists():
        return SnapshotEvidence(frozenset(), availability_counts, invalid)
    for path in sorted(root.rglob("*.json")):
        snapshot_date = _date_from_filename(path)
        if snapshot_date is None:
            continue
        if not period_start <= snapshot_date <= period_end:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            invalid += 1
            continue
        dates.add(snapshot_date)
        availability = payload.get("availability", {})
        if isinstance(availability, dict):
            for key, value in availability.items():
                if bool(value):
                    normalized = str(key).lower()
                    availability_counts[normalized] = (
                        availability_counts.get(normalized, 0) + 1
                    )
    return SnapshotEvidence(
        frozenset(dates),
        availability_counts,
        invalid,
    )


def _matched_tables(
    tables: Mapping[str, tuple[str, ...]],
    names: tuple[str, ...],
) -> tuple[str, ...]:
    expected = set(names)
    return tuple(
        sorted(
            qualified for qualified in tables if qualified.split(".", 1)[-1] in expected
        )
    )


def _columns(
    connection: duckdb.DuckDBPyConnection,
    schema: str,
    table: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = ? AND table_name = ? "
        "ORDER BY ordinal_position",
        [schema, table],
    ).fetchall()
    return tuple(str(row[0]).lower() for row in rows)


def _table_exists(
    connection: duckdb.DuckDBPyConnection,
    schema: str,
    table: str,
) -> bool:
    result = connection.execute(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = ? AND table_name = ?",
        [schema, table],
    ).fetchone()
    return bool(result and result[0])


def _evidence_text(
    tables: tuple[str, ...],
    files: tuple[Path, ...],
    *,
    extras: tuple[str, ...] = (),
) -> str:
    parts = [
        f"tables={','.join(tables)}" if tables else "",
        f"files={len(files)}" if files else "",
        *extras,
    ]
    return "; ".join(part for part in parts if part) or "none"


def _capability_status(row: DatasetInventoryRow) -> str:
    if row.certification_ready:
        return "READY"
    return "BLOCKED" if row.blocking else "PARTIAL"


def _resolve_period_end(year: int, as_of: date | None) -> date:
    year_end = date(year, 12, 31)
    if as_of is None:
        return year_end
    if as_of.year < year:
        raise ValueError("as_of cannot be before the requested year")
    return min(as_of, year_end)


def _weekday_count(start: date, end: date) -> int:
    return sum(
        1
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() < 5
    )


def _session_coverage(
    observed_sessions: int | None,
    expected_sessions: int | None,
) -> float | None:
    if observed_sessions is None or expected_sessions is None or expected_sessions == 0:
        return None
    return min(100.0, observed_sessions / expected_sessions * 100)


def _iter_files(root: Path | None) -> Iterable[Path]:
    if root is None or not root.exists():
        return ()
    return (path for path in root.rglob("*") if path.is_file())


def _matches(value: str, tokens: tuple[str, ...]) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in tokens)


def _date_from_filename(path: Path) -> date | None:
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def _as_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _write_csv(path: Path, rows: Iterable[dict[str, object]]) -> None:
    materialized = tuple(rows)
    if not materialized:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = tuple(materialized[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(materialized)


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD format") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory and certify a Project Alpha research dataset year."
    )
    parser.add_argument("--year", type=int, default=2026)
    parser.add_argument("--as-of", type=str, default=None)
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
    as_of = _parse_date(args.as_of)
    rows = build_inventory(
        year=args.year,
        database=args.database,
        snapshots=args.historical_truth_snapshots,
        as_of=as_of,
    )
    paths = export_inventory(
        rows,
        year=args.year,
        output=args.output,
        as_of=as_of,
    )
    summary = json.loads((args.output / "summary.json").read_text(encoding="utf-8"))
    print("Research Dataset Inventory")
    print(f"Year: {args.year}")
    print(f"Period end: {summary['period_end']}")
    print(f"Certification: {summary['certification']}")
    print(f"Coverage score: {summary['coverage_score_percent']}%")
    print("DIAGNOSTIC_ONLY=true")
    print("PRODUCTION_INFLUENCE=false")
    print(f"Artifacts: {args.output} ({len(paths)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
