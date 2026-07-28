"""DSI-010B4 final pre-2016 adjusted-history closure certification."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from alpha.historical_truth.residual_corporate_action_closure import (
    ResidualCorporateActionClosureEngine,
)

DSI010B4_CONTRACT_VERSION = "DSI-010B4-v1.0.0"
PRODUCTION_INFLUENCE = False

_UNRESOLVED = {
    "FACTOR_INSUFFICIENT_EVIDENCE",
    "FACTOR_REQUIRES_REFERENCE_PRICE",
    "FACTOR_CONFLICTING_OFFICIAL_EVIDENCE",
    "IMPLEMENTATION_DEFECT",
}


@dataclass(frozen=True, slots=True)
class FinalPre2016ClosureReport:
    """Immutable B4 comparison and fail-closed replay-readiness certificate."""

    summary: dict[str, Any]
    before_after: tuple[dict[str, Any], ...]
    resolved_cases: tuple[dict[str, Any], ...]
    remaining_blockers: tuple[dict[str, Any], ...]
    named_cases: tuple[dict[str, Any], ...]
    rights_factor_states: dict[str, int]
    certificate_sha256: str


class FinalPre2016AdjustedHistoryClosureEngine:
    """Reconcile B3 against B4 without changing factors or candles."""

    def run(
        self,
        *,
        baseline_b1c_output: Path,
        final_b1c_output: Path,
        baseline_htr010b_output: Path,
        final_htr010b_output: Path,
        dsi010b1_output: Path | None = None,
    ) -> FinalPre2016ClosureReport:
        base_report = ResidualCorporateActionClosureEngine().run(
            baseline_b1c_output=baseline_b1c_output,
            final_b1c_output=final_b1c_output,
            baseline_htr010b_output=baseline_htr010b_output,
            final_htr010b_output=final_htr010b_output,
            dsi010b1_output=dsi010b1_output,
        )
        baseline = _indexed(
            baseline_b1c_output / "htr010b1_factor_validation_results.json",
            "event_id",
        )
        final = _indexed(
            final_b1c_output / "htr010b1_factor_validation_results.json",
            "event_id",
        )
        factors = _indexed(
            final_htr010b_output / "htr010b_adjustment_factors.json",
            "canonical_event_id",
        )
        events = _indexed(
            final_htr010b_output / "htr010b_canonical_events.json",
            "canonical_event_id",
        )
        before_after = tuple(
            _comparison(event_id, baseline[event_id], final[event_id])
            for event_id in sorted(baseline)
        )
        resolved = tuple(row for row in before_after if row["resolved"])
        channel_counts = Counter(str(row["resolution_channel"]) for row in resolved)
        named = tuple(
            _named_case(symbol, baseline, final)
            for symbol in ("MURUDCERA", "TATAPOWER", "HINDMOTOR")
        )
        rights_factor_states = Counter(
            str(factors[event_id].get("factor_state"))
            for event_id, event in events.items()
            if event.get("action_type") == "RIGHTS" and event_id in factors
        )
        before_basis = _basis_metrics(baseline_htr010b_output)
        after_basis = _basis_metrics(final_htr010b_output)
        raw_unchanged = (
            before_basis["raw_candle_fingerprint"]
            == after_basis["raw_candle_fingerprint"]
        )
        final_counts = Counter(
            str(row.get("validation_outcome")) for row in final.values()
        )
        adjusted_ready = (
            not base_report.remaining_blockers
            and int(base_report.summary["unresolved_admission_intervals"]) == 0
            and int(after_basis["mixed_price_basis_intervals"]) == 0
            and raw_unchanged
        )
        summary: dict[str, Any] = {
            "contract_version": DSI010B4_CONTRACT_VERSION,
            "production_influence": PRODUCTION_INFLUENCE,
            "full_benchmark_replays": 0,
            "starting_case_count": int(base_report.summary["initial_residual_count"]),
            "resolved_case_count": len(resolved),
            "remaining_case_count": len(base_report.remaining_blockers),
            "resolution_channel_counts": dict(sorted(channel_counts.items())),
            "validation_outcome_counts": dict(sorted(final_counts.items())),
            "rights_factor_state_counts": dict(sorted(rights_factor_states.items())),
            "unresolved_admission_intervals": int(
                base_report.summary["unresolved_admission_intervals"]
            ),
            "mixed_price_basis_intervals_before": before_basis[
                "mixed_price_basis_intervals"
            ],
            "mixed_price_basis_intervals_after": after_basis[
                "mixed_price_basis_intervals"
            ],
            "raw_rows_before": before_basis["raw_rows"],
            "raw_rows_after": after_basis["raw_rows"],
            "adjusted_rows_before": before_basis["adjusted_rows"],
            "adjusted_rows_after": after_basis["adjusted_rows"],
            "raw_candle_fingerprint_before": before_basis["raw_candle_fingerprint"],
            "raw_candle_fingerprint_after": after_basis["raw_candle_fingerprint"],
            "raw_candles_unchanged": raw_unchanged,
            "security_periods_excluded": False,
            "policy_or_production_behaviour_changed": False,
            "adjusted_replay_ready": adjusted_ready,
            "readiness": (
                "ADJUSTED_REPLAY_CERTIFIED"
                if adjusted_ready
                else "RESIDUAL_OFFICIAL_EVIDENCE_REQUIRED"
            ),
        }
        certificate = {
            "summary": summary,
            "before_after_sha256": _digest(before_after),
            "resolved_cases_sha256": _digest(resolved),
            "remaining_blockers_sha256": _digest(base_report.remaining_blockers),
            "named_cases_sha256": _digest(named),
        }
        certificate_sha256 = _digest(certificate)
        summary["certificate_sha256"] = certificate_sha256
        return FinalPre2016ClosureReport(
            summary=summary,
            before_after=before_after,
            resolved_cases=resolved,
            remaining_blockers=base_report.remaining_blockers,
            named_cases=named,
            rights_factor_states=dict(sorted(rights_factor_states.items())),
            certificate_sha256=certificate_sha256,
        )


class FinalPre2016AdjustedHistoryClosureExporter:
    """Write deterministic B4 evidence and readiness artifacts."""

    def export(
        self,
        report: FinalPre2016ClosureReport,
        output: Path,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        files = [
            _write_json(output / "dsi010b4_closure_summary.json", report.summary),
        ]
        for stem, rows in (
            ("dsi010b4_before_after_residual_ledger", report.before_after),
            ("dsi010b4_resolved_cases", report.resolved_cases),
            ("dsi010b4_remaining_blockers", report.remaining_blockers),
            ("dsi010b4_named_case_outcomes", report.named_cases),
        ):
            files.extend(_write_pair(output, stem, rows))
        files.extend(
            (
                _write_json(
                    output / "dsi010b4_adjusted_replay_readiness_certificate.json",
                    {
                        **report.summary,
                        "certificate_sha256": report.certificate_sha256,
                    },
                ),
                _write_markdown(output / "dsi010b4_executive_report.md", report),
            )
        )
        return tuple(files)


def _comparison(
    event_id: str,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    old = str(before.get("validation_outcome"))
    new = str(after.get("validation_outcome"))
    resolved = old in _UNRESOLVED and new not in _UNRESOLVED
    return {
        "event_id": event_id,
        "symbol": after.get("symbol") or before.get("symbol"),
        "effective_date": after.get("effective_date") or before.get("effective_date"),
        "action_type": after.get("action_type") or before.get("action_type"),
        "old_validation_outcome": old,
        "new_validation_outcome": new,
        "old_continuity_decision": _context_decision(before),
        "new_continuity_decision": _context_decision(after),
        "resolved": resolved,
        "resolution_channel": (
            _resolution_channel(before, after) if resolved else "NOT_RESOLVED"
        ),
        "production_influence": False,
    }


def _resolution_channel(before: dict[str, Any], after: dict[str, Any]) -> str:
    context = after.get("governed_continuity_context")
    context_row = context if isinstance(context, dict) else {}
    selected = list(context_row.get("selected_prior_bars") or [])
    action = context_row.get("action_bar")
    if isinstance(action, dict):
        selected.append(action)
    if any(
        str(row.get("identity_state")) == "CERTIFIED_OFFICIAL_ISIN_TRANSITION_CANDLE"
        for row in selected
        if isinstance(row, dict)
    ):
        return "IDENTITY_TRANSITION_WIRING"
    if _context_decision(before) == "INSUFFICIENT_ATR_HISTORY":
        return "PRE_EVENT_INTERVAL_REPAIR"
    if _context_decision(before) == "ACTION_SESSION_MISSING":
        return "SECURITY_SPECIFIC_ACTION_SESSION"
    if before.get("validation_outcome") == "FACTOR_REQUIRES_REFERENCE_PRICE":
        return "RIGHTS_TERMS_OR_REFERENCE_IDENTITY_RECOVERY"
    if before.get("validation_outcome") == "FACTOR_CONFLICTING_OFFICIAL_EVIDENCE":
        return "SOURCE_CONFLICT_ADJUDICATION"
    return "TRANSFORMATION_CONTRACT_REPAIR"


def _context_decision(row: dict[str, Any]) -> str | None:
    context = row.get("governed_continuity_context")
    return str(context.get("decision")) if isinstance(context, dict) else None


def _named_case(
    symbol: str,
    baseline: dict[str, dict[str, Any]],
    final: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    event_ids = sorted(
        event_id for event_id, row in final.items() if str(row.get("symbol")) == symbol
    )
    outcomes = [
        {
            "event_id": event_id,
            "effective_date": final[event_id].get("effective_date"),
            "old_validation_outcome": baseline[event_id].get("validation_outcome"),
            "final_validation_outcome": final[event_id].get("validation_outcome"),
        }
        for event_id in event_ids
    ]
    return {
        "symbol": symbol,
        "event_count": len(outcomes),
        "outcomes": outcomes,
        "production_influence": False,
    }


def _basis_metrics(output: Path) -> dict[str, Any]:
    rows = _records(output / "htr010b_adjusted_candle_summary.json")
    readiness = json.loads(
        (output / "htr010b_adjusted_replay_readiness.json").read_text(encoding="utf-8")
    )
    return {
        "raw_rows": sum(int(row.get("raw_rows") or 0) for row in rows),
        "adjusted_rows": sum(int(row.get("adjusted_rows") or 0) for row in rows),
        "mixed_price_basis_intervals": sum(
            str(row.get("price_basis_state")) == "MIXED_PRICE_BASIS" for row in rows
        ),
        "raw_candle_fingerprint": readiness.get("raw_candle_fingerprint"),
    }


def _indexed(path: Path, key: str) -> dict[str, dict[str, Any]]:
    rows = _records(path)
    result = {str(row.get(key) or ""): row for row in rows}
    if "" in result or len(result) != len(rows):
        raise ValueError(f"{path} must contain unique non-empty {key} values")
    return result


def _records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path} must contain a JSON record list")
    return rows


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode()
    ).hexdigest()


def _write_json(path: Path, value: Any) -> Path:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    return path


def _write_pair(
    output: Path,
    stem: str,
    rows: tuple[dict[str, Any], ...],
) -> tuple[Path, Path]:
    json_path = _write_json(output / f"{stem}.json", rows)
    csv_path = output / f"{stem}.csv"
    fields = sorted({key for row in rows for key in row})
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: json.dumps(row.get(key), sort_keys=True)
                    if isinstance(row.get(key), (dict, list, tuple))
                    else row.get(key)
                    for key in fields
                }
            )
    return json_path, csv_path


def _write_markdown(path: Path, report: FinalPre2016ClosureReport) -> Path:
    summary = report.summary
    lines = [
        "# DSI-010B4 Final Pre-2016 Closure",
        "",
        f"- Starting residual cases: {summary['starting_case_count']}",
        f"- Resolved cases: {summary['resolved_case_count']}",
        f"- Remaining cases: {summary['remaining_case_count']}",
        f"- Resolution channels: {summary['resolution_channel_counts']}",
        f"- Validation outcomes: {summary['validation_outcome_counts']}",
        (
            "- Mixed price-basis intervals: "
            f"{summary['mixed_price_basis_intervals_before']} -> "
            f"{summary['mixed_price_basis_intervals_after']}"
        ),
        f"- Raw candles unchanged: {summary['raw_candles_unchanged']}",
        f"- Readiness: {summary['readiness']}",
        "",
        "No benchmark replay ran. No production or policy behavior changed.",
        "",
        "PRODUCTION_INFLUENCE=false",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


__all__ = [
    "DSI010B4_CONTRACT_VERSION",
    "PRODUCTION_INFLUENCE",
    "FinalPre2016AdjustedHistoryClosureEngine",
    "FinalPre2016AdjustedHistoryClosureExporter",
    "FinalPre2016ClosureReport",
]
