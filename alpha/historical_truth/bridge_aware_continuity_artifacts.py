"""Deterministic DSI-010B2 bridge-aware continuity certification artifacts."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256
from pathlib import Path
from typing import Any

import duckdb

from alpha.historical_truth.bridge_aware_continuity_context import (
    BRIDGE_AWARE_CONTINUITY_CONTRACT_VERSION,
    PRODUCTION_INFLUENCE,
    BridgeAwareContinuityContextProvider,
)

BRIDGE_AWARE_CONTINUITY_CERTIFICATE_VERSION = (
    "DSI-010B2-BRIDGE-AWARE-CONTINUITY-CERTIFICATE-v1.0.0"
)


@dataclass(frozen=True, slots=True)
class BridgeAwareContinuityCertificationReport:
    contract_version: str
    production_influence: bool
    cases: tuple[dict[str, Any], ...]
    bar_ledger: tuple[dict[str, Any], ...]
    rejections: tuple[dict[str, Any], ...]
    summary: dict[str, Any]
    source_manifest: dict[str, Any]
    certificate: dict[str, Any]
    report_markdown: str
    certificate_sha256: str


class BridgeAwareContinuityCertificationEngine:
    """Recompute and reconcile the signed 18-event continuity population."""

    def run(
        self,
        *,
        database_path: Path,
        htr009a2_output: Path,
        htr010a3_output: Path,
        htr010b_output: Path,
        htr010b1c_output: Path,
        htr010b1e2_output: Path,
        dsi010b1_output: Path,
    ) -> BridgeAwareContinuityCertificationReport:
        provider = BridgeAwareContinuityContextProvider.from_signed_outputs(
            htr009a2_output=htr009a2_output,
            htr010a3_output=htr010a3_output,
            dsi010b1_output=dsi010b1_output,
        )
        database_sha256_before = _file_sha256(database_path)
        paths = _input_files(
            htr010b_output=htr010b_output,
            htr010b1c_output=htr010b1c_output,
            htr010b1e2_output=htr010b1e2_output,
            dsi010b1_output=dsi010b1_output,
        )
        events = _records(paths["htr010b_canonical_events.json"])
        factors = _records(paths["htr010b_adjustment_factors.json"])
        upstream = _records(paths["b1c_factor_validation_results.json"])
        final = _records(paths["e2_factor_validation_results.json"])
        readiness = _object(paths["htr010b1_replay_readiness.json"])
        b1_summary = _object(paths["legacy_rights_reference_bridge_summary.json"])

        events_by_id = {
            str(row["canonical_event_id"]): row
            for row in events
            if row.get("canonical_event_id")
        }
        factors_by_event = {
            str(row["canonical_event_id"]): row
            for row in factors
            if row.get("canonical_event_id")
        }
        upstream_by_event = _by_event(upstream)
        final_by_event = _by_event(final)

        case_rows: list[dict[str, Any]] = []
        bar_rows: list[dict[str, Any]] = []
        rejection_rows: list[dict[str, Any]] = []
        with duckdb.connect(str(database_path), read_only=True) as connection:
            for event_id in provider.event_ids:
                event = events_by_id.get(event_id)
                factor = factors_by_event.get(event_id)
                if event is None or factor is None:
                    raise ValueError(f"signed event missing from HTR-010B: {event_id}")
                applicable = tuple(
                    str(item).upper()
                    for item in event.get("series_applicability") or ()
                )
                if len(applicable) != 1:
                    raise ValueError(f"signed event series is ambiguous: {event_id}")
                effective = _as_date(event.get("effective_date"))
                if effective is None:
                    raise ValueError(f"signed event date is malformed: {event_id}")
                context = provider.build(
                    connection,
                    event=event,
                    factor=factor,
                    series=applicable[0],
                    effective_date=effective,
                )
                upstream_row = _one(upstream_by_event, event_id, "B1C")
                final_row = _one(final_by_event, event_id, "B1E2")
                if upstream_row.get("governed_continuity_context") != context.as_dict():
                    raise ValueError(
                        f"B1C governed context does not reproduce for {event_id}"
                    )
                signed_case = provider.case(event_id)
                row = _case_row(
                    signed_case=signed_case,
                    factor=factor,
                    context=context.as_dict(),
                    upstream=upstream_row,
                    final=final_row,
                )
                case_rows.append(row)
                for bar in context.prior_window.selected_prior_bars:
                    bar_rows.append(
                        _bar_row(
                            row,
                            bar.as_dict(
                                atr_included=(bar in context.prior_window.atr_bars),
                            ),
                        )
                    )
                if context.action_bar is not None:
                    bar_rows.append(
                        _bar_row(row, context.action_bar.as_dict(), action=True)
                    )
                rejection_rows.extend(
                    _rejection_row(row, item.as_dict())
                    for item in context.rejected_bars
                )
        database_sha256_after = _file_sha256(database_path)
        if database_sha256_before != database_sha256_after:
            raise ValueError("canonical DuckDB changed during read-only certification")

        cases = tuple(sorted(case_rows, key=_case_key))
        bars = tuple(sorted(bar_rows, key=_bar_key))
        rejections = tuple(sorted(rejection_rows, key=_rejection_key))
        summary = _summary(
            cases=cases,
            events=events,
            factors=factors,
            final_results=final,
            readiness=readiness,
            b1_summary=b1_summary,
        )
        source_manifest = _source_manifest(
            provider,
            paths,
            database_sha256=database_sha256_before,
        )
        markdown = _markdown(summary, cases)
        certificate = _certificate(
            cases=cases,
            bars=bars,
            rejections=rejections,
            summary=summary,
            source_manifest=source_manifest,
            report_markdown=markdown,
        )
        report = BridgeAwareContinuityCertificationReport(
            contract_version=BRIDGE_AWARE_CONTINUITY_CERTIFICATE_VERSION,
            production_influence=PRODUCTION_INFLUENCE,
            cases=cases,
            bar_ledger=bars,
            rejections=rejections,
            summary=summary,
            source_manifest=source_manifest,
            certificate=certificate,
            report_markdown=markdown,
            certificate_sha256="",
        )
        digest = _payload_sha256({**certificate, "certificate_sha256": ""})
        return replace(
            report,
            certificate={**certificate, "certificate_sha256": digest},
            certificate_sha256=digest,
        )


class BridgeAwareContinuityArtifactExporter:
    """Write the permanent deterministic DSI-010B2 evidence bundle."""

    def export(
        self,
        report: BridgeAwareContinuityCertificationReport,
        output: Path,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        return (
            _json(
                output / "bridge_aware_continuity_cases.json",
                {"records": list(report.cases)},
            ),
            _csv(output / "bridge_aware_continuity_cases.csv", report.cases),
            _json(
                output / "bridge_aware_continuity_bar_ledger.json",
                {"records": list(report.bar_ledger)},
            ),
            _json(
                output / "bridge_aware_continuity_rejections.json",
                {"records": list(report.rejections)},
            ),
            _json(
                output / "bridge_aware_continuity_summary.json",
                report.summary,
            ),
            _json(
                output / "bridge_aware_continuity_source_manifest.json",
                report.source_manifest,
            ),
            _text(
                output / "bridge_aware_continuity_report.md",
                report.report_markdown,
            ),
            _json(
                output / "bridge_aware_continuity_certificate.json",
                report.certificate,
            ),
        )


def _case_row(
    *,
    signed_case: dict[str, Any],
    factor: dict[str, Any],
    context: dict[str, Any],
    upstream: dict[str, Any],
    final: dict[str, Any],
) -> dict[str, Any]:
    metrics = context["metrics"]
    prior_rows = context["selected_prior_bars"]
    context_bars = list(prior_rows)
    if isinstance(context.get("action_bar"), dict):
        context_bars.append(context["action_bar"])
    bridged_count = sum(
        row["identity_state"] == "CERTIFIED_DATED_BRIDGE_CANDLE" for row in context_bars
    )
    old_outcomes = tuple(signed_case.get("final_validation_outcomes") or ())
    old_outcome = old_outcomes[0] if len(old_outcomes) == 1 else None
    return {
        "event_id": signed_case["event_id"],
        "factor_id": signed_case["factor_id"],
        "identity_key": signed_case["identity_key"],
        "symbol": signed_case["symbol"],
        "series": signed_case["series"],
        "event_isin": signed_case["event_isin"],
        "effective_date": signed_case["effective_date"],
        "certified_reference_date": signed_case["prior_candle_date"],
        "certified_reference_close": signed_case["prior_close"],
        "certified_reference_source_sha256": signed_case["prior_candle_source_sha256"],
        "old_isin_only_prior_bar_count": context["exact_isin_prior_bar_count"],
        "old_isin_only_action_bar_count": context["exact_isin_action_bar_count"],
        "old_isin_only_atr_context": "INSUFFICIENT",
        "potentially_relevant_missing_isin_bars": context[
            "potentially_relevant_missing_isin_bar_count"
        ],
        "governed_context_id": context["context_id"],
        "governed_context_decision": context["decision"],
        "governed_context_complete": context["complete"],
        "selected_prior_bar_count": len(prior_rows),
        "selected_atr_bar_count": sum(row["atr_included"] for row in prior_rows),
        "bridged_bar_count": bridged_count,
        "rejected_bar_count": len(context["rejected_bars"]),
        "first_candidate_action_date": context["first_candidate_action_date"],
        "selected_action_session": metrics["action_session"],
        "later_action_session_selected": (
            context["first_candidate_action_date"] != metrics["action_session"]
        ),
        "previous_close": metrics["previous_close"],
        "action_open": metrics["action_open"],
        "atr": metrics["atr_before"],
        "raw_gap_atr": metrics["raw_gap_atr"],
        "adjusted_gap_atr": metrics["adjusted_gap_atr"],
        "inverse_adjusted_gap_atr": metrics["inverse_adjusted_gap_atr"],
        "old_validation_outcome": old_outcome,
        "proposed_validation_outcome": upstream["validation_outcome"],
        "final_validation_outcome": final["validation_outcome"],
        "admitted_to_replay": bool(final.get("admitted_to_replay")),
        "factor_state": factor.get("factor_state"),
        "price_factor": factor.get("price_factor"),
        "factor_value_mutated": False,
        "canonical_candle_mutated": False,
        "production_influence": False,
    }


def _bar_row(
    case: dict[str, Any],
    bar: dict[str, Any],
    *,
    action: bool = False,
) -> dict[str, Any]:
    return {
        "event_id": case["event_id"],
        "factor_id": case["factor_id"],
        "symbol": case["symbol"],
        "effective_date": case["effective_date"],
        "context_id": case["governed_context_id"],
        "bar_role": "ACTION" if action else "PRIOR",
        **bar,
        "production_influence": False,
    }


def _rejection_row(
    case: dict[str, Any],
    rejection: dict[str, Any],
) -> dict[str, Any]:
    return {
        "event_id": case["event_id"],
        "factor_id": case["factor_id"],
        "symbol": case["symbol"],
        "effective_date": case["effective_date"],
        "context_id": case["governed_context_id"],
        **rejection,
        "production_influence": False,
    }


def _summary(
    *,
    cases: tuple[dict[str, Any], ...],
    events: tuple[dict[str, Any], ...],
    factors: tuple[dict[str, Any], ...],
    final_results: tuple[dict[str, Any], ...],
    readiness: dict[str, Any],
    b1_summary: dict[str, Any],
) -> dict[str, Any]:
    outcomes = Counter(str(row["final_validation_outcome"]) for row in cases)
    complete = sum(bool(row["governed_context_complete"]) for row in cases)
    confirmed = outcomes["FACTOR_CONFIRMED_CORRECT_MARKET_GAP"]
    defects = outcomes["IMPLEMENTATION_DEFECT"]
    insufficient = outcomes["FACTOR_INSUFFICIENT_EVIDENCE"]
    conflicts = outcomes["FACTOR_CONFLICTING_OFFICIAL_EVIDENCE"]
    if complete + (len(cases) - complete) != 18:
        raise ValueError("DSI-010B2 population reconciliation failed")
    if confirmed + defects + insufficient + conflicts != 18:
        raise ValueError("DSI-010B2 outcome reconciliation failed")

    rights_event_ids = {
        str(row.get("canonical_event_id") or "")
        for row in events
        if row.get("action_type") == "RIGHTS"
    }
    rights = [
        row
        for row in factors
        if str(row.get("canonical_event_id") or "") in rights_event_ids
    ]
    factor_states = Counter(str(row.get("factor_state") or "") for row in rights)
    governed_factor_states = {
        "FACTOR_CERTIFIED_REFERENCE_PRICE": factor_states[
            "FACTOR_CERTIFIED_REFERENCE_PRICE"
        ],
        "FACTOR_PROVISIONAL_REFERENCE_PRICE": factor_states[
            "FACTOR_PROVISIONAL_REFERENCE_PRICE"
        ],
        "FACTOR_UNKNOWN_MISSING_TERMS": factor_states["FACTOR_UNKNOWN_MISSING_TERMS"],
    }
    if governed_factor_states != {
        "FACTOR_CERTIFIED_REFERENCE_PRICE": 55,
        "FACTOR_PROVISIONAL_REFERENCE_PRICE": 22,
        "FACTOR_UNKNOWN_MISSING_TERMS": 28,
    }:
        raise ValueError(f"rights factor-state drift: {governed_factor_states}")
    final_counts = Counter(
        str(row.get("validation_outcome") or "") for row in final_results
    )
    blocker_state = (
        "EXPOSED_IMPLEMENTATION_DEFECT"
        if defects
        else (
            "FULLY_CLOSED_BRIDGE_CERTIFIED_CONTINUITY_BLOCKER"
            if insufficient == 0
            else (
                "PARTIALLY_REDUCED_BRIDGE_CERTIFIED_CONTINUITY_BLOCKER"
                if insufficient < 18
                else "UNCHANGED_BRIDGE_CERTIFIED_CONTINUITY_BLOCKER"
            )
        )
    )
    return {
        "contract_version": BRIDGE_AWARE_CONTINUITY_CERTIFICATE_VERSION,
        "context_contract_version": BRIDGE_AWARE_CONTINUITY_CONTRACT_VERSION,
        "event_count": len(cases),
        "M_complete_governed_context": complete,
        "K_confirmed_correct": confirmed,
        "D_implementation_defect": defects,
        "U_insufficient_evidence": insufficient,
        "C_conflicting_official_evidence": conflicts,
        "bridge_certified_continuity_blocker_state": blocker_state,
        "old_validation_outcomes": b1_summary["rebuilt_validation_outcomes"],
        "new_validation_outcomes": dict(sorted(final_counts.items())),
        "rights_factor_states": governed_factor_states,
        "replay_admission_count_changed": sum(
            bool(row["admitted_to_replay"]) for row in cases
        ),
        "implementation_defect_count": readiness.get(
            "implementation_defect_count",
            defects,
        ),
        "unresolved_admission_interval_count": readiness.get(
            "final_unresolved_interval_count",
        ),
        "global_readiness_state": readiness.get("state"),
        "global_readiness_blockers": readiness.get("blockers", []),
        "adjusted_replay_ready": (
            readiness.get("state") == "READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
        ),
        "reference_price_certification_is_separate": True,
        "continuity_context_certification_is_separate": True,
        "factor_continuity_confirmation_is_separate": True,
        "replay_admission_is_separate": True,
        "factor_value_mutated": False,
        "canonical_candle_mutated": False,
        "market_derived_factor_correction": False,
        "full_benchmark_replays": 0,
        "production_influence": False,
    }


def _source_manifest(
    provider: BridgeAwareContinuityContextProvider,
    paths: dict[str, Path],
    *,
    database_sha256: str,
) -> dict[str, Any]:
    inputs = {
        name: {
            "logical_name": path.name,
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }
        for name, path in sorted(paths.items())
    }
    return {
        "contract_version": BRIDGE_AWARE_CONTINUITY_CERTIFICATE_VERSION,
        "signed_dsi010b1_boundary": {
            "workflow_run_id": provider.source_contract.workflow_run_id,
            "artifact_id": provider.source_contract.artifact_id,
            "artifact_digest": provider.source_contract.artifact_digest,
            "source_head_sha": provider.source_contract.source_head_sha,
            "verified_file_sha256": dict(provider.source_checksums),
        },
        "inputs": inputs,
        "canonical_database_sha256_before": database_sha256,
        "canonical_database_sha256_after": database_sha256,
        "canonical_database_mutated": False,
        "production_influence": False,
    }


def _certificate(
    *,
    cases: tuple[dict[str, Any], ...],
    bars: tuple[dict[str, Any], ...],
    rejections: tuple[dict[str, Any], ...],
    summary: dict[str, Any],
    source_manifest: dict[str, Any],
    report_markdown: str,
) -> dict[str, Any]:
    return {
        "contract_version": BRIDGE_AWARE_CONTINUITY_CERTIFICATE_VERSION,
        "event_count": len(cases),
        "M": summary["M_complete_governed_context"],
        "K": summary["K_confirmed_correct"],
        "D": summary["D_implementation_defect"],
        "U": summary["U_insufficient_evidence"],
        "C": summary["C_conflicting_official_evidence"],
        "cases_sha256": _payload_sha256(list(cases)),
        "bar_ledger_sha256": _payload_sha256(list(bars)),
        "rejections_sha256": _payload_sha256(list(rejections)),
        "summary_sha256": _payload_sha256(summary),
        "source_manifest_sha256": _payload_sha256(source_manifest),
        "report_markdown_sha256": sha256(report_markdown.encode()).hexdigest(),
        "rights_factor_states": summary["rights_factor_states"],
        "new_validation_outcomes": summary["new_validation_outcomes"],
        "global_readiness_state": summary["global_readiness_state"],
        "adjusted_replay_ready": summary["adjusted_replay_ready"],
        "full_benchmark_replays": 0,
        "production_influence": False,
        "certificate_sha256": "",
    }


def _markdown(
    summary: dict[str, Any],
    cases: tuple[dict[str, Any], ...],
) -> str:
    lines = [
        "# DSI-010B2 Bridge-Aware Continuity Certification",
        "",
        "## Contract Separation",
        "",
        "Reference-price certification, continuity-context certification, "
        "factor-continuity confirmation and replay admission are separate contracts.",
        "",
        "## Empirical Result",
        "",
        f"- M complete contexts: {summary['M_complete_governed_context']}",
        f"- K confirmed factors: {summary['K_confirmed_correct']}",
        f"- D implementation defects: {summary['D_implementation_defect']}",
        f"- U insufficient evidence: {summary['U_insufficient_evidence']}",
        f"- C official conflicts: {summary['C_conflicting_official_evidence']}",
        "- Factor states: "
        + json.dumps(summary["rights_factor_states"], sort_keys=True),
        f"- Readiness: {summary['global_readiness_state']}",
        "- Blockers: " + json.dumps(summary["global_readiness_blockers"]),
        "",
        "## Cases",
        "",
        "| Symbol | Context | Final outcome | Replay |",
        "|---|---|---|---:|",
    ]
    lines.extend(
        "| {symbol} | {context} | {outcome} | {replay} |".format(
            symbol=row["symbol"],
            context=row["governed_context_decision"],
            outcome=row["final_validation_outcome"],
            replay=str(row["admitted_to_replay"]).lower(),
        )
        for row in cases
    )
    lines.extend(
        [
            "",
            "No factor, canonical candle, threshold or production policy changed.",
            "",
            "FULL_BENCHMARK_REPLAYS=0",
            "",
            "PRODUCTION_INFLUENCE=false",
            "",
        ]
    )
    return "\n".join(lines)


def _input_files(
    *,
    htr010b_output: Path,
    htr010b1c_output: Path,
    htr010b1e2_output: Path,
    dsi010b1_output: Path,
) -> dict[str, Path]:
    return {
        "htr010b_canonical_events.json": _unique(
            htr010b_output,
            "htr010b_canonical_events.json",
        ),
        "htr010b_adjustment_factors.json": _unique(
            htr010b_output,
            "htr010b_adjustment_factors.json",
        ),
        "b1c_factor_validation_results.json": _unique(
            htr010b1c_output,
            "htr010b1_factor_validation_results.json",
        ),
        "e2_factor_validation_results.json": _unique(
            htr010b1e2_output,
            "htr010b1_factor_validation_results.json",
        ),
        "htr010b1_replay_readiness.json": _unique(
            htr010b1e2_output,
            "htr010b1_replay_readiness.json",
        ),
        "legacy_rights_reference_bridge_summary.json": _unique(
            dsi010b1_output,
            "legacy_rights_reference_bridge_summary.json",
        ),
    }


def _by_event(
    rows: tuple[dict[str, Any], ...],
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row.get("event_id") or ""), []).append(row)
    return grouped


def _one(
    grouped: dict[str, list[dict[str, Any]]],
    event_id: str,
    label: str,
) -> dict[str, Any]:
    rows = grouped.get(event_id, [])
    if len(rows) != 1:
        raise ValueError(f"{label} must contain exactly one row for {event_id}")
    return rows[0]


def _as_date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _case_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row["effective_date"]),
        str(row["symbol"]),
        str(row["event_id"]),
    )


def _bar_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row["effective_date"]),
        str(row["symbol"]),
        str(row["trading_date"]),
        str(row["bar_role"]),
    )


def _rejection_key(row: dict[str, Any]) -> tuple[str, ...]:
    return (
        str(row["effective_date"]),
        str(row["symbol"]),
        str(row["trading_date"]),
        str(row["reason"]),
    )


def _unique(root: Path, name: str) -> Path:
    matches = tuple(sorted(root.resolve().rglob(name)))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one {name}, found {len(matches)}")
    return matches[0]


def _records(path: Path) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        payload = payload.get("records")
    if not isinstance(payload, list) or not all(
        isinstance(row, dict) for row in payload
    ):
        raise ValueError(f"expected JSON records at {path}")
    return tuple(payload)


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object at {path}")
    return payload


def _payload_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()
    return sha256(encoded).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json(path: Path, payload: object) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return path


def _text(path: Path, payload: str) -> Path:
    path.write_text(payload, encoding="utf-8")
    return path


def _csv(path: Path, rows: tuple[dict[str, Any], ...]) -> Path:
    fields = sorted({key for row in rows for key in row})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(value, sort_keys=True, ensure_ascii=True)
                        if isinstance(value, (dict, list, tuple))
                        else value
                    )
                    for key, value in row.items()
                }
            )
    return path


__all__ = [
    "BRIDGE_AWARE_CONTINUITY_CERTIFICATE_VERSION",
    "BridgeAwareContinuityArtifactExporter",
    "BridgeAwareContinuityCertificationEngine",
    "BridgeAwareContinuityCertificationReport",
]
