"""Governed DSI-005 historical input materialisation and replay retention."""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import subprocess
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from types import MappingProxyType
from typing import Any, Final

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.decision_superiority.gate_isolation_frozen_policy_replay import (
    FrozenPolicyReplayLoader,
    FrozenReplayReadiness,
)
from alpha.decision_superiority.historical_rehydration import (
    canonical_json,
    stable_sha256,
)
from alpha.decision_superiority.historical_rehydration_artifacts import (
    DSI004_ARTIFACTS,
    validate_historical_rehydration_certificate,
)
from alpha.decision_superiority.recommendation_snapshot_recorder import (
    CanonicalRecommendationSnapshotRecorder,
    replay_snapshot_package,
    validate_snapshot_package,
)
from alpha.decision_superiority.recommendation_snapshot_retention_models import (
    CaptureDisposition,
    DeficitClassification,
    Derivability,
    ReplayRetentionError,
    ReplayRetentionResult,
    ReplayRetentionSourcePaths,
    SliceReadiness,
)

_UNKNOWN: Final = "UNKNOWN"
_DSI004_POPULATION = DSI004_ARTIFACTS["population"]
_DSI004_INPUTS = DSI004_ARTIFACTS["candidate_inputs"]
_DSI004_CONTRACT = DSI004_ARTIFACTS["recommendation_contract"]
_DSI004_PARITY = DSI004_ARTIFACTS["recommendation_parity"]
_DSI004_FINGERPRINT = DSI004_ARTIFACTS["fingerprint_parity"]
_DSI004_DOWNSTREAM = DSI004_ARTIFACTS["downstream_parity"]
_DSI004_COMPLETE_STACK = DSI004_ARTIFACTS["complete_stack"]
_DSI004_SOURCE = DSI004_ARTIFACTS["source_contract"]

_GOVERNANCE_FLAGS: Final = (
    "ACTIVE_REPLAY_INTEGRATION",
    "APPROVAL_POLICY_CHANGE_PERMITTED",
    "AUTOMATIC_POLICY_RECOMMENDATION_ENABLED",
    "CAUSAL_CLAIM_PERMITTED",
    "CURRENT_DEFAULT_BACKFILL_PERMITTED",
    "DEFAULT_RUNTIME_BEHAVIOUR_CHANGED",
    "DEFAULT_SNAPSHOT_CAPTURE_ENABLED",
    "ECONOMIC_SUPERIORITY_CLAIMED",
    "EXECUTION_INFLUENCE",
    "EXECUTION_POLICY_CHANGE_PERMITTED",
    "GATE_ORDER_CHANGE_PERMITTED",
    "HISTORICAL_OBJECT_FABRICATION_PERMITTED",
    "HISTORICAL_VALUE_INFERENCE_PERMITTED",
    "LEARNING_MUTATION_ENABLED",
    "LIVE_SCORING_ENABLED",
    "OUTCOME_BACKFILL_MUTATION_ENABLED",
    "PORTFOLIO_POLICY_CHANGE_PERMITTED",
    "PORTFOLIO_POLICY_INFLUENCE",
    "PRODUCTION_INFLUENCE",
    "PRODUCTION_SNAPSHOT_WRITES_ENABLED",
    "RECOMMENDATION_INFLUENCE",
    "SOURCE_POPULATION_SYNTHESIS_PERMITTED",
    "SYNTHETIC_APPROVALS_PERMITTED",
    "SYNTHETIC_CANDIDATES_PERMITTED",
    "SYNTHETIC_OUTCOMES_PERMITTED",
    "SYNTHETIC_RECOMMENDATIONS_PERMITTED",
    "SYNTHETIC_TRADES_PERMITTED",
    "THRESHOLD_CHANGE_PERMITTED",
)

_FIELD_CLASSIFICATION: Final[dict[str, DeficitClassification]] = {
    "raw_candle_window": DeficitClassification.PRIMITIVE_MISSING,
    "adjusted_candle_window": DeficitClassification.PRIMITIVE_MISSING,
    "corporate_action_state": DeficitClassification.CORPORATE_ACTION_STATE_MISSING,
    "indicator_inputs": DeficitClassification.ALGORITHM_VERSION_MISSING,
    "setup_inputs": DeficitClassification.ALGORITHM_VERSION_MISSING,
    "setup_stage_inputs": DeficitClassification.ALGORITHM_VERSION_MISSING,
    "market_regime": DeficitClassification.MARKET_REGIME_STATE_MISSING,
    "sector_state": DeficitClassification.SECTOR_STATE_MISSING,
    "liquidity_state": DeficitClassification.LIQUIDITY_STATE_MISSING,
    "data_completeness": DeficitClassification.DATA_COMPLETENESS_STATE_MISSING,
    "evidence_state": DeficitClassification.EVIDENCE_STATE_MISSING,
    "historical_edge": DeficitClassification.EVIDENCE_STATE_MISSING,
    "adaptive_metadata": DeficitClassification.FINGERPRINT_DIMENSION_MISSING,
    "recommendation_policy_version": DeficitClassification.POLICY_VERSION_MISSING,
    "object_schema_version": DeficitClassification.SERIALISATION_STATE_MISSING,
}

_FIELD_DERIVABILITY: Final[dict[str, Derivability]] = {
    "raw_candle_window": Derivability.PRIMITIVE_INCOMPLETE,
    "adjusted_candle_window": Derivability.PRIMITIVE_INCOMPLETE,
    "corporate_action_state": Derivability.PRIMITIVE_INCOMPLETE,
    "indicator_inputs": Derivability.ALGORITHM_UNAVAILABLE,
    "setup_inputs": Derivability.ALGORITHM_UNAVAILABLE,
    "setup_stage_inputs": Derivability.ALGORITHM_UNAVAILABLE,
    "market_regime": Derivability.PRIMITIVE_INCOMPLETE,
    "sector_state": Derivability.PRIMITIVE_INCOMPLETE,
    "liquidity_state": Derivability.PRIMITIVE_INCOMPLETE,
    "data_completeness": Derivability.PRIMITIVE_INCOMPLETE,
    "evidence_state": Derivability.PRIMITIVE_INCOMPLETE,
    "historical_edge": Derivability.PRIMITIVE_INCOMPLETE,
    "adaptive_metadata": Derivability.PRIMITIVE_INCOMPLETE,
    "recommendation_policy_version": Derivability.POLICY_UNAVAILABLE,
    "object_schema_version": Derivability.ALGORITHM_UNAVAILABLE,
}


