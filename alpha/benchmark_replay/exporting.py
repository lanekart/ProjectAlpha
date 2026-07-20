from __future__ import annotations

import csv
import json
import os
from collections.abc import Mapping
from dataclasses import fields, is_dataclass, replace
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from alpha.benchmark_replay.models import (
    BASELINE_ID,
    BenchmarkReplayReport,
    PositionHistoryRecord,
    TradeRecord,
)
from alpha.benchmark_replay.provenance import file_hash
from alpha.benchmark_replay.rendering import render_executive_report

DEFAULT_BENCHMARK_OUTPUT = Path(".alpha/benchmark") / BASELINE_ID


class BenchmarkArtifactExporter:
    """Write deterministic, idempotent CABR artifacts and checksums."""

    def export(
        self,
        report: BenchmarkReplayReport,
        *,
        output_directory: Path | str = DEFAULT_BENCHMARK_OUTPUT,
    ) -> tuple[Path, ...]:
        output = Path(output_directory)
        self._assert_immutable(output, report)
        output.mkdir(parents=True, exist_ok=True)
        paths = [
            _write_text(
                output / "executive_report.md", render_executive_report(report)
            ),
            _write_csv(
                output / "portfolio_statistics.csv",
                (report.portfolio_statistics,),
            ),
            _write_csv(output / "trade_log.csv", report.trades, row_type=TradeRecord),
            _write_csv(
                output / "position_history.csv",
                report.position_history,
                row_type=PositionHistoryRecord,
            ),
            _write_csv(output / "capital_curve.csv", report.capital_curve),
            _write_csv(
                output / "drawdown_curve.csv",
                tuple(
                    {
                        "observed_on": item.observed_on,
                        "portfolio_value": item.portfolio_value,
                        "drawdown_percent": item.drawdown_percent,
                    }
                    for item in report.capital_curve
                ),
            ),
            _write_csv(output / "monthly_returns.csv", report.monthly_returns),
            _write_csv(output / "yearly_returns.csv", report.yearly_returns),
            _write_csv(
                output / "candidate_statistics.csv",
                report.candidate_statistics,
            ),
            _write_csv(
                output / "approval_statistics.csv",
                report.approval_statistics,
            ),
            _write_csv(
                output / "top_rejection_reasons.csv",
                tuple(
                    {"reason_code": code, "rejected_candidates": count}
                    for code, count in report.top_rejection_reasons
                ),
            ),
            _write_csv(
                output / "decision_eligibility.csv",
                (_decision_eligibility_row(report),),
            ),
            _write_csv(
                output / "opportunity_capture.csv",
                report.opportunity_capture,
            ),
            _write_csv(output / "idle_capital.csv", report.idle_capital),
            _write_csv(
                output / "benchmark_comparison.csv",
                report.benchmark_comparison,
            ),
        ]
        hashes = {path.name: file_hash(path) for path in sorted(paths)}
        frozen_manifest = replace(report.manifest, artifact_hashes=hashes)
        manifest_path = _write_text(
            output / "manifest.json",
            json.dumps(_json_value(frozen_manifest), indent=2, sort_keys=True) + "\n",
        )
        paths.append(manifest_path)
        return tuple(paths)

    @staticmethod
    def _assert_immutable(output: Path, report: BenchmarkReplayReport) -> None:
        manifest_path = output / "manifest.json"
        if not manifest_path.exists():
            return
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if payload.get("input_hash") != report.manifest.input_hash:
            raise ValueError(
                "immutable benchmark output already exists with a different input hash"
            )



def _decision_eligibility_row(report: BenchmarkReplayReport) -> dict[str, object]:
    raw_candidates = sum(
        item.technical_candidates for item in report.candidate_statistics
    )
    approvable_signals = sum(
        item.buy_candidates + item.strong_buy_candidates
        for item in report.candidate_statistics
    )
    status = (
        "BLOCKED_NO_200_SESSION_SECURITIES"
        if report.eligible_securities == 0
        else "ELIGIBLE_POPULATION_AVAILABLE"
    )
    return {
        "status": status,
        "minimum_complete_history_sessions": 200,
        "replay_sessions": report.manifest.sessions,
        "eligible_securities": report.eligible_securities,
        "eligible_security_days": report.eligible_security_observations,
        "raw_technical_candidates": raw_candidates,
        "raw_buy_or_strong_buy_signals": approvable_signals,
        "institutional_approvals": sum(
            item.institutional_approvals for item in report.candidate_statistics
        ),
        "production_influence": False,
    }

def load_manifest(
    output_directory: Path | str = DEFAULT_BENCHMARK_OUTPUT,
) -> dict[str, Any]:
    path = Path(output_directory) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError("benchmark manifest unavailable; run benchmark replay")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("production_influence") is not False
    ):
        raise ValueError("invalid benchmark manifest")
    return {str(key): value for key, value in payload.items()}


def _write_csv(
    path: Path,
    rows: tuple[object, ...],
    *,
    row_type: type[object] | None = None,
) -> Path:
    normalized = tuple(_row(item) for item in rows)
    if normalized:
        headers = tuple(normalized[0])
    elif row_type is not None and is_dataclass(row_type):
        headers = tuple(field.name for field in fields(row_type))
    else:
        headers = ()
    buffer: list[str] = []
    from io import StringIO

    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=headers, lineterminator="\n")
    if headers:
        writer.writeheader()
        writer.writerows(normalized)
    buffer.append(stream.getvalue())
    return _write_text(path, "".join(buffer))


def _row(value: object) -> dict[str, object]:
    if is_dataclass(value) and not isinstance(value, type):
        raw = {field.name: getattr(value, field.name) for field in fields(value)}
    elif isinstance(value, Mapping):
        raw = dict(value)
    else:
        raise TypeError("CSV rows must be dataclasses or mappings")
    return {str(key): _csv_value(item) for key, item in raw.items()}


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, Decimal)):
        return str(value)
    if isinstance(value, dict):
        return json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"))
    if isinstance(value, (tuple, list)):
        return "|".join(str(_csv_value(item)) for item in value)
    return value


def _json_value(value: object) -> object:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(
            {field.name: getattr(value, field.name) for field in fields(value)}
        )
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items())}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, Decimal, Path)):
        return str(value)
    return value


def _write_text(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(text)
        temporary = Path(handle.name)
    os.replace(temporary, path)
    return path


__all__ = [
    "DEFAULT_BENCHMARK_OUTPUT",
    "BenchmarkArtifactExporter",
    "load_manifest",
]
