"""Deterministic certification artifacts for the legacy rights ISIN bridge."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

from alpha.historical_truth.legacy_isin_reference_bridge import (
    LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION,
    PRODUCTION_INFLUENCE,
    SIGNED_DSI010_H09A2_SOURCE_CONTRACT,
    LegacyBridgeDecision,
    LegacyBridgeSourceContract,
    LegacyIsinReferenceBridge,
)

LEGACY_RIGHTS_BRIDGE_CERTIFICATE_VERSION = (
    "DSI-010B1-LEGACY-RIGHTS-REFERENCE-CERTIFICATE-v1.0.0"
)

_BASELINE_RIGHTS_FACTOR_STATES = {
    "FACTOR_CERTIFIED_REFERENCE_PRICE": 37,
    "FACTOR_PROVISIONAL_REFERENCE_PRICE": 40,
    "FACTOR_UNKNOWN_MISSING_TERMS": 28,
}
_BASELINE_VALIDATION_OUTCOMES = {
    "FACTOR_CONFIRMED_CORRECT_MARKET_GAP": 235,
    "FACTOR_CONFLICTING_OFFICIAL_EVIDENCE": 3,
    "FACTOR_INSUFFICIENT_EVIDENCE": 399,
    "FACTOR_REQUIRES_REFERENCE_PRICE": 68,
}
_POST_RIGHTS_SOURCE_BOUNDARY = {
    "workflow_run_id": 30352312594,
    "artifact_id": 8685517709,
    "artifact_name": "dsi010-pre2016-rights-rebuild",
    "artifact_digest": (
        "sha256:0c9e0bed943064737709b92d0708ab5ab838609e339af4d3fee767775e7b5530"
    ),
    "source_head_sha": "729364f6410f84f8eb5905bc07e559c6f545a467",
}
_STRICT_REFERENCE_BASELINE = {
    "workflow_run_id": 30355398752,
    "artifact_id": 8686746487,
    "artifact_name": "dsi010-rights-reference-certified-rebuild",
    "artifact_digest": (
        "sha256:0a19987c06b51ddaaaa8f86fb3dfb4dd927942c97950c98db6ce8a162dec3234"
    ),
}


@dataclass(frozen=True, slots=True)
class LegacyRightsBridgeCertificationReport:
    contract_version: str
    production_influence: bool
    bridge_cases: tuple[dict[str, Any], ...]
    rejections: tuple[dict[str, Any], ...]
    summary: dict[str, Any]
    source_manifest: dict[str, Any]
    certificate: dict[str, Any]
    report_markdown: str
    certificate_sha256: str


class LegacyRightsBridgeCertificationEngine:
    """Reconcile all 39 missing-ISIN cases against rebuilt governed outputs."""

    def run(
        self,
        *,
        htr009a2_output: Path,
        htr010a3_output: Path,
        htr010b_output: Path,
        htr010b1e2_output: Path,
        source_contract: LegacyBridgeSourceContract = (
            SIGNED_DSI010_H09A2_SOURCE_CONTRACT
        ),
    ) -> LegacyRightsBridgeCertificationReport:
        bridge = LegacyIsinReferenceBridge.from_output(
            htr009a2_output,
            htr010a3_output=htr010a3_output,
            source_contract=source_contract,
        )
        inputs = _input_files(htr010b_output, htr010b1e2_output)
        events = _records(inputs["htr010b_canonical_events.json"])
        factors = _records(inputs["htr010b_adjustment_factors.json"])
        cumulative = _records(inputs["htr010b_cumulative_factors.json"])
        validations = _records(inputs["htr010b1_factor_validation_results.json"])
        readiness = _object(inputs["htr010b1_replay_readiness.json"])
        executive = _object(inputs["htr010b_executive_report.json"])
        _validate_downstream_contract(executive, readiness)

        event_by_id = {
            str(row["canonical_event_id"]): row
            for row in events
            if row.get("canonical_event_id")
        }
        validation_by_event: dict[str, list[dict[str, Any]]] = {}
        for row in validations:
            validation_by_event.setdefault(str(row.get("event_id") or ""), []).append(
                row
            )
        cumulative_ids = {
            str(item)
            for row in cumulative
            for item in tuple(row.get("factor_ids") or ())
        }

        bridge_cases = []
        mismatch_controls = []
        rights_factors = []
        for factor in factors:
            event = event_by_id.get(str(factor.get("canonical_event_id") or ""))
            if event is None or event.get("action_type") != "RIGHTS":
                continue
            rights_factors.append(factor)
            original = str(
                factor.get("reference_price_original_provenance_state")
                or factor.get("reference_price_provenance_state")
                or ""
            )
            if original == "PRIOR_ISIN_MISMATCH":
                mismatch_controls.append(
                    _mismatch_control(factor, event, validation_by_event)
                )
                continue
            if original != "PRIOR_ISIN_MISSING":
                continue
            if factor.get("factor_state") == "FACTOR_UNKNOWN_MISSING_TERMS":
                continue
            bridge_cases.append(
                _case(
                    factor,
                    event,
                    cumulative_ids=cumulative_ids,
                    validations=validation_by_event,
                )
            )

        cases = tuple(
            sorted(
                bridge_cases,
                key=lambda row: (
                    str(row["effective_date"]),
                    str(row["symbol"]),
                    str(row["event_id"]),
                ),
            )
        )
        mismatch = tuple(
            sorted(
                mismatch_controls,
                key=lambda row: (
                    str(row["effective_date"]),
                    str(row["symbol"]),
                    str(row["event_id"]),
                ),
            )
        )
        if len(cases) != 39:
            raise ValueError(
                "governed bridge population mismatch: "
                f"expected 39 missing-ISIN cases, found {len(cases)}"
            )
        if len(mismatch) != 1:
            raise ValueError(
                "governed mismatch control mismatch: "
                f"expected 1 explicit mismatch, found {len(mismatch)}"
            )
        if mismatch[0]["symbol"] != "TATAPOWER":
            raise ValueError("explicit mismatch control is not TATAPOWER")

        rejection_rows = tuple(
            sorted(
                (
                    *(row for row in cases if not row["bridge_certified"]),
                    *mismatch,
                ),
                key=lambda row: (
                    str(row["rejection_reason"]),
                    str(row["symbol"]),
                    str(row["event_id"]),
                ),
            )
        )
        summary = _summary(
            cases=cases,
            mismatch=mismatch,
            rights_factors=rights_factors,
            validations=validations,
            readiness=readiness,
        )
        source_manifest = _source_manifest(
            bridge=bridge,
            inputs=inputs,
            executive=executive,
        )
        markdown = _markdown(summary, cases, mismatch)
        certificate = _certificate(
            summary=summary,
            source_manifest=source_manifest,
            bridge_cases=cases,
            rejections=rejection_rows,
            report_markdown=markdown,
            executive=executive,
            readiness=readiness,
        )
        report = LegacyRightsBridgeCertificationReport(
            contract_version=LEGACY_RIGHTS_BRIDGE_CERTIFICATE_VERSION,
            production_influence=PRODUCTION_INFLUENCE,
            bridge_cases=cases,
            rejections=rejection_rows,
            summary=summary,
            source_manifest=source_manifest,
            certificate=certificate,
            report_markdown=markdown,
            certificate_sha256="",
        )
        report = replace(
            report,
            certificate_sha256=_payload_sha256(
                {**report.certificate, "certificate_sha256": ""}
            ),
        )
        certificate_with_hash = {
            **report.certificate,
            "certificate_sha256": report.certificate_sha256,
        }
        return replace(report, certificate=certificate_with_hash)


class LegacyRightsBridgeArtifactExporter:
    """Write stable JSON, CSV and Markdown evidence."""

    def export(
        self,
        report: LegacyRightsBridgeCertificationReport,
        output: Path,
    ) -> tuple[Path, ...]:
        output.mkdir(parents=True, exist_ok=True)
        paths = [
            _json(
                output / "legacy_rights_reference_bridge_cases.json",
                {"records": list(report.bridge_cases)},
            ),
            _csv(
                output / "legacy_rights_reference_bridge_cases.csv",
                report.bridge_cases,
            ),
            _json(
                output / "legacy_rights_reference_bridge_summary.json",
                report.summary,
            ),
            _json(
                output / "legacy_rights_reference_bridge_rejections.json",
                {"records": list(report.rejections)},
            ),
            _json(
                output / "legacy_rights_reference_bridge_source_manifest.json",
                report.source_manifest,
            ),
            _text(
                output / "legacy_rights_reference_bridge_report.md",
                report.report_markdown,
            ),
            _json(
                output / "legacy_rights_reference_bridge_certificate.json",
                report.certificate,
            ),
        ]
        return tuple(paths)


def _case(
    factor: Mapping[str, Any],
    event: Mapping[str, Any],
    *,
    cumulative_ids: set[str],
    validations: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    event_id = str(event["canonical_event_id"])
    factor_id = str(factor["factor_id"])
    bridge_state = str(factor.get("reference_price_bridge_state") or "")
    certified = (
        bridge_state
        == LegacyBridgeDecision.CERTIFIED_DATED_OFFICIAL_IDENTITY_BRIDGE.value
        and factor.get("factor_state") == "FACTOR_CERTIFIED_REFERENCE_PRICE"
    )
    validation_rows = validations.get(event_id, [])
    replay_admitted = any(
        bool(row.get("admitted_to_replay")) for row in validation_rows
    )
    validation_outcomes = sorted(
        {str(row.get("validation_outcome") or "") for row in validation_rows}
    )
    return {
        "case_id": f"legacy-rights-bridge:{sha256(event_id.encode()).hexdigest()}",
        "event_id": event_id,
        "factor_id": factor_id,
        "identity_key": factor["identity_key"],
        "symbol": event.get("symbol"),
        "series": factor.get("reference_price_series"),
        "effective_date": event.get("effective_date"),
        "prior_candle_date": factor.get("reference_price_date"),
        "event_isin": event.get("isin"),
        "observed_prior_candle_isin": factor.get("reference_price_isin"),
        "prior_close": factor.get("reference_price"),
        "prior_candle_source_sha256": factor.get("reference_price_source_sha256"),
        "proposed_bridged_identity": factor.get("reference_price_bridge_identity"),
        "bridge_contract_version": factor.get(
            "reference_price_bridge_contract_version"
        ),
        "bridge_decision": bridge_state,
        "bridge_certified": certified,
        "rejection_reason": (
            None
            if certified
            else factor.get("reference_price_bridge_rejection_reason") or bridge_state
        ),
        "matching_membership_interval_ids": factor.get(
            "reference_price_bridge_membership_interval_ids", []
        ),
        "matching_symbol_interval_ids": factor.get(
            "reference_price_bridge_symbol_interval_ids", []
        ),
        "matching_tradability_interval_ids": factor.get(
            "reference_price_bridge_tradability_interval_ids", []
        ),
        "tradability_states": factor.get(
            "reference_price_bridge_tradability_states", []
        ),
        "tradability_certified": factor.get(
            "reference_price_bridge_tradability_certified"
        ),
        "membership_states": factor.get("reference_price_bridge_membership_states", []),
        "membership_confidence": factor.get(
            "reference_price_bridge_membership_confidence"
        ),
        "symbol_confidence": factor.get("reference_price_bridge_symbol_confidence"),
        "official_source_ids": factor.get(
            "reference_price_bridge_official_source_ids", []
        ),
        "source_event_ids": sorted(
            {
                *factor.get("reference_price_bridge_membership_event_ids", []),
                *factor.get("reference_price_bridge_symbol_event_ids", []),
                *factor.get("reference_price_bridge_official_event_ids", []),
            }
        ),
        "evidence_sha256": factor.get("reference_price_bridge_evidence_sha256", {}),
        "overlapping_identity_keys": factor.get(
            "reference_price_bridge_overlapping_identities", []
        ),
        "symbol_reuse_conflict": factor.get(
            "reference_price_bridge_symbol_reuse_conflict", False
        ),
        "symbol_change_conflict": factor.get(
            "reference_price_bridge_symbol_change_conflict", False
        ),
        "series_transition_conflict": factor.get(
            "reference_price_bridge_series_transition_conflict", False
        ),
        "original_candle_isin_remained_missing": (
            factor.get("reference_price_isin") is None
        ),
        "factor_state": factor.get("factor_state"),
        "factor_certification_changed": certified,
        "cumulative_factor_admission_changed": certified
        and factor_id in cumulative_ids,
        "replay_admission_changed": certified and replay_admitted,
        "final_validation_outcomes": validation_outcomes,
        "production_influence": False,
    }


def _mismatch_control(
    factor: Mapping[str, Any],
    event: Mapping[str, Any],
    validations: Mapping[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    event_id = str(event["canonical_event_id"])
    return {
        "case_id": f"legacy-rights-mismatch:{sha256(event_id.encode()).hexdigest()}",
        "event_id": event_id,
        "factor_id": factor["factor_id"],
        "identity_key": factor["identity_key"],
        "symbol": event.get("symbol"),
        "series": factor.get("reference_price_series"),
        "effective_date": event.get("effective_date"),
        "prior_candle_date": factor.get("reference_price_date"),
        "event_isin": event.get("isin"),
        "observed_prior_candle_isin": factor.get("reference_price_isin"),
        "bridge_decision": (
            LegacyBridgeDecision.PRIOR_ISIN_MISMATCH_NON_BRIDGEABLE.value
        ),
        "bridge_certified": False,
        "rejection_reason": (
            LegacyBridgeDecision.PRIOR_ISIN_MISMATCH_NON_BRIDGEABLE.value
        ),
        "factor_state": factor.get("factor_state"),
        "factor_certification_changed": False,
        "cumulative_factor_admission_changed": False,
        "replay_admission_changed": False,
        "final_validation_outcomes": sorted(
            {
                str(row.get("validation_outcome") or "")
                for row in validations.get(event_id, [])
            }
        ),
        "production_influence": False,
    }


def _summary(
    *,
    cases: tuple[dict[str, Any], ...],
    mismatch: tuple[dict[str, Any], ...],
    rights_factors: list[dict[str, Any]],
    validations: list[dict[str, Any]],
    readiness: Mapping[str, Any],
) -> dict[str, Any]:
    certified = tuple(row for row in cases if row["bridge_certified"])
    factor_states = Counter(
        str(row.get("factor_state") or "") for row in rights_factors
    )
    outcomes = Counter(str(row.get("validation_outcome") or "") for row in validations)
    rejection_counts = Counter(
        str(row["rejection_reason"])
        for row in (*cases, *mismatch)
        if row["rejection_reason"]
    )
    strict_same_isin = sum(
        row.get("factor_state") == "FACTOR_CERTIFIED_REFERENCE_PRICE"
        and row.get("reference_price_provenance_state")
        == "CERTIFIED_SAME_ISIN_CANONICAL_PRIOR_CLOSE"
        for row in rights_factors
    )
    implementation_defects = sum(
        str(row.get("validation_outcome") or "") == "IMPLEMENTATION_DEFECT"
        for row in validations
    )
    certified_total = factor_states["FACTOR_CERTIFIED_REFERENCE_PRICE"]
    expected_certified_total = strict_same_isin + len(certified)
    rejected = tuple(row for row in cases if not row["bridge_certified"])
    certified_provenance_complete = all(
        row["proposed_bridged_identity"] == row["identity_key"]
        and row["event_isin"]
        and row["original_candle_isin_remained_missing"]
        and row["matching_membership_interval_ids"]
        and row["matching_symbol_interval_ids"]
        and row["official_source_ids"]
        and row["source_event_ids"]
        and row["evidence_sha256"]
        and not row["rejection_reason"]
        for row in certified
    )
    state_checks = {
        "rights_factor_count_is_105": len(rights_factors) == 105,
        "strict_same_isin_certified_is_37": strict_same_isin == 37,
        "certified_total_matches_37_plus_n": certified_total
        == expected_certified_total,
        "provisional_total_matches_40_minus_n": factor_states[
            "FACTOR_PROVISIONAL_REFERENCE_PRICE"
        ]
        == 40 - len(certified),
        "missing_terms_remain_28": factor_states["FACTOR_UNKNOWN_MISSING_TERMS"] == 28,
        "mismatch_remains_non_admissible": len(mismatch) == 1
        and not mismatch[0]["bridge_certified"],
        "certified_bridge_provenance_is_complete": certified_provenance_complete,
        "certified_bridge_factors_enter_cumulative_factors": all(
            row["cumulative_factor_admission_changed"] for row in certified
        ),
        "rejected_bridges_do_not_enter_cumulative_factors": not any(
            row["cumulative_factor_admission_changed"] for row in rejected
        ),
        "rejected_bridges_do_not_enter_replay": not any(
            row["replay_admission_changed"] for row in rejected
        ),
        "mismatch_does_not_enter_cumulative_or_replay": not any(
            row["cumulative_factor_admission_changed"]
            or row["replay_admission_changed"]
            for row in mismatch
        ),
        "implementation_defects_are_zero": implementation_defects == 0,
        "unresolved_admission_intervals_are_zero": int(
            readiness.get("final_unresolved_interval_count") or 0
        )
        == 0,
        "production_influence_is_false": readiness.get("production_influence") is False,
    }
    return {
        "contract_version": LEGACY_RIGHTS_BRIDGE_CERTIFICATE_VERSION,
        "bridge_contract_version": (LEGACY_ISIN_REFERENCE_BRIDGE_CONTRACT_VERSION),
        "bridge_case_count": len(cases),
        "explicit_mismatch_control_count": len(mismatch),
        "eligible_bridge_count": len(certified),
        "newly_certified_events": [
            {
                "event_id": row["event_id"],
                "symbol": row["symbol"],
                "effective_date": row["effective_date"],
            }
            for row in certified
        ],
        "rejection_counts": dict(sorted(rejection_counts.items())),
        "baseline_rights_factor_states": _BASELINE_RIGHTS_FACTOR_STATES,
        "rebuilt_rights_factor_states": dict(sorted(factor_states.items())),
        "baseline_validation_outcomes": _BASELINE_VALIDATION_OUTCOMES,
        "rebuilt_validation_outcomes": dict(sorted(outcomes.items())),
        "implementation_defect_count": implementation_defects,
        "final_unresolved_admission_interval_count": int(
            readiness.get("final_unresolved_interval_count") or 0
        ),
        "readiness_state": readiness.get("state"),
        "readiness_blockers": readiness.get("blockers", []),
        "rights_reference_blocker_state": (
            "FULLY_CLOSED"
            if len(certified) == 39
            else "PARTIALLY_REDUCED"
            if certified
            else "UNCHANGED"
        ),
        "state_checks": state_checks,
        "certificate_eligible": all(state_checks.values()),
        "full_benchmark_replays": 0,
        "production_influence": False,
    }


def _source_manifest(
    *,
    bridge: LegacyIsinReferenceBridge,
    inputs: Mapping[str, Path],
    executive: Mapping[str, Any],
) -> dict[str, Any]:
    contract = bridge.source_contract
    return {
        "contract_version": LEGACY_RIGHTS_BRIDGE_CERTIFICATE_VERSION,
        "htr009a2_signed_source": {
            "source_contract_id": contract.contract_id,
            "workflow_run_id": contract.workflow_run_id,
            "artifact_id": contract.artifact_id,
            "artifact_name": contract.artifact_name,
            "artifact_digest": contract.artifact_digest,
            "source_head_sha": contract.source_head_sha,
            "report_sha256": bridge.source_report_sha256,
            "files": [
                {"path": path, "sha256": digest}
                for path, digest in bridge.source_checksums
            ],
        },
        "post_rights_rebuild_source_boundary": _POST_RIGHTS_SOURCE_BOUNDARY,
        "strict_reference_certification_baseline": _STRICT_REFERENCE_BASELINE,
        "governed_rebuild_inputs": [
            {
                "path": name,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
            for name, path in sorted(inputs.items())
        ],
        "htr010b_report_sha256": executive.get("report_sha256"),
        "production_influence": False,
    }


def _certificate(
    *,
    summary: Mapping[str, Any],
    source_manifest: Mapping[str, Any],
    bridge_cases: tuple[dict[str, Any], ...],
    rejections: tuple[dict[str, Any], ...],
    report_markdown: str,
    executive: Mapping[str, Any],
    readiness: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "contract_version": LEGACY_RIGHTS_BRIDGE_CERTIFICATE_VERSION,
        "source_contract_id": source_manifest["htr009a2_signed_source"][
            "source_contract_id"
        ],
        "bridge_case_count": summary["bridge_case_count"],
        "eligible_bridge_count": summary["eligible_bridge_count"],
        "rejection_counts": summary["rejection_counts"],
        "rights_factor_states": summary["rebuilt_rights_factor_states"],
        "validation_outcomes": summary["rebuilt_validation_outcomes"],
        "implementation_defect_count": summary["implementation_defect_count"],
        "final_unresolved_admission_interval_count": summary[
            "final_unresolved_admission_interval_count"
        ],
        "readiness_state": readiness.get("state"),
        "readiness_blockers": readiness.get("blockers", []),
        "htr010b_report_sha256": executive.get("report_sha256"),
        "source_manifest_sha256": _payload_sha256(source_manifest),
        "bridge_cases_sha256": _payload_sha256({"records": list(bridge_cases)}),
        "rejections_sha256": _payload_sha256({"records": list(rejections)}),
        "summary_sha256": _payload_sha256(summary),
        "report_markdown_sha256": sha256(report_markdown.encode()).hexdigest(),
        "certificate_eligible": summary["certificate_eligible"],
        "full_benchmark_replays": 0,
        "adjusted_replay_ready": (
            readiness.get("state") == "READY_FOR_ADJUSTED_REPLAY_INTEGRATION"
        ),
        "production_influence": False,
        "certificate_sha256": "",
    }


def _markdown(
    summary: Mapping[str, Any],
    cases: tuple[dict[str, Any], ...],
    mismatch: tuple[dict[str, Any], ...],
) -> str:
    certified = [row for row in cases if row["bridge_certified"]]
    blockers = summary["readiness_blockers"] or ["None"]
    return "\n".join(
        (
            "# DSI-010B1 Governed Legacy ISIN Bridge Certification",
            "",
            f"- Missing-ISIN bridge cases: {len(cases)}",
            f"- Newly certified bridges: {len(certified)}",
            f"- Explicit mismatch controls: {len(mismatch)}",
            f"- Rights-reference blocker: {summary['rights_reference_blocker_state']}",
            f"- Final readiness: {summary['readiness_state']}",
            "- Full benchmark replays: 0",
            "- Production influence: false",
            "",
            "## Newly Certified",
            *(
                [
                    f"- {row['symbol']} on {row['effective_date']} "
                    f"(`{row['event_id']}`)"
                    for row in certified
                ]
                or ["- None"]
            ),
            "",
            "## Rejection Counts",
            *(
                [
                    f"- {reason}: {count}"
                    for reason, count in summary["rejection_counts"].items()
                ]
                or ["- None"]
            ),
            "",
            "## TATAPOWER",
            "- The explicit prior-ISIN mismatch remains non-bridgeable under the "
            "missing-ISIN contract.",
            "",
            "## Remaining Readiness Blockers",
            *[f"- {item}" for item in blockers],
            "",
            "The bridge certifies dated official identity evidence; it does not "
            "write an ISIN into the canonical candle or infer identity from price.",
            "",
            "PRODUCTION_INFLUENCE=false",
            "",
        )
    )


def _input_files(
    htr010b_output: Path,
    htr010b1e2_output: Path,
) -> dict[str, Path]:
    names = {
        "htr010b_canonical_events.json": htr010b_output,
        "htr010b_adjustment_factors.json": htr010b_output,
        "htr010b_cumulative_factors.json": htr010b_output,
        "htr010b_executive_report.json": htr010b_output,
        "htr010b1_factor_validation_results.json": htr010b1e2_output,
        "htr010b1_replay_readiness.json": htr010b1e2_output,
    }
    return {name: _governed_file(root, name) for name, root in names.items()}


def _validate_downstream_contract(
    executive: Mapping[str, Any],
    readiness: Mapping[str, Any],
) -> None:
    if executive.get("production_influence") is not False:
        raise ValueError("HTR-010B report has production influence")
    if not _valid_sha256(str(executive.get("report_sha256") or "")):
        raise ValueError("HTR-010B report SHA-256 is missing")
    if readiness.get("production_influence") is not False:
        raise ValueError("HTR-010B1E2 readiness has production influence")


def _governed_file(root: Path, name: str) -> Path:
    resolved_root = root.resolve()
    path = (resolved_root / name).resolve()
    try:
        path.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"governed input escapes artifact root: {name}") from exc
    if not path.is_file():
        raise ValueError(f"required governed input is missing: {path}")
    return path


def _records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
        rows = payload["records"]
    else:
        raise ValueError(f"{path.name} must contain a records array")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path.name} contains a non-object record")
    return [dict(row) for row in rows]


def _object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain an object")
    return dict(payload)


def _payload_sha256(payload: object) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _json(path: Path, payload: object) -> Path:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def _csv(path: Path, rows: tuple[dict[str, Any], ...]) -> Path:
    fields = sorted({key for row in rows for key in row}) or ["value"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: (
                        json.dumps(value, sort_keys=True, separators=(",", ":"))
                        if isinstance(value, (list, dict))
                        else value
                    )
                    for key, value in ((field, row.get(field)) for field in fields)
                }
            )
    return path


def _text(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


__all__ = [
    "LEGACY_RIGHTS_BRIDGE_CERTIFICATE_VERSION",
    "LegacyRightsBridgeArtifactExporter",
    "LegacyRightsBridgeCertificationEngine",
    "LegacyRightsBridgeCertificationReport",
]