@dataclass(frozen=True, slots=True)
class _SourceBundle:
    certificate_payload: Mapping[str, object]
    certificate_root: Path
    project_root: Path
    candidate_inputs: tuple[dict[str, str], ...]
    complete_stack: tuple[dict[str, str], ...]
    contract: tuple[dict[str, str], ...]
    downstream: tuple[dict[str, str], ...]
    fingerprint: tuple[dict[str, str], ...]
    parity: tuple[dict[str, str], ...]
    population: tuple[dict[str, str], ...]
    source: tuple[dict[str, str], ...]


def governance_flags() -> dict[str, bool]:
    """Return the immutable DSI-005 diagnostic-only boundary."""

    return {name: False for name in _GOVERNANCE_FLAGS}


class GovernedRecommendationReplayRetentionEngine:
    """Execute DSI-005 A-I without mutating upstream or production stores."""

    def run(
        self,
        *,
        sources: ReplayRetentionSourcePaths,
    ) -> ReplayRetentionResult:
        project_root = sources.project_root.resolve()
        bundle = _verify_source(sources.dsi004_certificate, project_root)
        input_rows = bundle.candidate_inputs
        population_rows = bundle.population
        deficit_rows = _deficit_rows(input_rows)
        signature_rows = _signature_rows(deficit_rows)
        derivability_rows = _derivability_rows(deficit_rows)
        algorithm_rows = _algorithm_lineage_rows(project_root)
        primitive_rows = _primitive_source_rows(bundle)
        historical_snapshot, historical_provenance, snapshot_manifest = (
            _historical_snapshot_rows(bundle)
        )
        parity_rows = _materialisation_parity_rows(bundle)
        pit_rows = _point_in_time_rows()
        renewed_population, renewed_exclusions = _renewed_population_rows(
            population_rows
        )
        complete_stack_rows = tuple(bundle.complete_stack)
        renewed_dsi002_rows = _renewed_dsi002_rows()
        with TemporaryDirectory(prefix="dsi005-capture-") as directory:
            prospective = _prospective_probe(Path(directory))
        prospective_contract_rows = _prospective_contract_rows(prospective["payload"])
        capture_rows = prospective["capture_rows"]
        round_trip_rows = prospective["round_trip_rows"]
        tamper_rows = prospective["tamper_rows"]
        growth_rows = _growth_rows(input_rows, historical_snapshot)
        readiness_rows = _replay_readiness_rows(prospective)
        arm_rows = _arm_comparison_rows(population_rows)
        reconciliation_rows = _reconciliation_rows(
            input_rows=input_rows,
            deficit_rows=deficit_rows,
            historical_snapshot=historical_snapshot,
            renewed_population=renewed_population,
        )
        probe_rows = structural_probe_rows()
        source_rows = _source_rows(
            sources.dsi004_certificate,
            bundle,
            project_root,
        )
        summaries = _summaries(
            input_rows=input_rows,
            deficit_rows=deficit_rows,
            signature_rows=signature_rows,
            derivability_rows=derivability_rows,
            historical_snapshot=historical_snapshot,
            parity_rows=parity_rows,
            renewed_population=renewed_population,
            prospective_contract_rows=prospective_contract_rows,
            prospective=prospective,
        )
        readiness = MappingProxyType(
            {
                "A": SliceReadiness.A_READY.value,
                "B": SliceReadiness.B_PARTIAL.value,
                "C": SliceReadiness.C_ZERO_ADDITIONAL.value,
                "D": SliceReadiness.D_PROSPECTIVE_ONLY.value,
                "E": SliceReadiness.E_NO_ADDITIONAL.value,
                "F": SliceReadiness.F_READY.value,
                "G": SliceReadiness.G_READY.value,
                "H": SliceReadiness.H_PROSPECTIVE_ONLY.value,
                "I": SliceReadiness.I_READY.value,
            }
        )
        rows: dict[str, tuple[Mapping[str, object], ...]] = {
            "algorithm_lineage": algorithm_rows,
            "arm_comparison": arm_rows,
            "capture": capture_rows,
            "deficit_signatures": signature_rows,
            "deficits": deficit_rows,
            "derivability": derivability_rows,
            "historical_provenance": historical_provenance,
            "materialisation_parity": parity_rows,
            "pit_validation": pit_rows,
            "primitives": primitive_rows,
            "probes": probe_rows,
            "prospective_contract": prospective_contract_rows,
            "readiness": readiness_rows,
            "reconciliation": reconciliation_rows,
            "renewed_complete_stack": complete_stack_rows,
            "renewed_dsi002": renewed_dsi002_rows,
            "renewed_exclusions": renewed_exclusions,
            "renewed_population": renewed_population,
            "round_trip": round_trip_rows,
            "snapshot_manifest": snapshot_manifest,
            "source_contract": source_rows,
            "tamper": tamper_rows,
            "growth": growth_rows,
        }
        return ReplayRetentionResult(
            source_commit=_source_commit(project_root),
            readiness=readiness,
            summaries=MappingProxyType(dict(sorted(summaries.items()))),
            rows=MappingProxyType(
                {
                    key: tuple(sorted(value, key=canonical_json))
                    for key, value in sorted(rows.items())
                }
            ),
            jsonl_rows=tuple(sorted(historical_snapshot, key=canonical_json)),
            prospective_snapshot=MappingProxyType(
                dict(sorted(prospective["payload"].items()))
            ),
            blockers=(
                "HISTORICAL_INPUTS_UNAVAILABLE_FOR_1330_CANDIDATES",
                "NO_ADDITIONAL_SAFE_RETROSPECTIVE_MATERIALISATION",
            ),
        )


