"""DSI-010B6 governed identity reconstruction and adjusted-replay certification."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any, cast

import duckdb

from alpha.historical_truth.final_official_evidence_closure import (
    _accepted_factors,
    _indexed,
    _materialize_governed_adjustments,
    _raw_candle_fingerprint,
    _records,
    _validate_b1e2,
)
from alpha.historical_truth.legacy_isin_reference_bridge import (
    LegacyIsinReferenceBridge,
)
from alpha.historical_truth.pre2016_identity_sources import (
    OfficialIdentityObservation,
    OfficialIdentitySourceRecord,
    OfficialPre2016IdentityStore,
    ParsedIdentitySource,
    default_identity_source_specs,
    historical_master_evidence_ceiling,
)

DSI010B6_CONTRACT_VERSION = "DSI-010B6-v1.0.0"
DSI010B6_IDENTITY_VERSION = "DSI-010B6-IDENTITY-TIMELINE-v1.0.0"
PRODUCTION_INFLUENCE = False
FULL_BENCHMARK_REPLAYS = 0

SIGNED_B5_WORKFLOW_ID = 30447849010
SIGNED_B5_ARTIFACT_ID = 8723054631
SIGNED_B5_ARTIFACT_DIGEST = (
    "sha256:15bcc743fd876f0467df17a8347561086e483e52256271da3bbe016bf57e487c"
)
SIGNED_B5_FILE_SHA256 = {
    "dsi010b5_remaining_blockers.json": (
        "685228b4f20c7717d854ca9702df554067033f9e1ba854f403d53cb2888b73a8"
    ),
    "dsi010b5_closure_summary.json": (
        "3e4dffd0e43dba7934ca8a20bc1e7a660b2d96bd33b964126a20fa48239f689c"
    ),
    "dsi010b5_adjusted_replay_certificate.json": (
        "3e4dffd0e43dba7934ca8a20bc1e7a660b2d96bd33b964126a20fa48239f689c"
    ),
}


class IdentityCheckpointType(StrEnum):
    EXACT_ISIN_CANDLE = "EXACT_ISIN_CANDLE"
    OFFICIAL_CORPORATE_ACTION = "OFFICIAL_CORPORATE_ACTION"
    OFFICIAL_SECURITY_EVENT = "OFFICIAL_SECURITY_EVENT"
    OFFICIAL_LISTING_PRESS_RELEASE = "OFFICIAL_LISTING_PRESS_RELEASE"


class IdentityIntervalState(StrEnum):
    CERTIFIED_BOUNDED_OFFICIAL_CHECKPOINT_INTERVAL = (
        "CERTIFIED_BOUNDED_OFFICIAL_CHECKPOINT_INTERVAL"
    )
    NO_LOWER_OFFICIAL_CHECKPOINT = "NO_LOWER_OFFICIAL_CHECKPOINT"
    NO_UPPER_OFFICIAL_CHECKPOINT = "NO_UPPER_OFFICIAL_CHECKPOINT"
    CONFLICTING_IDENTITY_CHECKPOINT = "CONFLICTING_IDENTITY_CHECKPOINT"
    SERIES_MISMATCH = "SERIES_MISMATCH"
    DATE_OUTSIDE_INTERVAL = "DATE_OUTSIDE_INTERVAL"
    PAID_HISTORICAL_MASTER_REQUIRED = "PAID_HISTORICAL_MASTER_REQUIRED"


@dataclass(frozen=True, slots=True)
class OfficialIdentityCheckpoint:
    identity_key: str
    isin: str
    symbol: str
    series: str
    effective_date: date
    checkpoint_type: IdentityCheckpointType
    source_id: str
    source_sha256: str
    source_url: str


@dataclass(frozen=True, slots=True)
class ReconstructedIdentityInterval:
    interval_id: str
    identity_key: str
    isin: str
    symbol: str
    series: str
    valid_from: date
    valid_to: date
    lower_checkpoint: OfficialIdentityCheckpoint
    upper_checkpoint: OfficialIdentityCheckpoint
    negative_conflict_checks: tuple[str, ...]
    state: IdentityIntervalState


@dataclass(frozen=True, slots=True)
class ReconstructedBridgeDecision:
    value: str


@dataclass(frozen=True, slots=True)
class ReconstructedBridgeResult:
    decision: ReconstructedBridgeDecision
    certified: bool
    source_contract_id: str
    source_report_sha256: str


@dataclass(frozen=True, slots=True)
class SegmentResolution:
    identity_key: str
    symbol: str
    series: str
    valid_from: date
    valid_to: date
    affected_row_count: int
    previous_reason: str
    final_state: IdentityIntervalState
    interval_id: str | None
    lower_checkpoint_date: date | None
    lower_source_id: str | None
    lower_source_sha256: str | None
    upper_checkpoint_date: date | None
    upper_source_id: str | None
    upper_source_sha256: str | None
    exact_missing_fact: str | None

    @property
    def resolved(self) -> bool:
        return (
            self.final_state
            == IdentityIntervalState.CERTIFIED_BOUNDED_OFFICIAL_CHECKPOINT_INTERVAL
        )


@dataclass(frozen=True, slots=True)
class Pre2016IdentityReconstructionReport:
    summary: dict[str, Any]
    segment_resolutions: tuple[SegmentResolution, ...]
    intervals: tuple[ReconstructedIdentityInterval, ...]
    checkpoints: tuple[OfficialIdentityCheckpoint, ...]
    source_manifest: tuple[OfficialIdentitySourceRecord, ...]
    identity_certificate: dict[str, Any]
    replay_certificate: dict[str, Any]
    report_sha256: str
    certificate_sha256: str


class ReconstructedIdentityBridge:
    """Compose the signed B1 bridge with strict B6 checkpoint intervals."""

    def __init__(
        self,
        baseline: LegacyIsinReferenceBridge,
        intervals: Sequence[ReconstructedIdentityInterval],
    ) -> None:
        self._baseline = baseline
        self._intervals: dict[tuple[str, str, str], tuple[Any, ...]] = defaultdict(
            tuple
        )
        grouped: dict[tuple[str, str, str], list[ReconstructedIdentityInterval]] = (
            defaultdict(list)
        )
        for interval in intervals:
            grouped[(interval.identity_key, interval.symbol, interval.series)].append(
                interval
            )
        self._intervals = {
            key: tuple(sorted(rows, key=lambda item: (item.valid_from, item.valid_to)))
            for key, rows in grouped.items()
        }

    def resolve(
        self,
        *,
        identity_key: str,
        symbol: str,
        series: str,
        isin: str,
        reference_date: date,
        prior_isin_mismatch: bool = False,
    ) -> Any:
        baseline = self._baseline.resolve(
            identity_key=identity_key,
            symbol=symbol,
            series=series,
            isin=isin,
            reference_date=reference_date,
            prior_isin_mismatch=prior_isin_mismatch,
        )
        if baseline.certified:
            return baseline
        matches = tuple(
            interval
            for interval in self._intervals.get(
                (identity_key, symbol.upper(), series.upper()),
                (),
            )
            if interval.valid_from <= reference_date <= interval.valid_to
        )
        if len(matches) != 1:
            return baseline
        interval = matches[0]
        return ReconstructedBridgeResult(
            decision=ReconstructedBridgeDecision(interval.state.value),
            certified=True,
            source_contract_id=DSI010B6_IDENTITY_VERSION,
            source_report_sha256=_digest(_interval_payload(interval)),
        )


class Pre2016IdentityReconstructionEngine:
    """Resolve only identity segments proven by immutable official checkpoints."""

    def run(
        self,
        *,
        database_path: Path,
        root: Path,
        htr009a2_output: Path,
        htr010a3_output: Path,
        htr010b_output: Path,
        final_b1c_output: Path,
        final_b1e2_output: Path,
        signed_b5_output: Path,
        start_date: date,
        end_date: date,
        output: Path,
        refresh_sources: bool = False,
    ) -> Pre2016IdentityReconstructionReport:
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        blockers, b5_summary = _load_signed_b5(signed_b5_output)
        if len(blockers) != 476:
            raise ValueError("signed B5 execution queue must contain 476 segments")
        if sum(int(row["affected_row_count"]) for row in blockers) != 253_358:
            raise ValueError("signed B5 affected-row population changed")

        store = OfficialPre2016IdentityStore(root)
        specs = default_identity_source_specs()
        parsed_sources = (
            store.acquire(specs) if refresh_sources else store.verify_or_missing(specs)
        )
        action_sources = store.acquire_historical_action_checkpoints(
            root=root,
            refresh_sources=refresh_sources,
        )
        checkpoints = _build_checkpoints(
            database_path=database_path,
            blockers=blockers,
            htr009a2_output=htr009a2_output,
            htr010b_output=htr010b_output,
            identity_sources=parsed_sources,
            action_sources=action_sources,
        )
        intervals, resolutions = _resolve_segments(blockers, checkpoints)

        validation = _records(
            final_b1c_output / "htr010b1_factor_validation_results.json"
        )
        _validate_b1e2(final_b1e2_output, validation)
        events = _indexed(
            htr010b_output / "htr010b_canonical_events.json",
            "canonical_event_id",
        )
        factors = _indexed(
            htr010b_output / "htr010b_adjustment_factors.json",
            "canonical_event_id",
        )
        accepted, _ = _accepted_factors(validation, events, factors)
        baseline_bridge = LegacyIsinReferenceBridge.from_output(
            htr009a2_output,
            htr010a3_output=htr010a3_output,
        )
        bridge = ReconstructedIdentityBridge(baseline_bridge, intervals)
        raw_before = _raw_candle_fingerprint(database_path)
        materialization = _materialize_governed_adjustments(
            database_path=database_path,
            output_database=output / "dsi010b6_adjusted_history.duckdb",
            bridge=bridge,
            events=events,
            accepted=accepted,
            start_date=start_date,
            end_date=end_date,
        )
        raw_after = _raw_candle_fingerprint(database_path)
        if raw_before != raw_after:
            raise RuntimeError("canonical raw candles changed during DSI-010B6")

        source_manifest = tuple(
            (
                *(source.inventory for source in parsed_sources),
                *(_action_inventory(source) for source in action_sources),
                historical_master_evidence_ceiling(),
            )
        )
        full_census = _full_canonical_census(
            database_path,
            b5_summary,
            resolutions,
            start_date,
            end_date,
        )
        resolved_segments = sum(row.resolved for row in resolutions)
        resolved_rows = sum(
            row.affected_row_count for row in resolutions if row.resolved
        )
        remaining = tuple(row for row in resolutions if not row.resolved)
        remaining_reason_counts = Counter(row.final_state.value for row in remaining)
        adjusted_ready = (
            not remaining
            and materialization["unresolved_identity_adjustment_row_count"] == 0
            and full_census["unresolved_identity_row_count"] == 0
            and materialization["duplicate_adjusted_row_count"] == 0
            and materialization["invalid_adjusted_row_count"] == 0
            and raw_before == raw_after
        )
        source_manifest_payload = tuple(
            _jsonable(asdict(row)) for row in source_manifest
        )
        interval_payload = tuple(_interval_payload(row) for row in intervals)
        identity_certificate = {
            "contract_version": DSI010B6_CONTRACT_VERSION,
            "identity_version": DSI010B6_IDENTITY_VERSION,
            "canonical_database_raw_fingerprint": raw_before,
            "checkpoint_count": len(checkpoints),
            "certified_interval_count": len(intervals),
            "starting_segment_count": len(blockers),
            "resolved_segment_count": resolved_segments,
            "unresolved_segment_count": len(remaining),
            "starting_affected_row_count": 253_358,
            "newly_certified_affected_row_count": resolved_rows,
            "full_canonical_row_reconciliation": full_census,
            "identity_timeline_sha256": _digest(interval_payload),
            "source_manifest_sha256": _digest(source_manifest_payload),
            "unresolved_segment_sha256": _digest(
                tuple(_jsonable(asdict(row)) for row in remaining)
            ),
            "historical_master_subscription_required": bool(remaining),
            "production_influence": False,
        }
        replay_certificate = {
            "contract_version": DSI010B6_CONTRACT_VERSION,
            "adjusted_replay_ready": adjusted_ready,
            "readiness": (
                "ADJUSTED_REPLAY_CERTIFIED"
                if adjusted_ready
                else "BLOCKED_BY_UNAVAILABLE_OFFICIAL_HISTORICAL_SECURITY_MASTERS"
            ),
            "accepted_factor_count": len(accepted),
            "required_adjustment_row_count": materialization["required_row_count"],
            "adjusted_row_count": materialization["adjusted_row_count"],
            "unresolved_adjustment_row_count": materialization[
                "unresolved_identity_adjustment_row_count"
            ],
            "mixed_price_basis_identity_count": materialization[
                "unresolved_identity_count"
            ],
            "mixed_price_basis_interval_count": materialization[
                "unresolved_identity_segment_count"
            ],
            "duplicate_adjusted_row_count": materialization[
                "duplicate_adjusted_row_count"
            ],
            "invalid_adjusted_ohlc_row_count": materialization[
                "invalid_adjusted_row_count"
            ],
            "adjusted_history_logical_sha256": materialization[
                "adjusted_history_logical_sha256"
            ],
            "raw_candle_fingerprint_before": raw_before,
            "raw_candle_fingerprint_after": raw_after,
            "raw_candles_unchanged": raw_before == raw_after,
            "security_periods_excluded": False,
            "full_benchmark_replays": 0,
            "production_influence": False,
        }
        summary = {
            "contract_version": DSI010B6_CONTRACT_VERSION,
            "signed_b5_workflow_id": SIGNED_B5_WORKFLOW_ID,
            "signed_b5_artifact_id": SIGNED_B5_ARTIFACT_ID,
            "signed_b5_artifact_digest": SIGNED_B5_ARTIFACT_DIGEST,
            "starting_segment_count": 476,
            "starting_missing_official_interval_count": 415,
            "starting_series_mismatch_count": 60,
            "starting_date_outside_interval_count": 1,
            "starting_affected_row_count": 253_358,
            "resolved_segment_count": resolved_segments,
            "newly_certified_affected_row_count": resolved_rows,
            "remaining_segment_count": len(remaining),
            "remaining_affected_row_count": sum(
                row.affected_row_count for row in remaining
            ),
            "remaining_reason_counts": dict(sorted(remaining_reason_counts.items())),
            "certified_interval_count": len(intervals),
            "official_checkpoint_count": len(checkpoints),
            "full_canonical_row_reconciliation": full_census,
            "adjusted_rows_before": int(b5_summary["adjusted_row_count_after"]),
            "adjusted_rows_after": materialization["adjusted_row_count"],
            "mixed_identities_before": int(
                b5_summary["mixed_price_basis_intervals_after"]
            ),
            "mixed_identities_after": materialization["unresolved_identity_count"],
            "mixed_intervals_after": materialization[
                "unresolved_identity_segment_count"
            ],
            "identity_certificate_sha256": _digest(identity_certificate),
            "adjusted_history_sha256": materialization[
                "adjusted_history_logical_sha256"
            ],
            "adjusted_replay_ready": adjusted_ready,
            "readiness": replay_certificate["readiness"],
            "full_benchmark_replays": 0,
            "stop_policy_automatic_promotion_enabled": False,
            "production_influence": False,
            "policy_or_production_behaviour_changed": False,
        }
        report_payload = {
            "summary": summary,
            "identity_certificate": identity_certificate,
            "replay_certificate": replay_certificate,
            "segment_resolutions_sha256": _digest(
                tuple(_jsonable(asdict(row)) for row in resolutions)
            ),
            "source_manifest_sha256": _digest(source_manifest_payload),
        }
        report_sha = _digest(report_payload)
        certificate_sha = _digest(
            {
                "identity_certificate": identity_certificate,
                "replay_certificate": replay_certificate,
                "report_sha256": report_sha,
            }
        )
        summary["report_sha256"] = report_sha
        summary["certificate_sha256"] = certificate_sha
        replay_certificate["certificate_sha256"] = certificate_sha
        return Pre2016IdentityReconstructionReport(
            summary=summary,
            segment_resolutions=resolutions,
            intervals=intervals,
            checkpoints=checkpoints,
            source_manifest=source_manifest,
            identity_certificate=identity_certificate,
            replay_certificate=replay_certificate,
            report_sha256=report_sha,
            certificate_sha256=certificate_sha,
        )


class Pre2016IdentityReconstructionExporter:
    """Export deterministic B6 evidence and signed readiness contracts."""

    def export(
        self,
        report: Pre2016IdentityReconstructionReport,
        output: Path,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        paths = [
            _write_json(output / "dsi010b6_summary.json", report.summary),
            _write_json(
                output / "dsi010b6_identity_certificate.json",
                report.identity_certificate,
            ),
            _write_json(
                output / "dsi010b6_adjusted_replay_certificate.json",
                report.replay_certificate,
            ),
        ]
        for stem, rows in (
            ("dsi010b6_segment_resolutions", report.segment_resolutions),
            ("dsi010b6_identity_intervals", report.intervals),
            ("dsi010b6_identity_checkpoints", report.checkpoints),
            ("dsi010b6_source_manifest", report.source_manifest),
            (
                "dsi010b6_remaining_blockers",
                tuple(row for row in report.segment_resolutions if not row.resolved),
            ),
        ):
            paths.extend(_write_pair(output, stem, rows))
        report_path = output / "dsi010b6_executive_report.md"
        report_path.write_text(_markdown(report), encoding="utf-8")
        paths.append(report_path)
        return tuple(paths)


def _build_checkpoints(
    *,
    database_path: Path,
    blockers: Sequence[dict[str, Any]],
    htr009a2_output: Path,
    htr010b_output: Path,
    identity_sources: Sequence[ParsedIdentitySource],
    action_sources: Sequence[Any],
) -> tuple[OfficialIdentityCheckpoint, ...]:
    blocker_keys = {
        (
            str(row["identity_key"]),
            str(row["symbol"]).upper(),
            str(row["series"]).upper(),
        )
        for row in blockers
    }
    checkpoints: list[OfficialIdentityCheckpoint] = []
    checkpoints.extend(_exact_candle_checkpoints(database_path, blocker_keys))
    checkpoints.extend(_htr010b_event_checkpoints(htr010b_output, blocker_keys))
    checkpoints.extend(_htr009a2_event_checkpoints(htr009a2_output, blocker_keys))
    checkpoints.extend(_historical_action_checkpoints(action_sources, blocker_keys))
    for source in identity_sources:
        checkpoints.extend(
            _observation_checkpoint(item)
            for item in source.observations
            if (item.identity_key, item.symbol, item.series) in blocker_keys
        )
    unique = {
        (
            row.identity_key,
            row.symbol,
            row.series,
            row.effective_date,
            row.source_id,
            row.source_sha256,
        ): row
        for row in checkpoints
    }
    return tuple(
        sorted(
            unique.values(),
            key=lambda row: (
                row.identity_key,
                row.symbol,
                row.series,
                row.effective_date,
                row.source_id,
            ),
        )
    )


def _exact_candle_checkpoints(
    database_path: Path,
    blocker_keys: set[tuple[str, str, str]],
) -> tuple[OfficialIdentityCheckpoint, ...]:
    if not blocker_keys:
        return ()
    with duckdb.connect(str(database_path), read_only=True) as connection:
        connection.execute(
            "CREATE TEMP TABLE b6_key("
            "identity_key VARCHAR,symbol VARCHAR,series VARCHAR)"
        )
        connection.executemany(
            "INSERT INTO b6_key VALUES (?,?,?)",
            sorted(blocker_keys),
        )
        rows = connection.execute(
            """
            WITH exact AS (
                SELECT 'nse:isin:' || upper(trim(c.isin)) AS identity_key,
                       upper(c.symbol) AS symbol, upper(c.series) AS series,
                       c.trading_date, c.source_sha256,
                       row_number() OVER (
                         PARTITION BY upper(trim(c.isin)),upper(c.symbol),
                                      upper(c.series)
                         ORDER BY c.trading_date
                       ) AS first_row,
                       row_number() OVER (
                         PARTITION BY upper(trim(c.isin)),upper(c.symbol),
                                      upper(c.series)
                         ORDER BY c.trading_date DESC
                       ) AS last_row
                FROM daily_candle c
                JOIN b6_key k
                  ON k.identity_key='nse:isin:' || upper(trim(c.isin))
                 AND k.symbol=upper(c.symbol)
                 AND k.series=upper(c.series)
                WHERE c.isin IS NOT NULL AND trim(c.isin)<>''
                  AND c.source_sha256 IS NOT NULL
                  AND trim(c.source_sha256)<>''
            )
            SELECT identity_key,symbol,series,trading_date,source_sha256
            FROM exact WHERE first_row=1 OR last_row=1
            ORDER BY identity_key,symbol,series,trading_date
            """
        ).fetchall()
    return tuple(
        OfficialIdentityCheckpoint(
            identity_key=str(identity),
            isin=str(identity).removeprefix("nse:isin:"),
            symbol=str(symbol),
            series=str(series),
            effective_date=when,
            checkpoint_type=IdentityCheckpointType.EXACT_ISIN_CANDLE,
            source_id=f"canonical_exact_isin_{when.isoformat()}",
            source_sha256=str(source_sha),
            source_url="CANONICAL_OFFICIAL_DAILY_CANDLE",
        )
        for identity, symbol, series, when, source_sha in rows
    )


def _htr010b_event_checkpoints(
    output: Path,
    blocker_keys: set[tuple[str, str, str]],
) -> tuple[OfficialIdentityCheckpoint, ...]:
    events = _records(output / "htr010b_canonical_events.json")
    lineage = {
        str(row["canonical_event_id"]): row
        for row in _records(output / "htr010b_event_lineage.json")
    }
    rows: list[OfficialIdentityCheckpoint] = []
    for event in events:
        identity = str(event.get("governed_identity_id") or "")
        series_values = tuple(event.get("series_applicability") or ())
        if len(series_values) != 1:
            continue
        symbol = str(event.get("symbol") or "").upper()
        series = str(series_values[0]).upper()
        if (identity, symbol, series) not in blocker_keys:
            continue
        raw_lineage = tuple(
            lineage.get(str(event["canonical_event_id"]), {}).get("raw_lineage") or ()
        )
        if not raw_lineage:
            continue
        evidence = raw_lineage[0]
        source_sha = str(evidence.get("source_checksum") or "")
        if len(source_sha) != 64:
            continue
        rows.append(
            OfficialIdentityCheckpoint(
                identity_key=identity,
                isin=identity.removeprefix("nse:isin:"),
                symbol=symbol,
                series=series,
                effective_date=_required_date(event.get("effective_date")),
                checkpoint_type=IdentityCheckpointType.OFFICIAL_CORPORATE_ACTION,
                source_id=str(evidence.get("source_id") or ""),
                source_sha256=source_sha,
                source_url=str(evidence.get("source_url") or ""),
            )
        )
    return tuple(rows)


def _htr009a2_event_checkpoints(
    output: Path,
    blocker_keys: set[tuple[str, str, str]],
) -> tuple[OfficialIdentityCheckpoint, ...]:
    events = _records(output / "htr009a2_security_events.json")
    sources = {
        str(row["source_id"]): row
        for row in _records(output / "htr009a2_source_inventory.json")
    }
    rows: list[OfficialIdentityCheckpoint] = []
    for event in events:
        isin = str(event.get("new_isin") or "").upper()
        symbol = str(event.get("new_symbol") or "").upper()
        series = str(event.get("new_series") or "").upper()
        identity = f"nse:isin:{isin}"
        if (identity, symbol, series) not in blocker_keys:
            continue
        source = sources.get(str(event.get("official_source_id") or ""))
        if source is None or not source.get("sha256"):
            continue
        rows.append(
            OfficialIdentityCheckpoint(
                identity_key=identity,
                isin=isin,
                symbol=symbol,
                series=series,
                effective_date=_required_date(event.get("effective_date")),
                checkpoint_type=IdentityCheckpointType.OFFICIAL_SECURITY_EVENT,
                source_id=str(source["source_id"]),
                source_sha256=str(source["sha256"]),
                source_url=str(source.get("source_url") or ""),
            )
        )
    return tuple(rows)


def _historical_action_checkpoints(
    sources: Sequence[Any],
    blocker_keys: set[tuple[str, str, str]],
) -> tuple[OfficialIdentityCheckpoint, ...]:
    rows: list[OfficialIdentityCheckpoint] = []
    for source in sources:
        lineage = {item.action_id: item for item in source.lineage}
        for event in source.actions:
            identity = str(event.governed_identity_id or "")
            key = (identity, event.symbol.upper(), event.series.upper())
            evidence = lineage.get(event.action_id)
            if key not in blocker_keys or evidence is None:
                continue
            rows.append(
                OfficialIdentityCheckpoint(
                    identity_key=identity,
                    isin=str(event.isin or "").upper(),
                    symbol=event.symbol.upper(),
                    series=event.series.upper(),
                    effective_date=event.effective_date,
                    checkpoint_type=(IdentityCheckpointType.OFFICIAL_CORPORATE_ACTION),
                    source_id=evidence.source_id,
                    source_sha256=evidence.source_sha256,
                    source_url=evidence.source_url,
                )
            )
    return tuple(rows)


def _observation_checkpoint(
    item: OfficialIdentityObservation,
) -> OfficialIdentityCheckpoint:
    return OfficialIdentityCheckpoint(
        identity_key=item.identity_key,
        isin=item.isin,
        symbol=item.symbol,
        series=item.series,
        effective_date=item.effective_date,
        checkpoint_type=IdentityCheckpointType.OFFICIAL_LISTING_PRESS_RELEASE,
        source_id=item.source_id,
        source_sha256=item.source_sha256,
        source_url=item.source_url,
    )


def _resolve_segments(
    blockers: Sequence[dict[str, Any]],
    checkpoints: Sequence[OfficialIdentityCheckpoint],
) -> tuple[
    tuple[ReconstructedIdentityInterval, ...],
    tuple[SegmentResolution, ...],
]:
    by_key: dict[tuple[str, str, str], list[OfficialIdentityCheckpoint]] = defaultdict(
        list
    )
    by_symbol_series: dict[tuple[str, str], list[OfficialIdentityCheckpoint]] = (
        defaultdict(list)
    )
    for checkpoint in checkpoints:
        by_key[(checkpoint.identity_key, checkpoint.symbol, checkpoint.series)].append(
            checkpoint
        )
        by_symbol_series[(checkpoint.symbol, checkpoint.series)].append(checkpoint)
    intervals: list[ReconstructedIdentityInterval] = []
    resolutions: list[SegmentResolution] = []
    for row in blockers:
        identity = str(row["identity_key"])
        symbol = str(row["symbol"]).upper()
        series = str(row["series"]).upper()
        valid_from = _required_date(row["valid_from"])
        valid_to = _required_date(row["valid_to"])
        matches = sorted(
            by_key.get((identity, symbol, series), ()),
            key=lambda item: (item.effective_date, item.source_id),
        )
        lower = tuple(item for item in matches if item.effective_date <= valid_from)
        upper = tuple(item for item in matches if item.effective_date >= valid_to)
        selected_lower = lower[-1] if lower else None
        selected_upper = upper[0] if upper else None
        state = IdentityIntervalState.PAID_HISTORICAL_MASTER_REQUIRED
        exact_fact: str | None
        interval: ReconstructedIdentityInterval | None = None
        if selected_lower is None:
            state = IdentityIntervalState.NO_LOWER_OFFICIAL_CHECKPOINT
            exact_fact = (
                f"An official {symbol}/{series}/{identity} checkpoint on or before "
                f"{valid_from.isoformat()} from the NSE historical Masters product."
            )
        elif selected_upper is None:
            state = IdentityIntervalState.NO_UPPER_OFFICIAL_CHECKPOINT
            exact_fact = (
                f"An official {symbol}/{series}/{identity} checkpoint on or after "
                f"{valid_to.isoformat()}."
            )
        else:
            conflicts = {
                item.identity_key
                for item in by_symbol_series.get((symbol, series), ())
                if selected_lower.effective_date
                <= item.effective_date
                <= selected_upper.effective_date
                and item.identity_key != identity
            }
            if conflicts:
                state = IdentityIntervalState.CONFLICTING_IDENTITY_CHECKPOINT
                exact_fact = (
                    "Authoritative transition evidence separating competing "
                    f"identities: {sorted(conflicts)}."
                )
            else:
                state = (
                    IdentityIntervalState.CERTIFIED_BOUNDED_OFFICIAL_CHECKPOINT_INTERVAL
                )
                exact_fact = None
                payload = {
                    "identity_key": identity,
                    "symbol": symbol,
                    "series": series,
                    "valid_from": valid_from.isoformat(),
                    "valid_to": valid_to.isoformat(),
                    "lower_source": selected_lower.source_sha256,
                    "upper_source": selected_upper.source_sha256,
                }
                interval = ReconstructedIdentityInterval(
                    interval_id=f"dsi010b6-interval:{_digest(payload)}",
                    identity_key=identity,
                    isin=identity.removeprefix("nse:isin:"),
                    symbol=symbol,
                    series=series,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    lower_checkpoint=selected_lower,
                    upper_checkpoint=selected_upper,
                    negative_conflict_checks=(
                        "NO_COMPETING_IDENTITY_CHECKPOINT",
                        "EXACT_SYMBOL_MATCH",
                        "EXACT_SERIES_MATCH",
                        "CHECKPOINT_SOURCE_HASHES_PRESENT",
                    ),
                    state=state,
                )
                intervals.append(interval)
        resolutions.append(
            SegmentResolution(
                identity_key=identity,
                symbol=symbol,
                series=series,
                valid_from=valid_from,
                valid_to=valid_to,
                affected_row_count=int(row["affected_row_count"]),
                previous_reason=str(row["bridge_rejection_reason"]),
                final_state=state,
                interval_id=interval.interval_id if interval else None,
                lower_checkpoint_date=(
                    selected_lower.effective_date if selected_lower else None
                ),
                lower_source_id=(selected_lower.source_id if selected_lower else None),
                lower_source_sha256=(
                    selected_lower.source_sha256 if selected_lower else None
                ),
                upper_checkpoint_date=(
                    selected_upper.effective_date if selected_upper else None
                ),
                upper_source_id=(selected_upper.source_id if selected_upper else None),
                upper_source_sha256=(
                    selected_upper.source_sha256 if selected_upper else None
                ),
                exact_missing_fact=exact_fact,
            )
        )
    return (
        tuple(sorted(intervals, key=lambda item: item.interval_id)),
        tuple(
            sorted(
                resolutions,
                key=lambda item: (
                    item.symbol,
                    item.series,
                    item.valid_from,
                    item.identity_key,
                ),
            )
        ),
    )


def _full_canonical_census(
    database_path: Path,
    b5_summary: Mapping[str, Any],
    resolutions: Sequence[SegmentResolution],
    start_date: date,
    end_date: date,
) -> dict[str, int]:
    with duckdb.connect(str(database_path), read_only=True) as connection:
        row = connection.execute(
            """
            SELECT count(*),
                   count(*) FILTER (
                     WHERE isin IS NOT NULL AND trim(isin)<>''
                   )
            FROM daily_candle
            WHERE trading_date BETWEEN ? AND ?
            """,
            [start_date, end_date],
        ).fetchone()
    if row is None:
        raise RuntimeError("canonical identity census returned no result")
    total, exact = row
    baseline_bridge = int(b5_summary["certified_bridge_adjusted_row_count"])
    reconstructed = sum(row.affected_row_count for row in resolutions if row.resolved)
    governed = int(exact) + baseline_bridge + reconstructed
    if governed > int(total):
        raise ValueError("governed identity reconciliation exceeds canonical rows")
    return {
        "total_canonical_row_count": int(total),
        "exact_isin_certified_row_count": int(exact),
        "signed_b5_bridge_certified_row_count": baseline_bridge,
        "new_b6_interval_certified_row_count": reconstructed,
        "governed_identity_row_count": governed,
        "unresolved_identity_row_count": int(total) - governed,
    }


def _load_signed_b5(
    output: Path,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    paths = {name: _unique_file(output, name) for name in SIGNED_B5_FILE_SHA256}
    for name, path in paths.items():
        actual = sha256(path.read_bytes()).hexdigest()
        if actual != SIGNED_B5_FILE_SHA256[name]:
            raise ValueError(f"signed B5 checksum mismatch: {name}")
    blockers = _records(paths["dsi010b5_remaining_blockers.json"])
    summary = _object(paths["dsi010b5_closure_summary.json"])
    if summary.get("certificate_sha256") != (
        "67dc67b2a50cebe80eda5bc3b1289a0b733e21e33a16444729362a92eb02f64a"
    ):
        raise ValueError("signed B5 certificate identity changed")
    return tuple(blockers), summary


def _action_inventory(source: Any) -> OfficialIdentitySourceRecord:
    item = source.inventory
    return OfficialIdentitySourceRecord(
        source_id=str(item.source_id),
        source_url=str(item.source_url),
        source_path=str(item.immutable_path) if item.immutable_path else None,
        sha256=str(item.sha256) if item.sha256 else None,
        parser=str(item.parser),
        effective_date=item.covered_end,
        state=_source_state(str(item.status.value)),
        official_host=bool(item.official_host),
        byte_size=int(item.byte_size),
        record_count=int(item.events_parsed),
        acquired_at=str(item.retrieval_timestamp) if item.retrieval_timestamp else None,
        redirect_chain=tuple(item.redirects),
        limitation=str(item.known_limitations) if item.known_limitations else None,
    )


def _source_state(value: str) -> Any:
    from alpha.historical_truth.pre2016_identity_sources import IdentitySourceState

    if value in {"ACQUIRED", "REUSED"}:
        return IdentitySourceState(value)
    if value == "REJECTED":
        return IdentitySourceState.REJECTED
    return IdentitySourceState.FAILED


def _interval_payload(interval: ReconstructedIdentityInterval) -> dict[str, Any]:
    return cast(dict[str, Any], _jsonable(asdict(interval)))


def _unique_file(root: Path, name: str) -> Path:
    matches = sorted(root.resolve().glob(f"**/{name}"))
    if len(matches) != 1:
        raise ValueError(f"expected one {name}, found {len(matches)}")
    return matches[0]


def _required_date(value: object) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _digest(value: object) -> str:
    payload = json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _jsonable(value: object) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "value"):
        return getattr(value, "value")
    return value


def _write_json(path: Path, value: object) -> Path:
    path.write_text(
        json.dumps(_jsonable(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _write_pair(
    output: Path,
    stem: str,
    rows: Sequence[Any],
) -> tuple[Path, Path]:
    payload = tuple(
        _jsonable(asdict(row)) if hasattr(row, "__dataclass_fields__") else row
        for row in rows
    )
    json_path = _write_json(output / f"{stem}.json", payload)
    csv_path = output / f"{stem}.csv"
    columns = sorted(
        {str(key) for row in payload if isinstance(row, Mapping) for key in row}
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        if columns:
            writer.writeheader()
            for row in payload:
                writer.writerow(
                    {column: _csv_value(row.get(column)) for column in columns}
                )
    return json_path, csv_path


def _csv_value(value: object) -> object:
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return value


def _markdown(report: Pre2016IdentityReconstructionReport) -> str:
    summary = report.summary
    census = summary["full_canonical_row_reconciliation"]
    return "\n".join(
        (
            "# DSI-010B6 Pre-2016 Identity Reconstruction",
            "",
            "## Decision",
            "",
            f"**{summary['readiness']}**",
            "",
            "The signed B5 queue was evaluated against immutable, dated official "
            "identity checkpoints. No identity was inferred from price behaviour "
            "or symbol similarity.",
            "",
            "## Segment Closure",
            "",
            f"- Starting segments: {summary['starting_segment_count']}",
            f"- Resolved segments: {summary['resolved_segment_count']}",
            f"- Remaining segments: {summary['remaining_segment_count']}",
            "- Newly certified action-exposed rows: "
            f"{summary['newly_certified_affected_row_count']:,}",
            "",
            "## Full Row Reconciliation",
            "",
            f"- Canonical rows: {census['total_canonical_row_count']:,}",
            f"- Exact-ISIN rows: {census['exact_isin_certified_row_count']:,}",
            f"- Signed bridge rows: {census['signed_b5_bridge_certified_row_count']:,}",
            "- New bounded-interval rows: "
            f"{census['new_b6_interval_certified_row_count']:,}",
            f"- Unresolved identity rows: {census['unresolved_identity_row_count']:,}",
            "",
            "## Evidence Ceiling",
            "",
            "NSE's official Capital Market historical-data specification documents "
            "monthly Masters snapshots containing ISIN, symbol, series, name and "
            "deletion state. The 2005-2015 files require an NSE historical-data "
            "subscription and were not available to this run. Readiness therefore "
            "remains fail-closed wherever existing official checkpoints do not "
            "bracket the complete identity interval.",
            "",
            "## Governance",
            "",
            "- Raw candles unchanged: true",
            "- Security periods excluded: false",
            "- Full benchmark replays: 0",
            "- Production influence: false",
            "",
            f"`ADJUSTED_REPLAY_READY={str(summary['adjusted_replay_ready']).lower()}`",
            "",
        )
    )


__all__ = [
    "DSI010B6_CONTRACT_VERSION",
    "IdentityCheckpointType",
    "IdentityIntervalState",
    "OfficialIdentityCheckpoint",
    "Pre2016IdentityReconstructionEngine",
    "Pre2016IdentityReconstructionExporter",
    "Pre2016IdentityReconstructionReport",
    "ReconstructedIdentityBridge",
    "ReconstructedIdentityInterval",
    "SegmentResolution",
]
