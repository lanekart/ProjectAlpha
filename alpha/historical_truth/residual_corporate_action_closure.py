"""Deterministic DSI-010B3 residual corporate-action closure certification."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from pathlib import Path
from typing import Any

DSI010B3_CONTRACT_VERSION = "DSI-010B3-v1.0.0"
PRODUCTION_INFLUENCE = False

_UNRESOLVED_OUTCOMES = {
    "FACTOR_INSUFFICIENT_EVIDENCE",
    "FACTOR_REQUIRES_REFERENCE_PRICE",
    "FACTOR_CONFLICTING_OFFICIAL_EVIDENCE",
    "IMPLEMENTATION_DEFECT",
}


class ClosureReadiness(StrEnum):
    """Final adjusted-replay disposition."""

    ADJUSTED_REPLAY_CERTIFIED = "ADJUSTED_REPLAY_CERTIFIED"
    RESIDUAL_OFFICIAL_EVIDENCE_REQUIRED = "RESIDUAL_OFFICIAL_EVIDENCE_REQUIRED"
    SOURCE_POPULATION_MISMATCH = "SOURCE_POPULATION_MISMATCH"


@dataclass(frozen=True, slots=True)
class ResidualClosureReport:
    """Immutable comparison between the signed B2 baseline and repaired state."""

    summary: dict[str, Any]
    before_after: tuple[dict[str, Any], ...]
    remaining_blockers: tuple[dict[str, Any], ...]
    recovered_sources: tuple[dict[str, Any], ...]
    certificate_sha256: str


class ResidualCorporateActionClosureEngine:
    """Attribute actual closure without changing factors, candles, or policy."""

    def run(
        self,
        *,
        baseline_b1c_output: Path,
        final_b1c_output: Path,
        baseline_htr010b_output: Path,
        final_htr010b_output: Path,
        official_source_root: Path | None = None,
    ) -> ResidualClosureReport:
        baseline = _indexed_records(
            baseline_b1c_output / "htr010b1_factor_validation_results.json",
            "event_id",
        )
        final = _indexed_records(
            final_b1c_output / "htr010b1_factor_validation_results.json",
            "event_id",
        )
        baseline_factors = _indexed_records(
            baseline_htr010b_output / "htr010b_adjustment_factors.json",
            "canonical_event_id",
        )
        final_factors = _indexed_records(
            final_htr010b_output / "htr010b_adjustment_factors.json",
            "canonical_event_id",
        )
        final_events = _indexed_records(
            final_htr010b_output / "htr010b_canonical_events.json",
            "canonical_event_id",
        )
        same_population = set(baseline) == set(final)
        event_ids = sorted(set(baseline) | set(final))
        comparisons = tuple(
            _comparison(
                event_id,
                baseline.get(event_id),
                final.get(event_id),
                baseline_factors.get(event_id),
                final_factors.get(event_id),
            )
            for event_id in event_ids
        )
        remaining = tuple(
            _remaining_case(
                final[event_id],
                final_factors.get(event_id),
                final_events.get(event_id),
            )
            for event_id in sorted(final)
            if str(final[event_id].get("validation_outcome")) in _UNRESOLVED_OUTCOMES
        )
        sources = _official_source_manifest(official_source_root)
        before_counts = Counter(
            str(row.get("validation_outcome")) for row in baseline.values()
        )
        after_counts = Counter(
            str(row.get("validation_outcome")) for row in final.values()
        )
        baseline_factor_counts = Counter(
            str(row.get("factor_state")) for row in baseline_factors.values()
        )
        final_factor_counts = Counter(
            str(row.get("factor_state")) for row in final_factors.values()
        )
        resolution_counts = Counter(
            str(row["resolution_channel"]) for row in comparisons if row["resolved"]
        )
        regressed_count = sum(
            str(row["old_validation_outcome"]) not in _UNRESOLVED_OUTCOMES
            and str(row["new_validation_outcome"]) in _UNRESOLVED_OUTCOMES
            for row in comparisons
        )
        gross_resolved_count = sum(bool(row["resolved"]) for row in comparisons)
        unresolved_intervals = _unresolved_intervals(final_b1c_output)
        mixed_basis = _mixed_basis_count(final_htr010b_output)
        readiness = (
            ClosureReadiness.SOURCE_POPULATION_MISMATCH
            if not same_population
            else (
                ClosureReadiness.ADJUSTED_REPLAY_CERTIFIED
                if not remaining and unresolved_intervals == 0 and mixed_basis == 0
                else ClosureReadiness.RESIDUAL_OFFICIAL_EVIDENCE_REQUIRED
            )
        )
        summary: dict[str, Any] = {
            "contract_version": DSI010B3_CONTRACT_VERSION,
            "production_influence": PRODUCTION_INFLUENCE,
            "full_benchmark_replays": 0,
            "source_population_identical": same_population,
            "population_count": len(event_ids),
            "initial_residual_count": sum(
                before_counts.get(state, 0) for state in _UNRESOLVED_OUTCOMES
            ),
            "final_residual_count": len(remaining),
            "gross_resolved_count": gross_resolved_count,
            "regressed_to_fail_closed_count": regressed_count,
            "net_resolved_count": gross_resolved_count - regressed_count,
            "resolution_channel_counts": dict(sorted(resolution_counts.items())),
            "old_validation_outcome_counts": dict(sorted(before_counts.items())),
            "new_validation_outcome_counts": dict(sorted(after_counts.items())),
            "old_factor_state_counts": dict(sorted(baseline_factor_counts.items())),
            "new_factor_state_counts": dict(sorted(final_factor_counts.items())),
            "remaining_reason_counts": dict(
                sorted(
                    Counter(str(row["missing_component"]) for row in remaining).items()
                )
            ),
            "unresolved_admission_intervals": unresolved_intervals,
            "mixed_price_basis_intervals": mixed_basis,
            "new_official_source_count": len(sources),
            "readiness": readiness.value,
            "adjusted_replay_ready": (
                readiness is ClosureReadiness.ADJUSTED_REPLAY_CERTIFIED
            ),
            "raw_candles_mutated": False,
            "security_periods_excluded": False,
            "policy_or_production_behaviour_changed": False,
        }
        certificate = {
            "summary": summary,
            "before_after_sha256": _digest(comparisons),
            "remaining_blockers_sha256": _digest(remaining),
            "recovered_sources_sha256": _digest(sources),
        }
        certificate_sha256 = _digest(certificate)
        summary["certificate_sha256"] = certificate_sha256
        return ResidualClosureReport(
            summary=summary,
            before_after=comparisons,
            remaining_blockers=remaining,
            recovered_sources=sources,
            certificate_sha256=certificate_sha256,
        )


class ResidualCorporateActionClosureExporter:
    """Write stable machine-readable and executive closure artifacts."""

    def export(
        self,
        report: ResidualClosureReport,
        output: Path,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        files = (
            _write_json(output / "dsi010b3_closure_summary.json", report.summary),
            _write_json(
                output / "dsi010b3_before_after_residual_ledger.json",
                report.before_after,
            ),
            _write_csv(
                output / "dsi010b3_before_after_residual_ledger.csv",
                report.before_after,
            ),
            _write_json(
                output / "dsi010b3_remaining_blockers.json",
                report.remaining_blockers,
            ),
            _write_csv(
                output / "dsi010b3_remaining_blockers.csv",
                report.remaining_blockers,
            ),
            _write_json(
                output / "dsi010b3_recovered_official_sources.json",
                report.recovered_sources,
            ),
            _write_json(
                output / "dsi010b3_replay_readiness_certificate.json",
                {
                    **report.summary,
                    "certificate_sha256": report.certificate_sha256,
                },
            ),
            _write_markdown(output / "dsi010b3_executive_report.md", report),
        )
        return files


def _comparison(
    event_id: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    before_factor: dict[str, Any] | None,
    after_factor: dict[str, Any] | None,
) -> dict[str, Any]:
    old = str((before or {}).get("validation_outcome") or "MISSING")
    new = str((after or {}).get("validation_outcome") or "MISSING")
    initially_unresolved = old in _UNRESOLVED_OUTCOMES
    resolved = initially_unresolved and new not in _UNRESOLVED_OUTCOMES
    channel = _resolution_channel(old, new, before_factor, after_factor)
    source = after or before or {}
    return {
        "event_id": event_id,
        "symbol": source.get("symbol"),
        "effective_date": source.get("effective_date"),
        "action_type": source.get("action_type"),
        "old_factor_state": (before_factor or {}).get("factor_state"),
        "new_factor_state": (after_factor or {}).get("factor_state"),
        "old_validation_outcome": old,
        "new_validation_outcome": new,
        "initially_unresolved": initially_unresolved,
        "resolved": resolved,
        "resolution_channel": channel,
        "production_influence": False,
    }


def _resolution_channel(
    old: str,
    new: str,
    before_factor: dict[str, Any] | None,
    after_factor: dict[str, Any] | None,
) -> str:
    if old not in _UNRESOLVED_OUTCOMES or new in _UNRESOLVED_OUTCOMES:
        return "NOT_RESOLVED_BY_MILESTONE"
    if old == "IMPLEMENTATION_DEFECT":
        return "TRANSFORMATION_CONTRACT_REPAIR"
    if old == "FACTOR_CONFLICTING_OFFICIAL_EVIDENCE":
        return "SOURCE_CONFLICT_ADJUDICATION"
    before_state = str((before_factor or {}).get("factor_state") or "")
    after_state = str((after_factor or {}).get("factor_state") or "")
    if before_state != after_state:
        provenance = str(
            (after_factor or {}).get("reference_price_provenance_state") or ""
        )
        if "BRIDGE" in provenance or "INTERVAL" in provenance:
            return "IDENTITY_INTERVAL_OR_BRIDGE_RECOVERY"
        return "PARSER_OR_REFERENCE_PRICE_RECOVERY"
    return "BRIDGE_AWARE_CONTINUITY_RECOVERY"


def _remaining_case(
    row: dict[str, Any],
    factor: dict[str, Any] | None,
    event: dict[str, Any] | None,
) -> dict[str, Any]:
    context = row.get("governed_continuity_context")
    context_row = context if isinstance(context, dict) else {}
    outcome = str(row.get("validation_outcome") or "")
    if outcome == "FACTOR_REQUIRES_REFERENCE_PRICE":
        missing = _reference_price_blocker(factor, event)
    elif outcome == "FACTOR_CONFLICTING_OFFICIAL_EVIDENCE":
        missing = "AUTHORITATIVE_SUPERSEDING_OFFICIAL_TERMS"
    elif outcome == "IMPLEMENTATION_DEFECT":
        missing = "TRANSFORMATION_CONTRACT_REPAIR"
    elif context_row.get("decision") == "ACTION_SESSION_MISSING":
        missing = "FIRST_GOVERNED_ACTION_SESSION_CANDLE"
    elif context_row.get("decision") == "INSUFFICIENT_ATR_HISTORY":
        missing = "FOURTEEN_GOVERNED_PRE_EVENT_BARS"
    else:
        missing = "COMPLETE_GOVERNED_CONTINUITY_CONTEXT"
    rejected = context_row.get("rejected_bars")
    rejected_rows = rejected if isinstance(rejected, list) else []
    return {
        "event_id": row.get("event_id"),
        "factor_id": row.get("factor_id"),
        "symbol": row.get("symbol"),
        "series": row.get("series"),
        "isin": row.get("isin"),
        "effective_date": row.get("effective_date"),
        "action_type": row.get("action_type"),
        "factor_state": (factor or {}).get("factor_state"),
        "raw_action_text": (event or {}).get("raw_action_text"),
        "ratio_numerator": (event or {}).get("ratio_numerator"),
        "ratio_denominator": (event or {}).get("ratio_denominator"),
        "rights_price": (event or {}).get("rights_price"),
        "validation_outcome": outcome,
        "continuity_decision": context_row.get("decision"),
        "missing_component": missing,
        "rejected_candle_reasons": sorted(
            {str(item.get("reason")) for item in rejected_rows if item.get("reason")}
        ),
        "required_authoritative_evidence": _required_evidence(missing),
        "production_influence": False,
    }


def _reference_price_blocker(
    factor: dict[str, Any] | None,
    event: dict[str, Any] | None,
) -> str:
    factor_row = factor or {}
    event_row = event or {}
    if str(factor_row.get("reference_price_original_provenance_state")) == (
        "PRIOR_ISIN_MISMATCH"
    ):
        return "OFFICIAL_EFFECTIVE_DATED_ISIN_TRANSITION"
    if not _complete_equity_rights_terms(event_row):
        return "COMPLETE_OFFICIAL_EQUITY_RIGHTS_TERMS"
    return "GOVERNED_REFERENCE_PRICE_IDENTITY"


def _complete_equity_rights_terms(event: dict[str, Any]) -> bool:
    numerator = event.get("ratio_numerator")
    denominator = event.get("ratio_denominator")
    rights_price = event.get("rights_price")
    return (
        isinstance(numerator, (int, float))
        and numerator > 0
        and isinstance(denominator, (int, float))
        and denominator > 0
        and isinstance(rights_price, (int, float))
        and rights_price >= 0
    )


def _required_evidence(missing: str) -> str:
    return {
        "OFFICIAL_EFFECTIVE_DATED_ISIN_TRANSITION": (
            "official effective-dated predecessor-successor or ISIN-transition "
            "evidence linking the reference session to the action identity"
        ),
        "COMPLETE_OFFICIAL_EQUITY_RIGHTS_TERMS": (
            "official rights ratio, equity issue price, and applicable identity "
            "terms from an authoritative action document"
        ),
        "GOVERNED_REFERENCE_PRICE_IDENTITY": (
            "effective-dated official identity evidence certifying the governed "
            "prior-close reference candle"
        ),
        "AUTHORITATIVE_SUPERSEDING_OFFICIAL_TERMS": (
            "official amendment, superseding circular, or scheme document"
        ),
        "TRANSFORMATION_CONTRACT_REPAIR": "verified engine-level transformation repair",
        "FIRST_GOVERNED_ACTION_SESSION_CANDLE": (
            "canonical first action-session OHLCV row with governed "
            "identity and checksum"
        ),
        "FOURTEEN_GOVERNED_PRE_EVENT_BARS": (
            "fourteen pre-event canonical OHLCV rows with governed "
            "identity and checksums"
        ),
        "COMPLETE_GOVERNED_CONTINUITY_CONTEXT": (
            "complete bar-level identity and continuity evidence"
        ),
    }[missing]


def _official_source_manifest(root: Path | None) -> tuple[dict[str, Any], ...]:
    if root is None or not root.exists():
        return ()
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        raw = path.read_bytes()
        rows.append(
            {
                "path": str(path),
                "byte_size": len(raw),
                "sha256": sha256(raw).hexdigest(),
                "production_influence": False,
            }
        )
    return tuple(rows)


def _unresolved_intervals(output: Path) -> int:
    rows = _records(output / "htr010b1_replay_admission_intervals.json")
    return sum(str(row.get("admission_state")) == "UNRESOLVED" for row in rows)


def _mixed_basis_count(output: Path) -> int:
    rows = _records(output / "htr010b_adjusted_candle_summary.json")
    return sum(str(row.get("price_basis_state")) == "MIXED_PRICE_BASIS" for row in rows)


def _indexed_records(path: Path, key: str) -> dict[str, dict[str, Any]]:
    rows = _records(path)
    indexed = {str(row.get(key) or ""): row for row in rows}
    if "" in indexed or len(indexed) != len(rows):
        raise ValueError(f"{path} does not contain unique non-empty {key} values")
    return indexed


def _records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records", []) if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"expected record list: {path}")
    return rows


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _write_json(path: Path, value: Any) -> Path:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _write_csv(path: Path, rows: tuple[dict[str, Any], ...]) -> Path:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(value, sort_keys=True)
                        if isinstance(value, (dict, list, tuple))
                        else value
                    )
                    for key, value in row.items()
                }
            )
    return path


def _write_markdown(path: Path, report: ResidualClosureReport) -> Path:
    summary = report.summary
    lines = [
        "# DSI-010B3 Residual Corporate-Action Closure",
        "",
        f"- Initial residual cases: {summary['initial_residual_count']}",
        f"- Final residual cases: {summary['final_residual_count']}",
        f"- Gross cases resolved: {summary['gross_resolved_count']}",
        (f"- Regressed to fail-closed: {summary['regressed_to_fail_closed_count']}"),
        f"- Net cases resolved: {summary['net_resolved_count']}",
        f"- Resolution channels: {summary['resolution_channel_counts']}",
        f"- Remaining evidence: {summary['remaining_reason_counts']}",
        (
            "- Unresolved admission intervals: "
            f"{summary['unresolved_admission_intervals']}"
        ),
        f"- Mixed price-basis intervals: {summary['mixed_price_basis_intervals']}",
        f"- Readiness: {summary['readiness']}",
        f"- Certificate SHA-256: {report.certificate_sha256}",
        "",
        "No factor was inferred from price behaviour. No raw candle, strategy, gate, "
        "portfolio, execution, or production policy was changed.",
        "",
        "FULL_BENCHMARK_REPLAYS=0",
        f"ADJUSTED_REPLAY_READY={str(summary['adjusted_replay_ready']).lower()}",
        "PRODUCTION_INFLUENCE=false",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


__all__ = [
    "ClosureReadiness",
    "DSI010B3_CONTRACT_VERSION",
    "PRODUCTION_INFLUENCE",
    "ResidualClosureReport",
    "ResidualCorporateActionClosureEngine",
    "ResidualCorporateActionClosureExporter",
]