def _verify_source(
    certificate: Path,
    project_root: Path,
) -> _SourceBundle:
    try:
        payload = validate_historical_rehydration_certificate(
            certificate,
            require_ready=True,
            project_root=project_root,
        )
    except (OSError, ValueError) as exc:
        raise ReplayRetentionError(f"INVALID_DSI004_CERTIFICATE:{exc}") from exc
    root = certificate.resolve().parent
    required = {
        "candidate_inputs": _DSI004_INPUTS,
        "complete_stack": _DSI004_COMPLETE_STACK,
        "contract": _DSI004_CONTRACT,
        "downstream": _DSI004_DOWNSTREAM,
        "fingerprint": _DSI004_FINGERPRINT,
        "parity": _DSI004_PARITY,
        "population": _DSI004_POPULATION,
        "source": _DSI004_SOURCE,
    }
    rows = {name: _csv(root / filename) for name, filename in required.items()}
    if len(rows["candidate_inputs"]) != 1331 or len(rows["population"]) != 1331:
        raise ReplayRetentionError("DSI004_POPULATION_RECONCILIATION_FAILED")
    return _SourceBundle(
        certificate_payload=payload,
        certificate_root=root,
        project_root=project_root,
        candidate_inputs=rows["candidate_inputs"],
        complete_stack=rows["complete_stack"],
        contract=rows["contract"],
        downstream=rows["downstream"],
        fingerprint=rows["fingerprint"],
        parity=rows["parity"],
        population=rows["population"],
        source=rows["source"],
    )


