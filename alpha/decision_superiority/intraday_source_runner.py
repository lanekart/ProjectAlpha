"""Operator-facing assembly of the DSI-013 intraday source certificate."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any, cast

from alpha.decision_superiority.intraday_execution_models import (
    IntradayBar,
    IntradayExecutionError,
    IntradayExecutionPolicy,
    IntradaySourceRequest,
)
from alpha.decision_superiority.intraday_execution_population import (
    load_signed_intraday_population,
)
from alpha.decision_superiority.intraday_execution_reconciliation import (
    DailyCandleReference,
    InstrumentResolution,
    parse_upstox_instrument_payload,
    resolve_upstox_nse_equity,
)
from alpha.decision_superiority.intraday_execution_source import (
    cache_paths,
    fetch_upstox_v3_bars,
)
from alpha.decision_superiority.intraday_source_artifacts import (
    export_intraday_source_certification,
)
from alpha.decision_superiority.intraday_source_certification import (
    GovernedIntradaySourceCertificationEngine,
    IntradaySourceCertificationResult,
    IntradaySourceEvidence,
)


class IntradaySourceCertificationRunner:
    """Assemble candidate, instrument, cached/fetched, and daily source evidence."""

    def run(
        self,
        *,
        source_commit: str,
        dsi009_certificate: Path,
        instrument_json: Path,
        daily_reference_csv: Path,
        cache_root: Path,
        output: Path,
        access_token: str = "",
        policy: IntradayExecutionPolicy | None = None,
    ) -> tuple[IntradaySourceCertificationResult, tuple[Path, ...]]:
        """Run and export one complete fail-closed source-certification package."""

        active_policy = policy or IntradayExecutionPolicy()
        population = load_signed_intraday_population(
            dsi009_certificate,
            policy=active_policy,
        )
        instrument_payload = _read_json_or_gzip(instrument_json)
        records = parse_upstox_instrument_payload(instrument_payload)
        instrument_sha256 = _sha256(instrument_json)
        identities = sorted({request.identity_key for request in population.requests})
        resolutions: dict[str, InstrumentResolution] = {
            identity: resolve_upstox_nse_equity(
                identity,
                records,
                source_sha256=instrument_sha256,
            )
            for identity in identities
        }
        daily = load_daily_references(daily_reference_csv)
        bars: dict[tuple[str, date], tuple[IntradayBar, ...]] = {}
        for request in population.requests:
            resolution = resolutions[request.identity_key]
            if resolution.instrument is None:
                continue
            source_request = IntradaySourceRequest(
                governed_identity=request.identity_key,
                instrument_key=resolution.instrument.instrument_key,
                from_date=request.session_date,
                to_date=request.session_date,
            )
            raw_path, manifest_path = cache_paths(
                cache_root,
                source_request,
                policy=active_policy,
            )
            cache_complete = raw_path.is_file() and manifest_path.is_file()
            if not cache_complete and not access_token.strip():
                continue
            try:
                bars[(request.identity_key, request.session_date)] = (
                    fetch_upstox_v3_bars(
                        source_request,
                        access_token=(access_token if access_token.strip() else "CACHE"),
                        cache_root=cache_root,
                        policy=active_policy,
                    )
                )
            except (OSError, IntradayExecutionError, ValueError):
                bars[(request.identity_key, request.session_date)] = ()

        result = GovernedIntradaySourceCertificationEngine().run(
            IntradaySourceEvidence(
                source_commit=source_commit,
                population=population,
                identity_resolutions=resolutions,
                bars_by_request=bars,
                daily_by_request=daily,
            ),
            policy=active_policy,
        )
        return result, export_intraday_source_certification(result, output)


def load_daily_references(
    path: Path,
) -> dict[tuple[str, date], DailyCandleReference]:
    """Load exact governed RAW daily references from an immutable CSV extract."""

    if not path.is_file():
        raise IntradayExecutionError("DSI013_DAILY_REFERENCE_CSV_MISSING")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = tuple(dict(row) for row in csv.DictReader(handle))
    if not rows:
        raise IntradayExecutionError("DSI013_DAILY_REFERENCE_CSV_EMPTY")
    source_file_hash = _sha256(path)
    references: dict[tuple[str, date], DailyCandleReference] = {}
    for index, row in enumerate(rows):
        identity = _text(row, ("identity_key", "governed_identity"), index=index)
        session = _date_value(row, ("session_date", "trading_date"), index=index)
        source_hash = str(row.get("source_sha256") or source_file_hash).strip()
        reference = DailyCandleReference(
            governed_identity=identity,
            session_date=session,
            open=_number(row, ("open", "raw_open"), index=index),
            high=_number(row, ("high", "raw_high"), index=index),
            low=_number(row, ("low", "raw_low"), index=index),
            close=_number(row, ("close", "raw_close"), index=index),
            volume=_integer(row, ("volume", "raw_volume"), index=index),
            price_basis=str(row.get("price_basis") or "RAW").strip(),
            source_sha256=source_hash,
        )
        key = (identity, session)
        existing = references.get(key)
        if existing is not None and existing != reference:
            raise IntradayExecutionError(
                f"DSI013_DAILY_REFERENCE_DUPLICATE_CONFLICT:{identity}:{session}"
            )
        references[key] = reference
    return references


def _read_json_or_gzip(path: Path) -> object:
    if not path.is_file():
        raise IntradayExecutionError("DSI013_INSTRUMENT_SOURCE_MISSING")
    try:
        if path.suffix.lower() == ".gz":
            with gzip.open(path, "rt", encoding="utf-8") as handle:
                return json.load(handle)
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntradayExecutionError("DSI013_INSTRUMENT_SOURCE_UNREADABLE") from exc


def _text(
    row: Mapping[str, object],
    fields: tuple[str, ...],
    *,
    index: int,
) -> str:
    for field in fields:
        value = str(row.get(field) or "").strip()
        if value:
            return value
    raise IntradayExecutionError(
        f"DSI013_DAILY_REFERENCE_FIELD_MISSING:{index}:{'|'.join(fields)}"
    )


def _date_value(
    row: Mapping[str, object],
    fields: tuple[str, ...],
    *,
    index: int,
) -> date:
    value = _text(row, fields, index=index)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise IntradayExecutionError(
            f"DSI013_DAILY_REFERENCE_DATE_INVALID:{index}:{value}"
        ) from exc


def _number(
    row: Mapping[str, object],
    fields: tuple[str, ...],
    *,
    index: int,
) -> float:
    value = _text(row, fields, index=index)
    try:
        return float(value)
    except ValueError as exc:
        raise IntradayExecutionError(
            f"DSI013_DAILY_REFERENCE_NUMBER_INVALID:{index}:{value}"
        ) from exc


def _integer(
    row: Mapping[str, object],
    fields: tuple[str, ...],
    *,
    index: int,
) -> int:
    value = _number(row, fields, index=index)
    integer = int(value)
    if value != float(integer) or integer < 0:
        raise IntradayExecutionError(
            f"DSI013_DAILY_REFERENCE_INTEGER_INVALID:{index}:{value}"
        )
    return integer


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "IntradaySourceCertificationRunner",
    "load_daily_references",
]
