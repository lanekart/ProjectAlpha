"""Deterministic operator planning artifacts for DSI-013 source acquisition."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from datetime import date, datetime
from enum import Enum
from io import StringIO
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from alpha.decision_superiority.intraday_execution_population import (
    IntradayPopulationPlan,
)

DSI013_PLAN_SUMMARY = "dsi013_intraday_source_plan.json"
DSI013_PLAN_CANDIDATES = "dsi013_intraday_candidates.csv"
DSI013_PLAN_REQUESTS = "dsi013_intraday_requests.csv"
DSI013_DAILY_REFERENCE_TEMPLATE = "dsi013_daily_reference_template.csv"


def export_intraday_population_plan(
    plan: IntradayPopulationPlan,
    output: Path,
) -> tuple[Path, ...]:
    """Export exact candidate/session acquisition scope without source credentials."""

    output.mkdir(parents=True, exist_ok=True)
    candidate_rows = tuple(
        _normalise(asdict(candidate)) for candidate in plan.candidates
    )
    request_rows = tuple(
        {
            "identity_key": request.identity_key,
            "session_date": request.session_date.isoformat(),
            "signal_ids": "|".join(request.signal_ids),
            "signal_count": len(request.signal_ids),
        }
        for request in plan.requests
    )
    template_rows = tuple(
        {
            "identity_key": request.identity_key,
            "session_date": request.session_date.isoformat(),
            "open": "",
            "high": "",
            "low": "",
            "close": "",
            "volume": "",
            "price_basis": "RAW",
            "source_sha256": "",
        }
        for request in plan.requests
    )
    summary = {
        "contract": "DSI-013-SOURCE-PLAN-v1.0.0",
        "candidate_count": len(plan.candidates),
        "unique_request_count": len(plan.requests),
        "excluded_row_count": len(plan.exclusions),
        "dsi009_certificate_sha256": plan.dsi009_certificate_sha256,
        "credential_fields_present": False,
        "full_universe_intraday_sweep": False,
        "one_minute_strategy_mining": False,
        "production_influence": False,
    }
    paths = (
        _write_json(output / DSI013_PLAN_SUMMARY, summary),
        _write_csv(output / DSI013_PLAN_CANDIDATES, candidate_rows),
        _write_csv(output / DSI013_PLAN_REQUESTS, request_rows),
        _write_csv(output / DSI013_DAILY_REFERENCE_TEMPLATE, template_rows),
    )
    return paths


def _write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> Path:
    fields = sorted({str(field) for row in rows for field in row})
    stream = StringIO(newline="")
    if fields:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: _scalar(row.get(field)) for field in fields})
    return _write_text(path, stream.getvalue())


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    return _write_text(
        path,
        json.dumps(_normalise(payload), indent=2, sort_keys=True) + "\n",
    )


def _scalar(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping | list | tuple):
        return json.dumps(_normalise(value), separators=(",", ":"), sort_keys=True)
    return value


def _normalise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_normalise(item) for item in value]
    if isinstance(value, date | datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def _write_text(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)
    return path


__all__ = [
    "DSI013_DAILY_REFERENCE_TEMPLATE",
    "DSI013_PLAN_CANDIDATES",
    "DSI013_PLAN_REQUESTS",
    "DSI013_PLAN_SUMMARY",
    "export_intraday_population_plan",
]