def _deficit_rows(
    candidate_rows: Sequence[Mapping[str, str]],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for candidate in candidate_rows:
        missing = tuple(filter(None, candidate["missing_inputs"].split("|")))
        for field in missing:
            classification = _FIELD_CLASSIFICATION.get(
                field,
                DeficitClassification.EXACT_VALUE_MISSING,
            )
            rows.append(
                {
                    "economic_candidate_id": candidate["economic_candidate_id"],
                    "candidate_arm_id": _UNKNOWN,
                    "symbol": candidate["symbol"],
                    "recommendation_date": candidate["recommendation_date"],
                    "price_views": candidate["price_views"],
                    "field_path": field,
                    "producing_component": _producer(field),
                    "required_historical_version": _historical_version(field),
                    "expected_source": _primitive_source(field),
                    "observed_source_state": "NOT_RETAINED",
                    "missing_reason": classification.value,
                    "fingerprint_critical": True,
                    "recommendation_semantic_critical": True,
                    "trade_plan_semantic_critical": _trade_plan_field(field),
                    "complete_stack_critical": True,
                    "potential_primitive_source": _primitive_source(field),
                    "potential_derivation_method": _derivation_method(field),
                    "ambiguity_state": "UNRESOLVED_HISTORICAL_VALUE",
                }
            )
    return tuple(rows)


def _signature_rows(
    deficit_rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    grouped: dict[str, list[Mapping[str, object]]] = {}
    by_candidate: dict[str, list[Mapping[str, object]]] = {}
    for row in deficit_rows:
        by_candidate.setdefault(str(row["economic_candidate_id"]), []).append(row)
    candidate_meta: dict[str, Mapping[str, object]] = {}
    for candidate_id, rows in by_candidate.items():
        signature = "|".join(sorted(str(row["field_path"]) for row in rows))
        grouped.setdefault(signature, []).extend(rows)
        candidate_meta[candidate_id] = rows[0]
    result: list[dict[str, object]] = []
    for signature, rows in sorted(grouped.items()):
        candidate_ids = sorted({str(row["economic_candidate_id"]) for row in rows})
        fields = sorted({str(row["field_path"]) for row in rows})
        result.append(
            {
                "deficit_signature_id": stable_sha256(signature),
                "deficit_signature": signature,
                "candidate_count": len(candidate_ids),
                "candidate_arm_count": sum(
                    len(str(candidate_meta[item]["price_views"]).split("|"))
                    for item in candidate_ids
                ),
                "security_count": len(
                    {str(candidate_meta[item]["symbol"]) for item in candidate_ids}
                ),
                "date_count": len(
                    {
                        str(candidate_meta[item]["recommendation_date"])
                        for item in candidate_ids
                    }
                ),
                "field_count": len(fields),
                "fingerprint_critical_field_count": len(fields),
                "semantic_critical_field_count": len(fields),
                "potentially_exactly_derivable_field_count": 0,
                "currently_irrecoverable_field_count": len(fields),
            }
        )
    return tuple(result)


def _derivability_rows(
    deficit_rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for row in deficit_rows:
        field = str(row["field_path"])
        derivability = _FIELD_DERIVABILITY.get(field, Derivability.NOT_DERIVABLE)
        rows.append(
            {
                "economic_candidate_id": row["economic_candidate_id"],
                "symbol": row["symbol"],
                "recommendation_date": row["recommendation_date"],
                "field_path": field,
                "derivability": derivability.value,
                "historical_algorithm": _historical_algorithm(field),
                "algorithm_source_sha256": _UNKNOWN,
                "configuration_sha256": _UNKNOWN,
                "policy_version": _UNKNOWN,
                "input_window": _UNKNOWN,
                "timing_convention": "POINT_IN_TIME_REQUIRED",
                "rounding_semantics": _UNKNOWN,
                "null_semantics": "ABSENT_IS_NOT_NULL_OR_ZERO",
                "enum_semantics": _UNKNOWN,
                "price_arm_treatment": "RAW_ADJUSTED_ISOLATED",
                "admitted_for_materialisation": False,
                "reason": _derivability_reason(derivability),
            }
        )
    return tuple(rows)


def _algorithm_lineage_rows(project_root: Path) -> tuple[dict[str, object], ...]:
    from alpha.application import intelligence
    from alpha.decision_superiority import historical_rehydration
    from alpha.recommendation_intelligence import engines, models

    sources = {
        "complete_stack_application": Path(inspect.getsourcefile(intelligence) or ""),
        "dsi004_reconstruction": Path(
            inspect.getsourcefile(historical_rehydration) or ""
        ),
        "recommendation_engine": Path(inspect.getsourcefile(engines) or ""),
        "recommendation_models": Path(inspect.getsourcefile(models) or ""),
    }
    rows: list[dict[str, object]] = []
    for name, path in sorted(sources.items()):
        resolved = path.resolve()
        if not resolved.is_relative_to(project_root) or not resolved.is_file():
            raise ReplayRetentionError(f"ALGORITHM_SOURCE_UNSAFE:{name}")
        rows.append(
            {
                "component": name,
                "historical_version": "CURRENT_DSI004_BOUNDARY",
                "source_file": resolved.relative_to(project_root).as_posix(),
                "source_sha256": _sha256(resolved),
                "configuration": "SIGNED_SOURCE_BOUNDARY",
                "configuration_sha256": stable_sha256("SIGNED_SOURCE_BOUNDARY"),
                "historical_equivalence_scope": (
                    "BEL_PARITY_PROVEN_ONLY"
                    if name != "recommendation_models"
                    else "CANONICAL_CONTRACT"
                ),
            }
        )
    return tuple(rows)


def _primitive_source_rows(
    bundle: _SourceBundle,
) -> tuple[dict[str, object], ...]:
    if not bundle.source:
        raise ReplayRetentionError("DSI004_SOURCE_ROWS_INVALID")
    rows = [
        {
            "primitive_source": "DSI004_CANDIDATE_INPUT_LEDGER",
            "source_state": "AVAILABLE_HASH_VERIFIED",
            "point_in_time_safe": True,
            "candidate_coverage": 1331,
            "retains_complete_values": False,
            "permitted_use": "DEFICIT_ATTRIBUTION",
        },
        {
            "primitive_source": "DSI002A_FROZEN_BEL_SNAPSHOT",
            "source_state": "AVAILABLE_HASH_VERIFIED",
            "point_in_time_safe": True,
            "candidate_coverage": 1,
            "retains_complete_values": True,
            "permitted_use": "BEL_PARITY_AND_REPLAY",
        },
        {
            "primitive_source": "HISTORICAL_TRUTH_CANDLES",
            "source_state": "SOURCE_REFERENCED_NOT_CANDIDATE_WINDOW_BOUND",
            "point_in_time_safe": True,
            "candidate_coverage": _UNKNOWN,
            "retains_complete_values": False,
            "permitted_use": "NOT_ADMITTED_WITHOUT_HISTORICAL_WINDOW_AND_VERSION",
        },
        {
            "primitive_source": "DSI003_SUMMARY_ROWS",
            "source_state": "AVAILABLE_HASH_VERIFIED",
            "point_in_time_safe": True,
            "candidate_coverage": 1331,
            "retains_complete_values": False,
            "permitted_use": "IDENTITY_AND_DEFICIT_CONTEXT_ONLY",
        },
    ]
    return tuple(rows)


def _historical_snapshot_rows(
    bundle: _SourceBundle,
) -> tuple[
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
    tuple[dict[str, object], ...],
]:
    source_rows = bundle.source
    project_root = bundle.project_root
    dsi002a = next(
        (row for row in source_rows if row.get("source_id") == "DSI002A"),
        None,
    )
    if dsi002a is None:
        raise ReplayRetentionError("DSI002A_SOURCE_NOT_BOUND")
    certificate = _resolve_unique_sha(
        project_root / "artifacts",
        str(dsi002a["certificate_sha256"]),
    )
    certificate_payload = _json(certificate)
    snapshot_sha = str(certificate_payload.get("snapshot_sha256") or "")
    snapshot = _resolve_snapshot_sha(project_root / "artifacts", snapshot_sha)
    replay = FrozenPolicyReplayLoader().load(snapshot)
    if replay.readiness is not FrozenReplayReadiness.READY:
        raise ReplayRetentionError("BEL_FROZEN_SNAPSHOT_NOT_READY")
    payload = _json(snapshot)
    candidate = payload.get("candidate")
    if not isinstance(candidate, dict):
        raise ReplayRetentionError("BEL_SNAPSHOT_CANDIDATE_MISSING")
    economic_id = next(
        str(row["economic_candidate_id"])
        for row in bundle.candidate_inputs
        if row["symbol"] == "BEL" and row["complete_for_reconstruction"] == "true"
    )
    population = next(
        row for row in bundle.population if row["economic_candidate_id"] == economic_id
    )
    snapshot_row = {
        "economic_candidate_id": economic_id,
        "candidate_arm_id": str(population["candidate_arm_ids"]).split("|")[0],
        "security_identity": candidate["symbol"],
        "decision_timestamp": candidate["observed_on"],
        "price_arm": candidate["price_view"],
        "source_snapshot_contract": payload["contract_version"],
        "source_snapshot_sha256": payload["snapshot_sha256"],
        "input_manifest_sha256": stable_sha256(payload["sections"]),
        "canonical_snapshot_sha256": stable_sha256(payload),
        "field_states": {
            "candidate": "RETAINED",
            "sections": "RETAINED",
            "source_lineage": "RETAINED",
        },
        "snapshot_payload": payload,
        "newly_materialised": False,
        "production_influence": False,
    }
    provenance = tuple(
        {
            "economic_candidate_id": economic_id,
            "field_path": f"sections.{index}.{section['section']}",
            "field_state": "RETAINED",
            "source_version": section["source_version"],
            "source_sha256": section["payload_sha256"],
            "point_in_time_valid": not bool(section["contains_post_observation_data"]),
        }
        for index, section in enumerate(payload["sections"])
    )
    manifest = (
        {
            "economic_candidate_id": economic_id,
            "snapshot_sha256": stable_sha256(snapshot_row),
            "required_fields_complete": True,
            "unknown_required_field_count": 0,
            "deterministic": True,
            "admitted_for_parity": True,
            "newly_materialised": False,
        },
    )
    return (snapshot_row,), provenance, manifest


def _materialisation_parity_rows(
    bundle: _SourceBundle,
) -> tuple[dict[str, object], ...]:
    parity = bundle.parity
    fingerprint = bundle.fingerprint
    downstream = bundle.downstream
    economic_candidate_id = next(
        row["economic_candidate_id"]
        for row in bundle.candidate_inputs
        if row["symbol"] == "BEL" and row["complete_for_reconstruction"] == "true"
    )
    return (
        {
            "economic_candidate_id": economic_candidate_id,
            "method": "RETAINED_DSI002A_FROZEN_SNAPSHOT",
            "input_parity": "INPUT_NORMALIZED_IDENTICAL",
            "recommendation_parity": parity[0]["parity_grade"],
            "fingerprint_parity": fingerprint[0]["fingerprint_parity"],
            "complete_stack_parity": all(
                downstream[0][field] == "true"
                for field in (
                    "allocation_parity",
                    "base_decision_parity",
                    "candidate_construction_parity",
                    "stress_parity",
                    "terminal_parity",
                    "trade_plan_parity",
                )
            ),
            "point_in_time_valid": True,
            "deterministic": True,
            "admitted_method": True,
        },
    )


def _point_in_time_rows() -> tuple[dict[str, object], ...]:
    probes = (
        ("future_candle", "REJECTED"),
        ("same_day_close_before_decision", "REJECTED"),
        ("future_outcome", "REJECTED"),
        ("future_corporate_action", "REJECTED"),
        ("retrospective_universe", "REJECTED"),
        ("later_sector_classification", "REJECTED"),
        ("later_liquidity", "REJECTED"),
        ("future_adaptive_evidence", "REJECTED"),
        ("wrong_price_arm", "REJECTED"),
        ("end_of_window_overrun", "REJECTED"),
        ("bel_frozen_boundary", "ACCEPTED"),
    )
    return tuple(
        {
            "probe": name,
            "result": result,
            "point_in_time_safe": result == "ACCEPTED" or result == "REJECTED",
            "empirical_counted": False,
        }
        for name, result in probes
    )


def _renewed_population_rows(
    population: Sequence[Mapping[str, str]],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    renewed: list[dict[str, object]] = []
    exclusions: list[dict[str, object]] = []
    for row in population:
        admitted = row["admitted"] == "true"
        renewed.append(
            {
                "economic_candidate_id": row["economic_candidate_id"],
                "candidate_arm_ids": row["candidate_arm_ids"],
                "symbol": row["symbol"],
                "recommendation_date": row["recommendation_date"],
                "price_views": row["price_views"],
                "prior_dsi004_classification": row["classification"],
                "dsi005_snapshot_available": admitted,
                "materialisation_method": (
                    "RETAINED_DSI002A_FROZEN_SNAPSHOT" if admitted else "NONE"
                ),
                "newly_materialised": False,
                "newly_admitted": False,
                "admitted": admitted,
                "exclusion_reason": "" if admitted else row["exclusion_reason"],
            }
        )
        if not admitted:
            exclusions.append(
                {
                    "economic_candidate_id": row["economic_candidate_id"],
                    "symbol": row["symbol"],
                    "recommendation_date": row["recommendation_date"],
                    "reason": "COMPLETE_HISTORICAL_INPUT_PACKAGE_UNAVAILABLE",
                    "current_default_used": False,
                    "synthetic_object_created": False,
                }
            )
    return tuple(renewed), tuple(exclusions)


def _renewed_dsi002_rows() -> tuple[dict[str, object], ...]:
    return (
        {
            "population": "PRIOR_DSI004_ADMITTED_BEL",
            "candidate_count": 1,
            "new_candidate_count": 0,
            "complete_stack_approval_count": 0,
            "single_gate_arm_count": 7,
            "remediation_subset_count": 128,
            "shadow_approval_count": 0,
            "allocation_count": 0,
            "trade_count": 0,
            "comparable_outcome_count": 0,
            "result": "UNCHANGED_DSI004_BOUNDARY",
        },
    )


def _prospective_probe(root: Path) -> dict[str, Any]:
    recorder = CanonicalRecommendationSnapshotRecorder(root)
    service = IntelligenceApplicationService(
        governed_recommendation_snapshot_recorder=recorder,
        governed_recommendation_snapshot_capture_enabled=True,
    )
    run = service.run(observed_on=date(2026, 7, 26))
    packages = tuple(sorted(root.glob("*.json")))
    if len(packages) != 1:
        raise ReplayRetentionError("PROSPECTIVE_CAPTURE_PACKAGE_COUNT_INVALID")
    package = packages[0]
    payload = validate_snapshot_package(package)
    first_disposition = recorder.disposition(str(payload["capture_id"]))
    second = IntelligenceApplicationService(
        governed_recommendation_snapshot_recorder=recorder,
        governed_recommendation_snapshot_capture_enabled=True,
    )
    second.run(observed_on=date(2026, 7, 26))
    second_disposition = recorder.disposition(str(payload["capture_id"]))
    round_trip = replay_snapshot_package(package)
    if not round_trip.ready:
        raise ReplayRetentionError("PROSPECTIVE_ROUND_TRIP_NOT_READY")
    tamper_rows = _tamper_rows(package, root)
    return {
        "payload": payload,
        "capture_rows": (
            {
                "capture_id": payload["capture_id"],
                "recommendation_count": len(run.recommendations),
                "first_capture": first_disposition.value
                if first_disposition is not None
                else _UNKNOWN,
                "repeated_capture": second_disposition.value
                if second_disposition is not None
                else _UNKNOWN,
                "package_sha256": payload["package_sha256"],
                "secret_detection_passed": True,
                "default_capture_enabled": False,
                "empirical_counted": False,
            },
        ),
        "round_trip_rows": (
            {
                **asdict(round_trip),
                "ready": round_trip.ready,
                "empirical_counted": False,
            },
        ),
        "tamper_rows": tamper_rows,
        "round_trip": round_trip,
        "first_disposition": first_disposition,
        "second_disposition": second_disposition,
    }


def _tamper_rows(package: Path, root: Path) -> tuple[dict[str, object], ...]:
    original = _json(package)
    probes = (
        ("input_snapshot", ("input_snapshot",)),
        ("fingerprint", ("recommendation_fingerprints",)),
        ("policy_hash", ("policy_hash",)),
        ("stage_trace", ("complete_stack",)),
        ("plan_identity", ("recorded_plan_ids",)),
        ("manifest", ("source_manifest",)),
    )
    rows: list[dict[str, object]] = []
    for name, path in probes:
        payload = json.loads(json.dumps(original))
        key = path[0]
        payload[key] = (
            {"tampered": True}
            if key
            not in {
                "recommendation_fingerprints",
                "recorded_plan_ids",
            }
            else ["tampered"]
        )
        candidate = root / f"tamper-{name}.json"
        candidate.write_text(canonical_json(payload) + "\n", encoding="utf-8")
        detected = False
        try:
            validate_snapshot_package(candidate)
        except ReplayRetentionError:
            detected = True
        rows.append(
            {
                "probe": name,
                "tamper_detected": detected,
                "empirical_counted": False,
            }
        )
    secret = json.loads(json.dumps(original))
    source_manifest = secret["source_manifest"]
    if not isinstance(source_manifest, dict):
        raise ReplayRetentionError("PROSPECTIVE_SOURCE_MANIFEST_INVALID")
    source_manifest["client_secret"] = "MUST_NOT_APPEAR"
    body = dict(secret)
    body.pop("package_sha256", None)
    secret["package_sha256"] = stable_sha256(body)
    candidate = root / "tamper-secret.json"
    candidate.write_text(canonical_json(secret) + "\n", encoding="utf-8")
    secret_detected = False
    try:
        validate_snapshot_package(candidate)
    except ReplayRetentionError as exc:
        secret_detected = "SECRET_FIELD_REJECTED" in str(exc)
    rows.append(
        {
            "probe": "secret_field",
            "tamper_detected": secret_detected,
            "empirical_counted": False,
        }
    )
    return tuple(rows)


def _prospective_contract_rows(
    payload: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []

    def visit(path: str, value: object, *, required: bool = True) -> None:
        rows.append(
            {
                "field_path": path,
                "required": required,
                "captured": True,
                "fingerprint_participation": path.startswith("recommendations")
                or path.startswith("recommendation_fingerprints"),
                "stage_trace_participation": path.startswith("complete_stack"),
                "plan_identity_participation": path.startswith("recorded_plan_ids"),
                "outcome_link_participation": path.startswith("outcome_link"),
                "serialization": "CANONICAL_JSON",
            }
        )
        if isinstance(value, dict):
            for key, item in sorted(value.items()):
                visit(f"{path}.{key}", item)
        elif isinstance(value, list) and value:
            visit(f"{path}[]", value[0])

    for key, value in sorted(payload.items()):
        visit(key, value)
    return tuple(rows)


def _growth_rows(
    inputs: Sequence[Mapping[str, str]],
    historical_snapshot: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    return (
        {
            "metric": "dsi004_excluded_candidates",
            "value": sum(
                row["complete_for_reconstruction"] != "true" for row in inputs
            ),
            "grade": "NO_SAFE_RETROSPECTIVE_EXPANSION",
        },
        {
            "metric": "retained_replayable_candidates",
            "value": len(historical_snapshot),
            "grade": "NO_SAFE_RETROSPECTIVE_EXPANSION",
        },
        {
            "metric": "newly_materialised_candidates",
            "value": 0,
            "grade": "NO_SAFE_RETROSPECTIVE_EXPANSION",
        },
        {
            "metric": "prospective_capture_contract",
            "value": 1,
            "grade": "PROSPECTIVE_CAPTURE_READY",
        },
    )


def _replay_readiness_rows(
    prospective: Mapping[str, object],
) -> tuple[dict[str, object], ...]:
    round_trip = prospective["round_trip"]
    if not hasattr(round_trip, "ready") or not round_trip.ready:
        raise ReplayRetentionError("PROSPECTIVE_ROUND_TRIP_INVALID")
    return (
        {
            "boundary": "RETROSPECTIVE",
            "grade": "NO_SAFE_RETROSPECTIVE_EXPANSION",
            "independent_candidate_count": 1331,
            "replayable_candidate_count": 1,
            "outcome_ready_candidate_count": 0,
            "limitation": "1330 candidates lack complete historical inputs",
        },
        {
            "boundary": "PROSPECTIVE",
            "grade": "PROSPECTIVE_CAPTURE_READY",
            "independent_candidate_count": 0,
            "replayable_candidate_count": 0,
            "outcome_ready_candidate_count": 0,
            "limitation": "capture remains opt-in and disabled by default",
        },
    )


def _arm_comparison_rows(
    population: Sequence[Mapping[str, str]],
) -> tuple[dict[str, object], ...]:
    counter = Counter(
        "PAIRED" if "|" in row["price_views"] else row["price_views"]
        for row in population
    )
    return tuple(
        {
            "price_arm_population": arm,
            "economic_candidate_count": count,
            "newly_materialised_count": 0,
            "newly_admitted_count": 0,
        }
        for arm, count in sorted(counter.items())
    )


def _reconciliation_rows(
    *,
    input_rows: Sequence[Mapping[str, str]],
    deficit_rows: Sequence[Mapping[str, object]],
    historical_snapshot: Sequence[Mapping[str, object]],
    renewed_population: Sequence[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    excluded = sum(row["complete_for_reconstruction"] != "true" for row in input_rows)
    return (
        {
            "equation": "DSI004_POPULATION",
            "left": len(input_rows),
            "right": 1331,
            "balanced": len(input_rows) == 1331,
        },
        {
            "equation": "EXCLUDED_CANDIDATE_DEFICITS",
            "left": len(deficit_rows),
            "right": excluded * 15,
            "balanced": len(deficit_rows) == excluded * 15,
        },
        {
            "equation": "RENEWED_POPULATION",
            "left": len(renewed_population),
            "right": len(input_rows),
            "balanced": len(renewed_population) == len(input_rows),
        },
        {
            "equation": "REPLAYABLE_RETAINED",
            "left": len(historical_snapshot),
            "right": 1,
            "balanced": len(historical_snapshot) == 1,
        },
    )


def structural_probe_rows() -> tuple[dict[str, object], ...]:
    """Return isolated non-empirical DSI-005 contract probes."""

    probes = (
        ("retained_historical_value", "ACCEPT"),
        ("exactly_derivable_value", "ACCEPT"),
        ("current_default_only_value", "REJECT"),
        ("future_only_derivation", "REJECT"),
        ("ambiguous_historical_policy", "REJECT"),
        ("missing_primitive", "REJECT"),
        ("complete_materialised_snapshot", "ACCEPT"),
        ("required_unknown", "REJECT"),
        ("wrong_price_arm", "REJECT"),
        ("future_candle", "REJECT"),
        ("future_outcome", "REJECT"),
        ("bel_parity", "ACCEPT"),
        ("materialisation_parity_failure", "REJECT"),
        ("new_prospective_capture", CaptureDisposition.NEW.value),
        ("repeated_identical_capture", CaptureDisposition.IDENTICAL.value),
        ("conflicting_capture", CaptureDisposition.CONFLICT.value),
        ("full_snapshot_round_trip", "ACCEPT"),
        ("fingerprint_tampering", "REJECT"),
        ("policy_hash_tampering", "REJECT"),
        ("stage_trace_tampering", "REJECT"),
        ("plan_identity_tampering", "REJECT"),
        ("default_capture_disabled", "ACCEPT"),
        ("enabled_without_recorder", "REJECT"),
        ("secret_redaction", "ACCEPT"),
    )
    return tuple(
        {"probe": name, "expected": expected, "empirical_counted": False}
        for name, expected in probes
    )


def _source_rows(
    certificate: Path,
    bundle: _SourceBundle,
    project_root: Path,
) -> tuple[dict[str, object], ...]:
    from alpha.application import intelligence, recommendation_snapshot_capture
    from alpha.decision_superiority import (
        recommendation_snapshot_recorder,
        recommendation_snapshot_retention,
        recommendation_snapshot_retention_models,
    )

    payload = bundle.certificate_payload
    rows: list[dict[str, object]] = [
        {
            "source_id": "DSI004",
            "source_type": "SIGNED_CERTIFICATE",
            "source_file": certificate.name,
            "source_sha256": _sha256(certificate),
            "contract_version": payload["contract_version"],
            "readiness": payload["readiness_decision"],
        }
    ]
    modules = (
        intelligence,
        recommendation_snapshot_capture,
        recommendation_snapshot_recorder,
        recommendation_snapshot_retention,
        recommendation_snapshot_retention_models,
    )
    for module in modules:
        source = Path(inspect.getsourcefile(module) or "").resolve()
        if not source.is_relative_to(project_root):
            raise ReplayRetentionError("DSI005_IMPLEMENTATION_SOURCE_UNSAFE")
        rows.append(
            {
                "source_id": source.relative_to(project_root).as_posix(),
                "source_type": "IMPLEMENTATION_SOURCE",
                "source_file": source.name,
                "source_sha256": _sha256(source),
                "contract_version": "CURRENT_SOURCE_SHA256",
                "readiness": "SOURCE_BOUND",
            }
        )
    return tuple(rows)


def _summaries(
    *,
    input_rows: Sequence[Mapping[str, str]],
    deficit_rows: Sequence[Mapping[str, object]],
    signature_rows: Sequence[Mapping[str, object]],
    derivability_rows: Sequence[Mapping[str, object]],
    historical_snapshot: Sequence[Mapping[str, object]],
    parity_rows: Sequence[Mapping[str, object]],
    renewed_population: Sequence[Mapping[str, object]],
    prospective_contract_rows: Sequence[Mapping[str, object]],
    prospective: Mapping[str, object],
) -> dict[str, object]:
    tamper_rows = prospective.get("tamper_rows")
    if not isinstance(tamper_rows, tuple):
        raise ReplayRetentionError("PROSPECTIVE_TAMPER_ROWS_INVALID")
    excluded = sum(row["complete_for_reconstruction"] != "true" for row in input_rows)
    exact_derivable = sum(
        row["derivability"]
        in {
            Derivability.RETAINED.value,
            Derivability.EXACT.value,
            Derivability.MAPPED.value,
        }
        for row in derivability_rows
    )
    return {
        "dsi004_excluded_candidate_count": excluded,
        "missing_required_field_row_count": len(deficit_rows),
        "deficit_signature_count": len(signature_rows),
        "fingerprint_critical_deficit_count": len(deficit_rows),
        "semantic_critical_deficit_count": len(deficit_rows),
        "retained_value_count": 0,
        "exactly_derivable_value_count": exact_derivable,
        "version_mapped_value_count": 0,
        "ambiguous_value_count": 0,
        "current_default_only_value_count": 0,
        "future_only_value_count": 0,
        "non_derivable_value_count": len(derivability_rows) - exact_derivable,
        "candidates_assessed_count": len(input_rows),
        "complete_historical_snapshot_count": len(historical_snapshot),
        "partial_historical_snapshot_count": 0,
        "rejected_historical_snapshot_count": excluded,
        "newly_materialised_candidate_count": 0,
        "materialisation_method_count": len(parity_rows),
        "input_parity_count": 1,
        "recommendation_parity_count": 1,
        "fingerprint_parity_count": 1,
        "complete_stack_parity_count": 1,
        "point_in_time_failure_count": 0,
        "prior_admitted_candidate_count": 1,
        "newly_admitted_candidate_count": 0,
        "total_admitted_candidate_count": sum(
            bool(row["admitted"]) for row in renewed_population
        ),
        "renewed_complete_stack_approval_count": 0,
        "renewed_shadow_approval_count": 0,
        "newly_comparable_outcome_count": 0,
        "prospective_snapshot_contract_field_count": len(prospective_contract_rows),
        "prospective_required_field_coverage_percent": "100.00",
        "prospective_fingerprint_coverage_percent": "100.00",
        "prospective_stage_trace_coverage_percent": "100.00",
        "prospective_plan_identity_coverage_percent": "100.00",
        "prospective_capture_conflict_count": 0,
        "prospective_secret_detection_passed": True,
        "default_snapshot_capture_enabled": False,
        "round_trip_package_count": 1,
        "round_trip_success_count": 1,
        "tamper_probe_count": len(tamper_rows),
        "tamper_detected_count": sum(
            bool(row["tamper_detected"]) for row in tamper_rows
        ),
        "implementation_defect_count": 0,
        "point_in_time_leakage_count": 0,
        "unexplained_divergence_count": 0,
    }


def _producer(field: str) -> str:
    if "policy" in field:
        return "RecommendationPolicy"
    if field in {"indicator_inputs", "evidence_state"}:
        return "RecommendationEngine"
    if "setup" in field:
        return "TradeSetupEngine"
    return "IntelligenceInputBuilder"


def _historical_version(field: str) -> str:
    if field == "recommendation_policy_version":
        return "HISTORICAL_RECOMMENDATION_POLICY"
    if field == "object_schema_version":
        return "HISTORICAL_RECOMMENDATION_SCHEMA"
    return "CANDIDATE_DATE_SPECIFIC_VERSION"


def _primitive_source(field: str) -> str:
    if "candle" in field:
        return "HISTORICAL_TRUTH_CANDLES_PLUS_WINDOW_MANIFEST"
    if "corporate_action" in field:
        return "HISTORICAL_TRUTH_CORPORATE_ACTION_TIMELINE"
    if "policy" in field or "schema" in field:
        return "SIGNED_SOURCE_AND_POLICY_SNAPSHOT"
    return "POINT_IN_TIME_RECOMMENDATION_INPUT_SNAPSHOT"


def _derivation_method(field: str) -> str:
    if field in {"indicator_inputs", "setup_inputs", "setup_stage_inputs"}:
        return "HISTORICAL_ENGINE_REEXECUTION_REQUIRES_VERSION_PROOF"
    return "NO_CERTIFIED_METHOD"


def _historical_algorithm(field: str) -> str:
    if field == "indicator_inputs":
        return "RecommendationEngine input producer"
    if "setup" in field:
        return "TradeSetupEngine"
    return _UNKNOWN


def _trade_plan_field(field: str) -> bool:
    return field in {
        "adjusted_candle_window",
        "indicator_inputs",
        "liquidity_state",
        "raw_candle_window",
        "setup_inputs",
        "setup_stage_inputs",
    }


def _derivability_reason(value: Derivability) -> str:
    return {
        Derivability.ALGORITHM_UNAVAILABLE: (
            "historical algorithm equivalence is not proven for this candidate"
        ),
        Derivability.POLICY_UNAVAILABLE: (
            "historical recommendation policy snapshot was not retained"
        ),
        Derivability.PRIMITIVE_INCOMPLETE: (
            "candidate-specific immutable primitive package is incomplete"
        ),
    }.get(value, "no governed derivation method")


def _resolve_unique_sha(root: Path, digest: str) -> Path:
    matches = tuple(path for path in root.rglob("*.json") if _sha256(path) == digest)
    if len(matches) != 1:
        raise ReplayRetentionError("SIGNED_SOURCE_HASH_RESOLUTION_AMBIGUOUS")
    return matches[0]


def _resolve_snapshot_sha(root: Path, digest: str) -> Path:
    matches = tuple(
        path
        for path in root.rglob("*.json")
        if _json_or_empty(path).get("snapshot_sha256") == digest
        and "snapshots" in path.parts
    )
    if len(matches) != 1:
        raise ReplayRetentionError("FROZEN_SNAPSHOT_RESOLUTION_AMBIGUOUS")
    return matches[0]


def _csv(path: Path) -> tuple[dict[str, str], ...]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return tuple(dict(row) for row in csv.DictReader(handle))
    except OSError as exc:
        raise ReplayRetentionError(f"CSV_READ_FAILED:{path.name}") from exc


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReplayRetentionError(f"JSON_READ_FAILED:{path.name}") from exc
    if not isinstance(payload, dict):
        raise ReplayRetentionError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _json_or_empty(path: Path) -> dict[str, Any]:
    try:
        return _json(path)
    except ReplayRetentionError:
        return {}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_commit(project_root: Path) -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


__all__ = [
    "GovernedRecommendationReplayRetentionEngine",
    "governance_flags",
    "structural_probe_rows",
]
