from __future__ import annotations

import csv
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile

import pyarrow as pa
import pyarrow.parquet as pq

from alpha.historical_truth_acquisition.identity import (
    alpha_security_id,
    build_security_master,
)
from alpha.historical_truth_acquisition.index_membership import (
    IndexMembershipRepository,
)
from alpha.historical_truth_acquisition.models import (
    AcquisitionManifest,
    HTAResult,
    json_value,
)
from alpha.market_truth.warehouse import HistoricalMarketWarehouse

REQUIRED_ARTIFACT_NAMES = (
    "acquisition_manifest.json",
    "security_master.json",
    "daily_history.parquet",
    "index_history.parquet",
    "index_membership.parquet",
    "corporate_actions.parquet",
    "delivery_history.parquet",
    "reconciliation_report.csv",
    "certification_report.md",
    "historical_truth_scorecard.md",
    "warehouse_v2_candidate.json",
    "executive_report.md",
)


class HistoricalTruthExporter:
    def __init__(
        self,
        *,
        output_directory: Path,
        warehouse: HistoricalMarketWarehouse,
        memberships: IndexMembershipRepository,
    ) -> None:
        self.output_directory = output_directory
        self.warehouse = warehouse
        self.memberships = memberships

    def export(
        self,
        *,
        result: HTAResult,
        write_manifest: bool = True,
    ) -> tuple[tuple[Path, ...], AcquisitionManifest]:
        output = self.output_directory
        output.mkdir(parents=True, exist_ok=True)
        paths = (
            self._security_master(output / "security_master.json"),
            self._daily(output / "daily_history.parquet"),
            self._indices(output / "index_history.parquet"),
            self._memberships(output / "index_membership.parquet"),
            self._corporate_actions(output / "corporate_actions.parquet"),
            self._delivery(output / "delivery_history.parquet"),
            self._reconciliation(output / "reconciliation_report.csv", result),
            _write_text(
                output / "certification_report.md", _certification_report(result)
            ),
            _write_text(
                output / "historical_truth_scorecard.md", _scorecard_report(result)
            ),
            _write_json(
                output / "warehouse_v2_candidate.json", result.warehouse_candidate
            ),
            _write_text(output / "executive_report.md", _executive_report(result)),
        )
        hashes = {path.name: sha256(path.read_bytes()).hexdigest() for path in paths}
        manifest = replace(result.manifest, artifact_hashes=hashes)
        manifest_path = output / "acquisition_manifest.json"
        if write_manifest or not manifest_path.exists():
            _write_json(manifest_path, manifest)
        return ((*paths, manifest_path), manifest)

    def _security_master(self, path: Path) -> Path:
        identities = build_security_master(self.warehouse.store.identity_records())
        actions = self.warehouse.store.corporate_action_records()
        lineage = tuple(
            {
                "corporate_action_id": item.corporate_action_id,
                "action_type": item.action_type.value,
                "predecessor": (
                    None
                    if not item.old_isin
                    else alpha_security_id(
                        isin=item.old_isin,
                        exchange=item.exchange.value,
                        symbol=item.old_symbol or "UNKNOWN",
                    )
                ),
                "successor": (
                    None
                    if not item.new_isin
                    else alpha_security_id(
                        isin=item.new_isin,
                        exchange=item.exchange.value,
                        symbol=item.new_symbol or "UNKNOWN",
                    )
                ),
                "old_symbol": item.old_symbol,
                "new_symbol": item.new_symbol,
            }
            for item in actions
            if item.old_isin or item.new_isin or item.old_symbol or item.new_symbol
        )
        return _write_json(
            path,
            {
                "version": "SECURITY_MASTER_v1",
                "identity_count": len(identities),
                "identities": identities,
                "corporate_action_lineage": lineage,
            },
        )

    def _daily(self, path: Path) -> Path:
        records = self.warehouse.store.daily_records()
        rows = [
            {
                "exchange": item.exchange.value,
                "trading_date": item.trading_date,
                "alpha_security_id": alpha_security_id(
                    isin=item.isin,
                    exchange=item.exchange.value,
                    symbol=item.symbol_as_traded,
                ),
                "symbol": item.symbol_as_traded,
                "series": item.series,
                "isin": item.isin,
                "open": item.open,
                "high": item.high,
                "low": item.low,
                "close": item.close,
                "volume": item.volume,
                "turnover": item.turnover,
                "source_file_id": item.source_file_id,
                "record_checksum": item.record_checksum,
            }
            for item in records
        ]
        schema = pa.schema(
            [
                ("exchange", pa.string()),
                ("trading_date", pa.date32()),
                ("alpha_security_id", pa.string()),
                ("symbol", pa.string()),
                ("series", pa.string()),
                ("isin", pa.string()),
                ("open", pa.decimal128(24, 8)),
                ("high", pa.decimal128(24, 8)),
                ("low", pa.decimal128(24, 8)),
                ("close", pa.decimal128(24, 8)),
                ("volume", pa.decimal128(30, 4)),
                ("turnover", pa.decimal128(30, 4)),
                ("source_file_id", pa.string()),
                ("record_checksum", pa.string()),
            ]
        )
        return _write_parquet(path, rows, schema)

    def _indices(self, path: Path) -> Path:
        checksums = {
            item.source_file_id: item.sha256 for item in self.warehouse.vault.records()
        }
        rows = [
            {
                "exchange": item.exchange.value,
                "index_id": item.index_id,
                "index_name": item.index_name,
                "trading_date": item.trading_date,
                "open": item.open,
                "high": item.high,
                "low": item.low,
                "close": item.close,
                "volume": item.volume,
                "source_file_id": item.source_file_id,
                "source_checksum": checksums.get(item.source_file_id),
                "confidence": "HIGH",
                "dataset_version": "INDEX_HISTORY_v1",
            }
            for item in self.warehouse.store.index_records()
        ]
        schema = pa.schema(
            [
                ("exchange", pa.string()),
                ("index_id", pa.string()),
                ("index_name", pa.string()),
                ("trading_date", pa.date32()),
                ("open", pa.decimal128(24, 8)),
                ("high", pa.decimal128(24, 8)),
                ("low", pa.decimal128(24, 8)),
                ("close", pa.decimal128(24, 8)),
                ("volume", pa.decimal128(30, 4)),
                ("source_file_id", pa.string()),
                ("source_checksum", pa.string()),
                ("confidence", pa.string()),
                ("dataset_version", pa.string()),
            ]
        )
        return _write_parquet(path, rows, schema)

    def _memberships(self, path: Path) -> Path:
        records = self.memberships.records()
        schema = pa.schema(
            [
                ("index_name", pa.string()),
                ("effective_date", pa.date32()),
                ("alpha_security_id", pa.string()),
                ("symbol", pa.string()),
                ("isin", pa.string()),
                ("change", pa.string()),
                ("is_member", pa.bool_()),
                ("complete_snapshot", pa.bool_()),
                ("source_file_id", pa.string()),
                ("source", pa.string()),
                ("confidence", pa.string()),
            ]
        )
        normalized: list[dict[str, object]] = [
            {
                "index_name": item.index_name,
                "effective_date": item.effective_date,
                "alpha_security_id": item.alpha_security_id,
                "symbol": item.symbol,
                "isin": item.isin,
                "change": item.change,
                "is_member": item.is_member,
                "complete_snapshot": item.complete_snapshot,
                "source_file_id": item.source_file_id,
                "source": item.source,
                "confidence": item.confidence.value,
            }
            for item in records
        ]
        return _write_parquet(path, normalized, schema)

    def _corporate_actions(self, path: Path) -> Path:
        rows = [
            {
                "corporate_action_id": item.corporate_action_id,
                "alpha_security_id": alpha_security_id(
                    isin=item.old_isin or item.new_isin,
                    exchange=item.exchange.value,
                    symbol=item.old_symbol or item.new_symbol or item.security_id,
                ),
                "exchange": item.exchange.value,
                "action_type": item.action_type.value,
                "announcement_date": item.announcement_date,
                "ex_date": item.ex_date,
                "effective_date": item.effective_date,
                "old_symbol": item.old_symbol,
                "new_symbol": item.new_symbol,
                "old_isin": item.old_isin,
                "new_isin": item.new_isin,
                "source_file_id": item.source_file_id,
                "confidence": item.confidence,
            }
            for item in self.warehouse.store.corporate_action_records()
        ]
        schema = pa.schema(
            [
                ("corporate_action_id", pa.string()),
                ("alpha_security_id", pa.string()),
                ("exchange", pa.string()),
                ("action_type", pa.string()),
                ("announcement_date", pa.date32()),
                ("ex_date", pa.date32()),
                ("effective_date", pa.date32()),
                ("old_symbol", pa.string()),
                ("new_symbol", pa.string()),
                ("old_isin", pa.string()),
                ("new_isin", pa.string()),
                ("source_file_id", pa.string()),
                ("confidence", pa.decimal128(8, 4)),
            ]
        )
        return _write_parquet(path, rows, schema)

    def _delivery(self, path: Path) -> Path:
        with self.warehouse.store.connection() as database:
            raw_rows = database.execute(
                """
                SELECT exchange, trading_date, security_id, symbol, series,
                       deliverable_quantity, deliverable_percentage, source_file_id
                FROM deliverable_history
                ORDER BY trading_date, security_id
                """
            ).fetchall()
        rows = [
            {
                "exchange": row[0],
                "trading_date": row[1],
                "security_id": row[2],
                "symbol": row[3],
                "series": row[4],
                "deliverable_quantity": row[5],
                "deliverable_percentage": row[6],
                "source_file_id": row[7],
            }
            for row in raw_rows
        ]
        schema = pa.schema(
            [
                ("exchange", pa.string()),
                ("trading_date", pa.date32()),
                ("security_id", pa.string()),
                ("symbol", pa.string()),
                ("series", pa.string()),
                ("deliverable_quantity", pa.decimal128(30, 4)),
                ("deliverable_percentage", pa.decimal128(12, 6)),
                ("source_file_id", pa.string()),
            ]
        )
        return _write_parquet(path, rows, schema)

    @staticmethod
    def _reconciliation(path: Path, result: HTAResult) -> Path:
        fieldnames = (
            "finding_id",
            "discrepancy_type",
            "dataset_id",
            "observation_key",
            "sources",
            "severity",
            "explanation",
            "resolved",
        )
        rows = (
            {
                "finding_id": item.finding_id,
                "discrepancy_type": item.discrepancy_type.value,
                "dataset_id": item.dataset_id,
                "observation_key": item.observation_key,
                "sources": "|".join(item.sources),
                "severity": item.severity,
                "explanation": item.explanation,
                "resolved": item.resolved,
            }
            for item in result.reconciliation.findings
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        return path


def _write_parquet(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    schema: pa.Schema,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(list(rows), schema=schema)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(  # type: ignore[no-untyped-call]
        table, temporary, compression="zstd"
    )
    os.replace(temporary, path)
    return path


def _write_json(path: Path, value: object) -> Path:
    return _write_text(
        path, json.dumps(json_value(value), indent=2, sort_keys=True) + "\n"
    )


def _write_text(path: Path, value: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(value)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


def _certification_report(result: HTAResult) -> str:
    lines = [
        "# HTA Certification Report",
        "",
        "Only PASS-certified datasets are eligible for ACTIVE status.",
    ]
    for stage in result.certifications:
        lines.extend(("", f"## {stage.stage.value}: {stage.status.value}"))
        for item in stage.dataset_certifications:
            lines.append(
                f"- `{item.dataset_id}`: **{item.status.value}**; "
                f"score {item.overall_score}; ACTIVE={'YES' if item.active else 'NO'}"
            )
            lines.extend(f"  - {reason}" for reason in item.reasons)
    return "\n".join(lines) + "\n"


def _scorecard_report(result: HTAResult) -> str:
    scorecard = result.scorecard
    lines = [
        "# Historical Truth Scorecard",
        "",
        f"Overall score: **{scorecard.overall_score}/100**",
        f"Activation target: **{scorecard.target_score}/100**",
        f"Target met: **{'YES' if scorecard.target_met else 'NO'}**",
        f"Confidence: **{scorecard.confidence.value}**",
        "",
    ]
    lines.extend(
        f"- {item.stage.value}: {item.score}/100 ({item.certification.value})"
        for item in scorecard.logical_datasets
    )
    return "\n".join(lines) + "\n"


def _executive_report(result: HTAResult) -> str:
    scorecard = result.scorecard
    candidate = result.warehouse_candidate
    acquired = sum(
        item.evidence.source_files
        for stage in result.certifications
        for item in stage.dataset_certifications
    )
    passed = sum(
        item.active
        for stage in result.certifications
        for item in stage.dataset_certifications
    )
    lines = [
        "# Historical Truth Acquisition Executive Report",
        "",
        f"- Official/lawfully supplied source files acquired: **{acquired}**",
        f"- PASS-certified datasets: **{passed}/20**",
        f"- Historical truth score: **{scorecard.overall_score}/100**",
        f"- Warehouse v2 candidate: **{candidate.status.value}**",
        f"- Reconciliation findings: **{len(result.reconciliation.findings)}**",
        "- Automatic source overwrites: **0**",
        "- Replay migration: **NO**",
        "- Production influence: **FALSE**",
        "",
        "## Readiness",
        "",
    ]
    lines.extend(f"- {reason}" for reason in candidate.reasons)
    if acquired == 0:
        lines.extend(
            (
                "",
                "No historical truth was fabricated. Official licensed delivery or "
                "lawfully obtained source files are required before certification "
                "can pass.",
            )
        )
    return "\n".join(lines) + "\n"


__all__ = ["HistoricalTruthExporter", "REQUIRED_ARTIFACT_NAMES"]
