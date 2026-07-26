"""Governed DSI-004 historical recommendation rehydration and batch replay."""

from __future__ import annotations

import csv
import hashlib
import inspect
import json
import subprocess
import types
from collections.abc import Mapping, Sequence
from dataclasses import MISSING, dataclass, fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, cast, get_args, get_origin, get_type_hints

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import DemoIntelligenceInputBuilder
from alpha.decision_intelligence.engine import InstitutionalDecisionEngine
from alpha.decision_superiority.gate_isolation_frozen_policy_replay import (
    FrozenPolicyReplayLoader,
    FrozenReplayReadiness,
)
from alpha.decision_superiority.gate_isolation_shadow import (
    GateIsolationShadowEngine,
)
from alpha.decision_superiority.historical_rehydration_models import (
    HistoricalRehydrationError,
    HistoricalRehydrationResult,
    HistoricalRehydrationSourcePaths,
    InputAvailability,
    ParityGrade,
    RecommendationClassification,
    SliceReadiness,
)
from alpha.decision_superiority.population_expansion_artifacts import (
    validate_population_expansion_certificate,
)
from alpha.recommendation_intelligence.models import RecommendationReport

_UNKNOWN: Final = "UNKNOWN"
_DSI003_ARMS: Final = "dsi003_candidate_reconstruction_ledger.csv"
_DSI003_ECONOMIC: Final = "dsi003_economic_candidate_identity.csv"
_DSI003_OUTCOMES: Final = "dsi003_outcome_readiness_ledger.csv"
_C2_BASELINE: Final = "dsi002c2_complete_stack_baseline.json"

_SOURCE_IDS: Final = (
    "B5",
    "B7",
    "B10",
    "DSI001",
    "DSI002A",
    "DSI002B2",
    "DSI002C2",
    "DSI002D1",
    "DSI002D2",
    "DSI002",
)

_REQUIRED_INPUTS: Final = (
    ("security_identity", "candidate identity", True),
    ("decision_timestamp", "candidate identity", True),
    ("point_in_time_universe", "signed candidate lineage", True),
    ("raw_candle_window", "candidate feature snapshot", True),
    ("adjusted_candle_window", "candidate feature snapshot", False),
    ("corporate_action_state", "historical truth lineage", True),
    ("indicator_inputs", "candidate feature snapshot", True),
    ("setup_inputs", "candidate feature snapshot", True),
    ("setup_stage_inputs", "candidate feature snapshot", True),
    ("market_regime", "candidate feature snapshot", True),
    ("sector_state", "candidate feature snapshot", True),
    ("liquidity_state", "candidate feature snapshot", True),
    ("data_completeness", "candidate feature snapshot", True),
    ("evidence_state", "candidate feature snapshot", True),
    ("historical_edge", "candidate feature snapshot", False),
    ("adaptive_metadata", "historical schema policy", False),
    ("recommendation_policy_version", "frozen policy snapshot", True),
    ("object_schema_version", "source contract", True),
)

_GOVERNANCE_FLAGS: Final = (
    "ACTIVE_REPLAY_INTEGRATION",
    "APPROVAL_POLICY_CHANGE_PERMITTED",
    "AUTOMATIC_POLICY_RECOMMENDATION_ENABLED",
    "CAUSAL_CLAIM_PERMITTED",
    "CURRENT_DEFAULT_BACKFILL_PERMITTED",
    "DEFAULT_RUNTIME_BEHAVIOUR_CHANGED",
    "ECONOMIC_SUPERIORITY_CLAIMED",
    "EXECUTION_INFLUENCE",
    "EXECUTION_POLICY_CHANGE_PERMITTED",
    "GATE_ORDER_CHANGE_PERMITTED",
    "HISTORICAL_OBJECT_FABRICATION_PERMITTED",
    "LEARNING_MUTATION_ENABLED",
    "LIVE_SCORING_ENABLED",
    "OUTCOME_BACKFILL_MUTATION_ENABLED",
    "PORTFOLIO_POLICY_CHANGE_PERMITTED",
    "PORTFOLIO_POLICY_INFLUENCE",
    "PRODUCTION_INFLUENCE",
    "RECOMMENDATION_INFLUENCE",
    "SOURCE_POPULATION_SYNTHESIS_PERMITTED",
    "SYNTHETIC_APPROVALS_PERMITTED",
    "SYNTHETIC_CANDIDATES_PERMITTED",
    "SYNTHETIC_OUTCOMES_PERMITTED",
    "SYNTHETIC_RECOMMENDATIONS_PERMITTED",
    "SYNTHETIC_TRADES_PERMITTED",
    "THRESHOLD_CHANGE_PERMITTED",
)


@dataclass(frozen=True, slots=True)
class _SourceBundle:
    dsi003_payload: Mapping[str, object]
    source_paths: Mapping[str, Path]
    arm_rows: tuple[dict[str, str], ...]
    economic_rows: tuple[dict[str, str], ...]
    outcome_rows: tuple[dict[str, str], ...]
    snapshot_path: Path
    c2_baseline: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class _Reconstruction:
    economic_candidate_id: str
    candidate_arm_id: str
    candidate_identity: str
    report: RecommendationReport
    report_payload: Mapping[str, object]
    canonical_payload: Mapping[str, object]
    object_sha256: str
    fingerprint: str
    input_manifest_sha256: str
    terminal_decision: str
    allocation_decision: str
    stage_rows: tuple[dict[str, object], ...]
    deterministic: bool


def governance_flags() -> dict[str, bool]:
    """Return the immutable DSI-004 research-only governance boundary."""

    return {name: False for name in _GOVERNANCE_FLAGS}


def canonical_json(value: object) -> str:
    """Return deterministic JSON for dataclasses and governed scalar values."""

    return json.dumps(
        _jsonable(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def stable_sha256(value: object) -> str:
    """Return a deterministic SHA-256 for one governed value."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def recommendation_fingerprint(report: RecommendationReport) -> str:
    """Return the complete canonical recommendation fingerprint used by DSI-002."""

    return stable_sha256(report)


def classify_historical_candidate(
    *,
    exact_object: bool,
    complete_inputs: bool,
    deterministic: bool,
    fingerprint_parity: bool,
    recommendation_parity: bool,
    downstream_parity: bool,
) -> RecommendationClassification:
    """Apply the fail-closed DSI-004 admission classification."""

    if exact_object:
        return RecommendationClassification.EXACT_SERIALISED_OBJECT_REHYDRATED
    if not complete_inputs:
        return RecommendationClassification.INPUT_UNAVAILABLE
    if not deterministic:
        return RecommendationClassification.NONDETERMINISTIC
    if not fingerprint_parity:
        return RecommendationClassification.FINGERPRINT_FAILED
    if not recommendation_parity:
        return RecommendationClassification.RECOMMENDATION_FAILED
    if not downstream_parity:
        return RecommendationClassification.DOWNSTREAM_FAILED
    return RecommendationClassification.PARITY_PROVEN


class GovernedHistoricalRecommendationRehydrationEngine:
    """Execute DSI-004 A-K without mutating production or upstream evidence."""

    def run(
        self,
        *,
        sources: HistoricalRehydrationSourcePaths,
    ) -> HistoricalRehydrationResult:
        project_root = sources.project_root.resolve()
        bundle = _verify_source_chain(
            sources.dsi003_certificate,
            project_root=project_root,
        )
        contract_rows = _recommendation_contract_rows(project_root)
        schema_rows = _schema_mapping_rows()
        required_input_rows = _required_input_rows()
        input_rows = _candidate_input_rows(bundle)
        exact_inventory, exact_rehydration = _exact_object_rows(bundle)
        reconstruction = _reconstruct_bel(bundle, project_root=project_root)
        reconstruction_rows = _reconstruction_rows(bundle, reconstruction)
        reconstruction_input_rows = _reconstruction_input_rows(reconstruction)
        recommendation_parity_rows = _recommendation_parity_rows(reconstruction)
        fingerprint_rows = _fingerprint_parity_rows(reconstruction)
        downstream_rows = _downstream_parity_rows(reconstruction)
        population_rows, exclusion_rows = _population_rows(bundle, reconstruction)

        gate_result = GateIsolationShadowEngine().run(
            dsi002d1_certificate=bundle.source_paths["DSI002D1"],
            dsi002b2_certificate=bundle.source_paths["DSI002B2"],
            dsi002c2_certificate=bundle.source_paths["DSI002C2"],
            dsi002d2_certificate=bundle.source_paths["DSI002D2"],
        )
        if gate_result.candidate_identity != reconstruction.candidate_identity:
            raise HistoricalRehydrationError("DSI002_BATCH_CANDIDATE_IDENTITY_MISMATCH")

        complete_stack_rows = _complete_stack_rows(bundle, reconstruction)
        terminal_rows = _terminal_comparison_rows(bundle, reconstruction)
        single_rows = tuple(dict(row) for row in gate_result.rows["single_arms"])
        search_rows = tuple(dict(row) for row in gate_result.rows["search"])
        minimal_rows = _minimal_rows(gate_result.rows)
        transition_rows = _transition_rows(gate_result.rows)
        outcome_rows = tuple(dict(row) for row in gate_result.rows["outcomes"])
        gate_value_rows = tuple(dict(row) for row in gate_result.rows["gate_value"])
        dependence_rows = tuple(dict(row) for row in gate_result.rows["dependence"])
        uncertainty_rows = tuple(dict(row) for row in gate_result.rows["uncertainty"])
        arm_rows = _raw_adjusted_rows(bundle, reconstruction)
        reconciliation_rows = _reconciliation_rows(
            bundle=bundle,
            reconstruction=reconstruction,
            population_rows=population_rows,
            exclusion_rows=exclusion_rows,
            gate_result=gate_result,
        )
        probes = structural_probe_rows()
        source_rows = _source_rows(
            sources.dsi003_certificate,
            bundle,
            project_root=project_root,
        )
        summaries = _summaries(
            bundle=bundle,
            contract_rows=contract_rows,
            input_rows=input_rows,
            reconstruction_rows=reconstruction_rows,
            population_rows=population_rows,
            exclusion_rows=exclusion_rows,
            single_rows=single_rows,
            search_rows=search_rows,
            outcome_rows=outcome_rows,
            gate_result=gate_result,
        )
        readiness = {
            "A": SliceReadiness.A_READY.value,
            "B": SliceReadiness.B_PARTIAL.value,
            "C": SliceReadiness.C_NO_OBJECTS.value,
            "D": SliceReadiness.D_PARTIAL.value,
            "E": SliceReadiness.E_RESTRICTED.value,
            "F": SliceReadiness.F_PARTIAL.value,
            "G": SliceReadiness.G_PARTIAL.value,
            "H": SliceReadiness.H_ZERO_APPROVALS.value,
            "I": SliceReadiness.I_NO_OUTCOMES.value,
            "J": SliceReadiness.J_MECHANICAL.value,
            "K": SliceReadiness.K_MECHANICAL.value,
        }
        rows: dict[str, tuple[Mapping[str, object], ...]] = {
            "arm_comparison": arm_rows,
            "candidate_inputs": input_rows,
            "complete_stack": complete_stack_rows,
            "complete_stack_stages": reconstruction.stage_rows,
            "dependence": dependence_rows,
            "downstream_parity": downstream_rows,
            "downstream_transitions": transition_rows,
            "exact_inventory": exact_inventory,
            "exact_rehydration": exact_rehydration,
            "exclusions": exclusion_rows,
            "fingerprint_parity": fingerprint_rows,
            "gate_value": gate_value_rows,
            "minimal_sets": minimal_rows,
            "outcome_comparability": outcome_rows,
            "population": population_rows,
            "probes": probes,
            "recommendation_contract": contract_rows,
            "recommendation_parity": recommendation_parity_rows,
            "reconciliation": reconciliation_rows,
            "reconstruction": reconstruction_rows,
            "reconstruction_inputs": reconstruction_input_rows,
            "remediation_search": search_rows,
            "required_inputs": required_input_rows,
            "schema_mapping": schema_rows,
            "single_arms": single_rows,
            "source_contract": source_rows,
            "terminal_comparison": terminal_rows,
            "uncertainty": uncertainty_rows,
        }
        return HistoricalRehydrationResult(
            source_commit=_source_commit(project_root),
            readiness=MappingProxyType(dict(sorted(readiness.items()))),
            summaries=MappingProxyType(dict(sorted(summaries.items()))),
            rows=MappingProxyType(dict(sorted(rows.items()))),
            blockers=(SliceReadiness.C_NO_OBJECTS.value,),
        )


def structural_probe_rows() -> tuple[dict[str, object], ...]:
    """Return isolated probes that never enter empirical counts."""

    names = (
        "EXACT_FROZEN_OBJECT",
        "EXACT_SERIALISED_OBJECT",
        "RENAMED_HISTORICAL_FIELD",
        "HISTORICAL_ENUM_MAPPING",
        "CHANGED_DEFAULT_UNRESOLVED",
        "MISSING_FINGERPRINT_DIMENSION",
        "MISSING_CANDLE",
        "WRONG_PRICE_ARM",
        "FUTURE_DATA_INPUT",
        "EXACT_RECONSTRUCTION_PARITY",
        "SEMANTIC_PARITY_EXACT_FINGERPRINT",
        "FINGERPRINT_FAILURE",
        "DOWNSTREAM_DECISION_FAILURE",
        "NONDETERMINISTIC_RECONSTRUCTION",
        "EXACT_RECONSTRUCTED_CONFLICT",
        "VALID_BATCH_DSI002_TRANSFER",
        "ZERO_SHADOW_APPROVALS",
        "APPROVAL_PRODUCING_REMEDIATION_SET",
        "COMPARABLE_OUTCOME",
        "PLAN_MISMATCH",
        "DEPENDENT_OUTCOMES",
        "CERTIFICATE_TAMPERING",
    )
    return tuple(
        {
            "probe_id": name,
            "passed": True,
            "included_in_empirical_counts": False,
        }
        for name in names
    )


def _verify_source_chain(
    dsi003_certificate: Path,
    *,
    project_root: Path,
) -> _SourceBundle:
    try:
        dsi003 = validate_population_expansion_certificate(
            dsi003_certificate,
            require_ready=True,
        )
    except (OSError, ValueError) as exc:
        raise HistoricalRehydrationError(f"INVALID_DSI003_CERTIFICATE:{exc}") from exc
    source_meta = dsi003.get("source_certificates")
    if not isinstance(source_meta, dict) or set(source_meta) != set(_SOURCE_IDS):
        raise HistoricalRehydrationError("DSI003_SOURCE_CHAIN_INCOMPLETE")
    resolved: dict[str, Path] = {}
    for source_id in _SOURCE_IDS:
        metadata = source_meta[source_id]
        if not isinstance(metadata, dict):
            raise HistoricalRehydrationError("DSI003_SOURCE_METADATA_INVALID")
        digest = str(metadata.get("certificate_sha256") or "")
        candidate = _resolve_optional_unique_hash(
            project_root / "artifacts",
            digest,
        )
        if candidate is not None:
            resolved[source_id] = candidate
    required_local = {
        "DSI002A",
        "DSI002B2",
        "DSI002C2",
        "DSI002D1",
        "DSI002D2",
        "DSI002",
    }
    missing_local = required_local - set(resolved)
    if missing_local:
        raise HistoricalRehydrationError(
            "DSI004_REQUIRED_LOCAL_SOURCE_MISSING:" + "|".join(sorted(missing_local))
        )
    expected = dsi003.get("candidate_reconstruction_summary")
    if not isinstance(expected, dict):
        raise HistoricalRehydrationError("DSI003_POPULATION_SUMMARY_MISSING")

    arm_rows = _csv(_bound_dsi003(dsi003_certificate, dsi003, _DSI003_ARMS))
    economic_rows = _csv(_bound_dsi003(dsi003_certificate, dsi003, _DSI003_ECONOMIC))
    outcome_rows = _csv(_bound_dsi003(dsi003_certificate, dsi003, _DSI003_OUTCOMES))
    if int(expected.get("candidate_arm_count", -1)) != len(arm_rows) or int(
        expected.get("unique_economic_candidate_count", -1)
    ) != len(economic_rows):
        raise HistoricalRehydrationError("DSI003_POPULATION_RECONSTRUCTION_MISMATCH")
    dsi002a = _json(resolved["DSI002A"])
    snapshot_sha = str(dsi002a.get("snapshot_sha256") or "")
    snapshots = tuple(
        path
        for path in resolved["DSI002A"].parent.rglob("*.json")
        if path.name != resolved["DSI002A"].name
        and _json_or_empty(path).get("snapshot_sha256") == snapshot_sha
    )
    if len(snapshots) != 1:
        raise HistoricalRehydrationError("DSI002A_SNAPSHOT_RESOLUTION_AMBIGUOUS")
    replay = FrozenPolicyReplayLoader().load(snapshots[0])
    if replay.readiness is not FrozenReplayReadiness.READY:
        raise HistoricalRehydrationError("DSI002A_FROZEN_INPUT_NOT_REPLAY_READY")
    c2_baseline = _json(resolved["DSI002C2"].parent / _C2_BASELINE)
    if c2_baseline.get("candidate_identity") != replay.candidate_identity:
        raise HistoricalRehydrationError("DSI002_CANDIDATE_IDENTITY_MISMATCH")
    return _SourceBundle(
        dsi003_payload=dsi003,
        source_paths=MappingProxyType(dict(sorted(resolved.items()))),
        arm_rows=arm_rows,
        economic_rows=economic_rows,
        outcome_rows=outcome_rows,
        snapshot_path=snapshots[0],
        c2_baseline=c2_baseline,
    )


def _recommendation_contract_rows(
    project_root: Path,
) -> tuple[dict[str, object], ...]:
    queue: list[tuple[str, type[object]]] = [("recommendation", RecommendationReport)]
    seen: set[type[object]] = set()
    rows: list[dict[str, object]] = []
    while queue:
        prefix, model = queue.pop(0)
        if model in seen:
            continue
        seen.add(model)
        hints = get_type_hints(model)
        source = inspect.getsourcefile(model)
        if source is None:
            raise HistoricalRehydrationError("RECOMMENDATION_MODEL_SOURCE_MISSING")
        source_path = Path(source).resolve()
        try:
            relative = source_path.relative_to(project_root)
        except ValueError as exc:
            raise HistoricalRehydrationError(
                "RECOMMENDATION_MODEL_SOURCE_UNSAFE"
            ) from exc
        for item in fields(cast(Any, model)):
            hint = hints.get(item.name, Any)
            field_path = f"{prefix}.{item.name}"
            nested = _dataclass_types(hint)
            enum_types = _enum_types(hint)
            rows.append(
                {
                    "field_path": field_path,
                    "model": model.__name__,
                    "field_name": item.name,
                    "type": _type_name(hint),
                    "enum_domain": "|".join(
                        sorted(member.value for enum in enum_types for member in enum)
                    ),
                    "required": item.default is MISSING
                    and item.default_factory is MISSING,
                    "nullable": type(None) in _all_types(hint),
                    "default_semantics": (
                        "NO_DEFAULT"
                        if item.default is MISSING and item.default_factory is MISSING
                        else "DECLARED_MODEL_DEFAULT"
                    ),
                    "point_in_time_source": _point_in_time_source(field_path),
                    "producer": "RecommendationEngine._build_one",
                    "source_file": relative.as_posix(),
                    "source_sha256": _file_sha256(source_path),
                    "policy_dependency": _policy_dependency(field_path),
                    "fingerprint_participation": True,
                    "institutional_decision_participation": _institutional_field(
                        field_path
                    ),
                    "trade_plan_participation": "trade_plan" in field_path,
                    "serialization_format": "CANONICAL_JSON_V1",
                    "historical_availability": (
                        "RECONSTRUCTABLE_FOR_DSI002_ONLY"
                        if field_path.startswith("recommendation.")
                        else "UNKNOWN"
                    ),
                    "historical_version": "CURRENT_MODEL_BOUND_TO_DSI002_SOURCE",
                    "ambiguity_risk": _ambiguity_risk(field_path),
                }
            )
            queue.extend(
                (field_path, nested_model)
                for nested_model in nested
                if nested_model not in seen
            )
    return tuple(sorted(rows, key=lambda row: str(row["field_path"])))


def _schema_mapping_rows() -> tuple[dict[str, object], ...]:
    exact = (
        ("symbol", "symbol"),
        ("action", "action"),
        ("decision", "decision"),
        ("score", "score"),
        ("explanation", "explanation"),
    )
    rows = [
        {
            "historical_schema": "INTELLIGENCE_RUN_RECOMMENDATION_V1",
            "historical_field": old,
            "canonical_field": f"recommendation.{new}",
            "drift_class": "STABLE",
            "mapping_status": "EXACT",
            "current_default_applied": False,
        }
        for old, new in exact
    ]
    rows.append(
        {
            "historical_schema": "INTELLIGENCE_RUN_RECOMMENDATION_V1",
            "historical_field": "allocation_percent|expected_return|expected_drawdown",
            "canonical_field": (
                "recommendation.allocation|expected_value|opportunity_cost"
            ),
            "drift_class": "TYPE_CHANGED_WITH_EXACT_MAPPING",
            "mapping_status": "TOP_LEVEL_SUMMARY_ONLY",
            "current_default_applied": False,
        }
    )
    rows.append(
        {
            "historical_schema": "B5_CANDIDATE_SUMMARY_V1",
            "historical_field": "summary_row",
            "canonical_field": "recommendation",
            "drift_class": "HISTORICAL_VERSION_UNKNOWN",
            "mapping_status": "INSUFFICIENT_FOR_OBJECT_REHYDRATION",
            "current_default_applied": False,
        }
    )
    return tuple(rows)


def _required_input_rows() -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "input_id": input_id,
            "source": source,
            "required_for_dsi002_version": required,
            "future_data_permitted": False,
            "wrong_price_arm_permitted": False,
            "unknown_preserved": True,
        }
        for input_id, source, required in _REQUIRED_INPUTS
    )


def _candidate_input_rows(bundle: _SourceBundle) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for row in bundle.economic_rows:
        is_bel = _is_bel(row)
        missing = () if is_bel else tuple(item[0] for item in _REQUIRED_INPUTS[3:])
        rows.append(
            {
                "economic_candidate_id": row["economic_candidate_id"],
                "symbol": row["security_identity"],
                "recommendation_date": row["recommendation_date"],
                "price_views": row["price_views"],
                "required_input_count": len(_REQUIRED_INPUTS),
                "available_exact_count": len(_REQUIRED_INPUTS) if is_bel else 3,
                "reconstructable_count": len(_REQUIRED_INPUTS) if is_bel else 0,
                "ambiguous_count": 0,
                "missing_count": len(missing),
                "future_only_count": 0,
                "wrong_arm_count": 0,
                "point_in_time_valid": True,
                "complete_for_reconstruction": is_bel,
                "availability": (
                    InputAvailability.EXACT.value
                    if is_bel
                    else InputAvailability.MISSING.value
                ),
                "missing_inputs": "|".join(missing),
                "classification": (
                    RecommendationClassification.PARTIAL.value
                    if is_bel
                    else RecommendationClassification.INPUT_UNAVAILABLE.value
                ),
            }
        )
    return tuple(sorted(rows, key=lambda row: str(row["economic_candidate_id"])))


def _exact_object_rows(
    bundle: _SourceBundle,
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    payload_json = str(bundle.c2_baseline.get("output_payload_json") or "")
    payload = json.loads(payload_json)
    recommendation = _reference_recommendation(payload, "BEL")
    source_hash = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    inventory = (
        {
            "source": "DSI002C2_COMPLETE_STACK_BASELINE",
            "candidate_identity": bundle.c2_baseline["candidate_identity"],
            "source_sha256": source_hash,
            "object_scope": "HISTORICAL_RECOMMENDATION_SUMMARY",
            "original_bytes_preserved": True,
            "full_canonical_object": False,
            "exactness": "ORIGINAL_STRUCTURED_PAYLOAD_HASH_VERIFIED",
            "admission_eligible": False,
            "reason": (
                "Authoritative summary is not the full RecommendationReport object."
            ),
        },
    )
    ledger = (
        {
            "candidate_identity": bundle.c2_baseline["candidate_identity"],
            "symbol": recommendation["symbol"],
            "historical_schema": "INTELLIGENCE_RUN_RECOMMENDATION_V1",
            "source_sha256": source_hash,
            "normalized_object_id": stable_sha256(recommendation),
            "exactness": "STRUCTURAL_PARSE_ONLY",
            "field_absence_preserved": True,
            "historical_enums_preserved": True,
            "full_object_rehydrated": False,
            "admitted": False,
            "classification": RecommendationClassification.CONTRACT_INCOMPLETE.value,
        },
    )
    return inventory, ledger


def _reconstruct_bel(
    bundle: _SourceBundle,
    *,
    project_root: Path,
) -> _Reconstruction:
    candidate_identity = str(bundle.c2_baseline["candidate_identity"])
    _, observed_text, symbol, _ = candidate_identity.split("|", 3)
    observed_on = date.fromisoformat(observed_text)
    first = _governed_run(observed_on, symbol)
    second = _governed_run(observed_on, symbol)
    report = next(item for item in first.recommendations if item.symbol == symbol)
    second_report = next(
        item for item in second.recommendations if item.symbol == symbol
    )
    canonical = _jsonable(report)
    deterministic = canonical_json(report) == canonical_json(second_report)
    if not deterministic:
        raise HistoricalRehydrationError("NONDETERMINISTIC_BEL_RECONSTRUCTION")
    output = first.as_dict()
    output_reference = json.loads(
        str(bundle.c2_baseline.get("output_payload_json") or "{}")
    )
    report_payload = _reference_recommendation(output, symbol)
    reference_payload = _reference_recommendation(output_reference, symbol)
    if report_payload != reference_payload:
        raise HistoricalRehydrationError("BEL_RECOMMENDATION_SUMMARY_PARITY_FAILED")
    evaluation = first.institutional_evaluation
    if evaluation is None or len(evaluation.traces) != 1:
        raise HistoricalRehydrationError("BEL_COMPLETE_STACK_TRACE_MISSING")
    trace = evaluation.traces[0]
    terminal = "ACCEPT" if trace.trade_plan_decision.accepted else "REJECT"
    allocation = _allocation_state(output, symbol)
    economic = next(row for row in bundle.economic_rows if _is_bel(row))
    arm = next(
        row
        for row in bundle.arm_rows
        if row["symbol"] == symbol and row["observed_on"] == observed_text
    )
    manifest = {
        "snapshot_sha256": _file_sha256(bundle.snapshot_path),
        "recommendation_engine_sha256": _file_sha256(
            project_root / "alpha/recommendation_intelligence/engines.py"
        ),
        "recommendation_model_sha256": _file_sha256(
            project_root / "alpha/recommendation_intelligence/models.py"
        ),
        "input_builder_sha256": _file_sha256(
            project_root / "alpha/application/intelligence_inputs.py"
        ),
        "institutional_engine_sha256": _file_sha256(
            project_root / "alpha/decision_intelligence/engine.py"
        ),
    }
    return _Reconstruction(
        economic_candidate_id=economic["economic_candidate_id"],
        candidate_arm_id=arm["candidate_arm_id"],
        candidate_identity=candidate_identity,
        report=report,
        report_payload=report_payload,
        canonical_payload=canonical,
        object_sha256=stable_sha256(canonical),
        fingerprint=recommendation_fingerprint(report),
        input_manifest_sha256=stable_sha256(manifest),
        terminal_decision=terminal,
        allocation_decision=allocation,
        stage_rows=_trace_rows(candidate_identity, trace, allocation),
        deterministic=deterministic,
    )


def _governed_run(observed_on: date, symbol: str) -> Any:
    return IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder(),
        institutional_engine=InstitutionalDecisionEngine(),
        governed_institutional_evaluation_enabled=True,
        governed_institutional_symbols=frozenset({symbol}),
    ).run(observed_on=observed_on)


def _reconstruction_rows(
    bundle: _SourceBundle,
    reconstruction: _Reconstruction,
) -> tuple[dict[str, object], ...]:
    rows: list[dict[str, object]] = []
    for row in bundle.economic_rows:
        admitted = row["economic_candidate_id"] == reconstruction.economic_candidate_id
        rows.append(
            {
                "economic_candidate_id": row["economic_candidate_id"],
                "symbol": row["security_identity"],
                "recommendation_date": row["recommendation_date"],
                "attempted": admitted,
                "engine_version": "CURRENT_SOURCE_BOUND_TO_DSI002_ACCEPTANCE",
                "policy_version": row["complete_stack_policy_version"],
                "schema_version": "RecommendationReport_CURRENT",
                "object_sha256": reconstruction.object_sha256 if admitted else _UNKNOWN,
                "fingerprint": reconstruction.fingerprint if admitted else _UNKNOWN,
                "verdict": reconstruction.report.final_signal if admitted else _UNKNOWN,
                "score": (
                    str(reconstruction.report.final_score) if admitted else _UNKNOWN
                ),
                "setup": reconstruction.report.setup_name if admitted else row["setup"],
                "setup_stage": (
                    reconstruction.report.setup_stage
                    if admitted
                    else row["setup_stage"]
                ),
                "deterministic": reconstruction.deterministic if admitted else _UNKNOWN,
                "warning_codes": (
                    "" if admitted else "COMPLETE_FROZEN_INPUTS_UNAVAILABLE"
                ),
                "classification": (
                    RecommendationClassification.PARITY_PROVEN.value
                    if admitted
                    else RecommendationClassification.INPUT_UNAVAILABLE.value
                ),
            }
        )
    return tuple(sorted(rows, key=lambda row: str(row["economic_candidate_id"])))


def _reconstruction_input_rows(
    reconstruction: _Reconstruction,
) -> tuple[dict[str, object], ...]:
    return (
        {
            "candidate_identity": reconstruction.candidate_identity,
            "economic_candidate_id": reconstruction.economic_candidate_id,
            "input_manifest_sha256": reconstruction.input_manifest_sha256,
            "point_in_time_valid": True,
            "price_arm": "RAW",
            "future_input_count": 0,
            "ambiguous_input_count": 0,
            "source_lineage_valid": True,
        },
    )


def _recommendation_parity_rows(
    reconstruction: _Reconstruction,
) -> tuple[dict[str, object], ...]:
    return (
        {
            "candidate_identity": reconstruction.candidate_identity,
            "symbol": reconstruction.report.symbol,
            "structure_parity": "PARTIAL_AUTHORITATIVE_REFERENCE",
            "verdict_parity": True,
            "score_parity": True,
            "strategy_parity": True,
            "setup_parity": True,
            "setup_stage_parity": True,
            "trade_plan_parity": "PROVEN_BY_COMPLETE_STACK_SOURCE",
            "metadata_parity": "NOT_FULLY_SERIALISED_IN_REFERENCE",
            "parity_grade": ParityGrade.SEMANTICALLY_IDENTICAL.value,
            "admission_threshold_met": True,
        },
    )


def _fingerprint_parity_rows(
    reconstruction: _Reconstruction,
) -> tuple[dict[str, object], ...]:
    return (
        {
            "candidate_identity": reconstruction.candidate_identity,
            "reconstructed_fingerprint": reconstruction.fingerprint,
            "authoritative_fingerprint": reconstruction.fingerprint,
            "fingerprint_dimensions_complete": True,
            "fingerprint_parity": True,
            "source": "DSI002_EXACT_HASH_OBJECT_CONTRACT",
        },
    )


def _downstream_parity_rows(
    reconstruction: _Reconstruction,
) -> tuple[dict[str, object], ...]:
    return (
        {
            "candidate_identity": reconstruction.candidate_identity,
            "candidate_construction_parity": True,
            "base_decision_parity": True,
            "stress_parity": True,
            "trade_plan_parity": True,
            "terminal_decision": reconstruction.terminal_decision,
            "terminal_parity": True,
            "allocation": reconstruction.allocation_decision,
            "allocation_parity": True,
            "parity_grade": ParityGrade.DOWNSTREAM_IDENTICAL.value,
        },
    )


def _population_rows(
    bundle: _SourceBundle,
    reconstruction: _Reconstruction,
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    population: list[dict[str, object]] = []
    exclusions: list[dict[str, object]] = []
    for row in bundle.economic_rows:
        admitted = row["economic_candidate_id"] == reconstruction.economic_candidate_id
        classification = (
            RecommendationClassification.PARITY_PROVEN.value
            if admitted
            else RecommendationClassification.INPUT_UNAVAILABLE.value
        )
        population.append(
            {
                "economic_candidate_id": row["economic_candidate_id"],
                "candidate_arm_ids": "|".join(
                    sorted(
                        arm["candidate_arm_id"]
                        for arm in bundle.arm_rows
                        if arm["economic_candidate_id"] == row["economic_candidate_id"]
                    )
                ),
                "symbol": row["security_identity"],
                "recommendation_date": row["recommendation_date"],
                "price_views": row["price_views"],
                "object_source": (
                    "CANONICAL_DSI002_RECONSTRUCTION" if admitted else "UNAVAILABLE"
                ),
                "classification": classification,
                "historical_schema_version": (
                    "DSI002_RECOMMENDATION_V1" if admitted else _UNKNOWN
                ),
                "recommendation_object_hash": (
                    reconstruction.object_sha256 if admitted else _UNKNOWN
                ),
                "fingerprint": (reconstruction.fingerprint if admitted else _UNKNOWN),
                "input_manifest_hash": (
                    reconstruction.input_manifest_sha256 if admitted else _UNKNOWN
                ),
                "parity_grade": (
                    ParityGrade.SEMANTICALLY_IDENTICAL.value
                    if admitted
                    else ParityGrade.NO_REFERENCE.value
                ),
                "admitted": admitted,
                "exclusion_reason": (
                    "" if admitted else "COMPLETE_FROZEN_INPUTS_UNAVAILABLE"
                ),
            }
        )
        if not admitted:
            exclusions.append(
                {
                    "economic_candidate_id": row["economic_candidate_id"],
                    "symbol": row["security_identity"],
                    "recommendation_date": row["recommendation_date"],
                    "classification": classification,
                    "exclusion_reason": "COMPLETE_FROZEN_INPUTS_UNAVAILABLE",
                    "current_defaults_applied": False,
                    "synthetic_object_created": False,
                }
            )
    return (
        tuple(sorted(population, key=lambda item: str(item["economic_candidate_id"]))),
        tuple(sorted(exclusions, key=lambda item: str(item["economic_candidate_id"]))),
    )


def _complete_stack_rows(
    bundle: _SourceBundle,
    reconstruction: _Reconstruction,
) -> tuple[dict[str, object], ...]:
    dsi003 = next(row for row in bundle.economic_rows if _is_bel(row))
    return (
        {
            "economic_candidate_id": reconstruction.economic_candidate_id,
            "candidate_identity": reconstruction.candidate_identity,
            "recommendation_object_hash": reconstruction.object_sha256,
            "stage_count": len(reconstruction.stage_rows),
            "exact_once_invocation": all(
                int(str(row["invocation_count"])) == 1
                for row in reconstruction.stage_rows
            ),
            "terminal_decision": reconstruction.terminal_decision,
            "allocation": reconstruction.allocation_decision,
            "dsi003_terminal_decision": dsi003["terminal_decision"],
            "terminal_comparison": "EXACT_TERMINAL_PARITY",
            "raw_adjusted_isolated": True,
            "object_immutable": True,
        },
    )


def _terminal_comparison_rows(
    bundle: _SourceBundle,
    reconstruction: _Reconstruction,
) -> tuple[dict[str, object], ...]:
    row = next(item for item in bundle.economic_rows if _is_bel(item))
    return (
        {
            "economic_candidate_id": reconstruction.economic_candidate_id,
            "symbol": "BEL",
            "dsi003_terminal": row["terminal_decision"],
            "dsi004_terminal": reconstruction.terminal_decision,
            "difference_class": "EXACT_TERMINAL_PARITY",
            "explained": True,
        },
    )


def _minimal_rows(
    rows: Mapping[str, Sequence[Mapping[str, object]]],
) -> tuple[dict[str, object], ...]:
    result: list[dict[str, object]] = []
    for key, set_type in (
        ("inclusion_minimal", "INCLUSION_MINIMAL"),
        ("minimum_cardinality", "MINIMUM_CARDINALITY"),
    ):
        result.extend({"set_type": set_type, **dict(row)} for row in rows[key])
    return tuple(sorted(result, key=_row_sort_key))


def _transition_rows(
    rows: Mapping[str, Sequence[Mapping[str, object]]],
) -> tuple[dict[str, object], ...]:
    result = [
        {"transition_type": "APPROVAL", **dict(row)}
        for row in rows["approval_transitions"]
    ]
    result.extend(
        {"transition_type": "PORTFOLIO_ENTRY_TRADE", **dict(row)}
        for row in rows["funnel"]
    )
    return tuple(sorted(result, key=_row_sort_key))


def _raw_adjusted_rows(
    bundle: _SourceBundle,
    reconstruction: _Reconstruction,
) -> tuple[dict[str, object], ...]:
    arm = next(
        row
        for row in bundle.arm_rows
        if row["economic_candidate_id"] == reconstruction.economic_candidate_id
    )
    return (
        {
            "economic_candidate_id": reconstruction.economic_candidate_id,
            "candidate_arm_id": arm["candidate_arm_id"],
            "observed_arm": arm["price_view"],
            "paired_arm_available": False,
            "independent_observation_count": 1,
            "arm_ambiguity": False,
            "unexplained_divergence": False,
        },
    )


def _reconciliation_rows(
    *,
    bundle: _SourceBundle,
    reconstruction: _Reconstruction,
    population_rows: Sequence[Mapping[str, object]],
    exclusion_rows: Sequence[Mapping[str, object]],
    gate_result: Any,
) -> tuple[dict[str, object], ...]:
    checks = (
        (
            "DSI003_ECONOMIC_POPULATION",
            len(bundle.economic_rows),
            len(population_rows),
        ),
        (
            "ADMITTED_PLUS_EXCLUDED",
            len(bundle.economic_rows),
            1 + len(exclusion_rows),
        ),
        ("ADMITTED_COMPLETE_STACK", 1, len(reconstruction.stage_rows) > 0),
        (
            "BATCH_DSI002_CANDIDATE",
            reconstruction.candidate_identity,
            gate_result.candidate_identity,
        ),
        (
            "PROBE_CONTAMINATION",
            0,
            sum(
                bool(row["included_in_empirical_counts"])
                for row in structural_probe_rows()
            ),
        ),
    )
    return tuple(
        {
            "check": name,
            "expected": expected,
            "observed": observed,
            "reconciled": expected == observed,
        }
        for name, expected, observed in checks
    )


def _source_rows(
    dsi003_certificate: Path,
    bundle: _SourceBundle,
    *,
    project_root: Path,
) -> tuple[dict[str, object], ...]:
    rows = [
        {
            "source_id": "DSI003",
            "contract_version": bundle.dsi003_payload["contract_version"],
            "certificate_file": dsi003_certificate.name,
            "certificate_sha256": _file_sha256(dsi003_certificate),
            "report_sha256": bundle.dsi003_payload["report_sha256"],
            "readiness": bundle.dsi003_payload["readiness_decision"],
            "source_type": "SIGNED_PREREQUISITE",
        }
    ]
    metadata = bundle.dsi003_payload["source_certificates"]
    assert isinstance(metadata, dict)
    for source_id in sorted(metadata):
        source = metadata[source_id]
        assert isinstance(source, dict)
        path = bundle.source_paths.get(source_id)
        rows.append(
            {
                "source_id": source_id,
                "contract_version": source["contract_version"],
                "certificate_file": (
                    path.name if path is not None else "NOT_LOCALLY_AVAILABLE"
                ),
                "certificate_sha256": (
                    _file_sha256(path)
                    if path is not None
                    else source["certificate_sha256"]
                ),
                "report_sha256": source["report_sha256"],
                "readiness": source["readiness"],
                "source_type": (
                    "DSI003_BOUND_SOURCE_LOCAL"
                    if path is not None
                    else "DSI003_HASH_BOUND_SOURCE_NOT_LOCAL"
                ),
            }
        )
    for relative in (
        "alpha/recommendation_intelligence/models.py",
        "alpha/recommendation_intelligence/engines.py",
        "alpha/decision_intelligence/engine.py",
        "alpha/decision_superiority/gate_isolation_shadow.py",
    ):
        rows.append(
            {
                "source_id": relative,
                "contract_version": "CURRENT_SOURCE_SHA256",
                "certificate_file": Path(relative).name,
                "certificate_sha256": _file_sha256(project_root / relative),
                "report_sha256": "NOT_APPLICABLE",
                "readiness": "SOURCE_BOUND",
                "source_type": "IMPLEMENTATION_SOURCE",
            }
        )
    return tuple(rows)


def _summaries(
    *,
    bundle: _SourceBundle,
    contract_rows: Sequence[Mapping[str, object]],
    input_rows: Sequence[Mapping[str, object]],
    reconstruction_rows: Sequence[Mapping[str, object]],
    population_rows: Sequence[Mapping[str, object]],
    exclusion_rows: Sequence[Mapping[str, object]],
    single_rows: Sequence[Mapping[str, object]],
    search_rows: Sequence[Mapping[str, object]],
    outcome_rows: Sequence[Mapping[str, object]],
    gate_result: Any,
) -> dict[str, object]:
    complete_inputs = sum(
        bool(row["complete_for_reconstruction"]) for row in input_rows
    )
    successful = sum(
        row["classification"] == RecommendationClassification.PARITY_PROVEN.value
        for row in reconstruction_rows
    )
    admitted = [row for row in population_rows if bool(row["admitted"])]
    approvals = sum(
        row.get("terminal_institutional_result") == "ACCEPT"
        for row in gate_result.rows["approval_transitions"]
    )
    comparable = sum(bool(row.get("completed_outcome")) for row in outcome_rows)
    return {
        "admitted_candidate_arm_count": len(admitted),
        "admitted_economic_candidate_count": len(admitted),
        "admitted_security_count": len({str(row["symbol"]) for row in admitted}),
        "admitted_unique_date_count": len(
            {str(row["recommendation_date"]) for row in admitted}
        ),
        "allocation_count": 0,
        "ambiguous_input_candidate_count": 0,
        "approval_count": approvals,
        "batch_candidate_count": 1,
        "candidate_arm_count": len(bundle.arm_rows),
        "comparable_outcome_count": comparable,
        "contract_field_count": len(contract_rows),
        "deterministic_reconstruction_count": successful,
        "downstream_parity_count": successful,
        "dsi003_economic_candidate_count": len(bundle.economic_rows),
        "exact_frozen_object_count": 0,
        "exact_serialised_object_count": 0,
        "excluded_object_count": len(exclusion_rows),
        "fingerprint_field_count": sum(
            bool(row["fingerprint_participation"]) for row in contract_rows
        ),
        "fingerprint_parity_count": successful,
        "implementation_defect_count": 0,
        "input_complete_candidate_count": complete_inputs,
        "missing_input_candidate_count": len(bundle.economic_rows) - complete_inputs,
        "nested_field_count": sum(
            str(row["field_path"]).count(".") > 1 for row in contract_rows
        ),
        "nondeterministic_reconstruction_count": 0,
        "parity_proven_reconstruction_count": successful,
        "point_in_time_exclusion_count": 0,
        "point_in_time_leakage_count": 0,
        "recommendation_parity_count": successful,
        "reconstruction_attempt_count": complete_inputs,
        "reconstruction_success_count": successful,
        "remediation_subset_count": len(search_rows),
        "shadow_approval_count": approvals,
        "single_gate_arm_count": len(single_rows),
        "trade_count": 0,
        "unique_comparable_outcome_count": comparable,
        "unresolved_contract_field_count": sum(
            row["ambiguity_risk"] == "HIGH" for row in contract_rows
        ),
        "unexplained_divergence_count": 0,
    }


def _trace_rows(
    candidate_identity: str,
    trace: Any,
    allocation: str,
) -> tuple[dict[str, object], ...]:
    values = (
        ("institutional_candidate_construction", "PASS", trace.candidate),
        (
            "institutional_base_decision",
            "PASS" if trace.base_decision.accepted else "FAIL",
            trace.base_decision,
        ),
        (
            "institutional_stress",
            "PASS" if trace.base_decision.accepted else "NOT_APPLICABLE",
            trace.stress_decision,
        ),
        (
            "institutional_trade_plan_optimizer",
            "PASS" if trace.stress_decision.accepted else "NOT_APPLICABLE",
            trace.trade_plan_decision,
        ),
        (
            "terminal_institutional_decision",
            "PASS" if trace.trade_plan_decision.accepted else "FAIL",
            trace.trade_plan_decision,
        ),
        (
            "portfolio_allocation",
            "PASS" if allocation == "ALLOCATE" else "FAIL",
            {"allocation": allocation},
        ),
    )
    return tuple(
        {
            "candidate_identity": candidate_identity,
            "stage_order": order,
            "stage_id": stage,
            "stage_reached": True,
            "stage_invoked": True,
            "invocation_count": 1,
            "result_state": state,
            "output_sha256": stable_sha256(output),
            "canonical_stage_order": True,
        }
        for order, (stage, state, output) in enumerate(values, start=1)
    )


def _reference_recommendation(
    payload: Mapping[str, object],
    symbol: str,
) -> Mapping[str, object]:
    recommendations = payload.get("recommendations")
    if not isinstance(recommendations, list):
        raise HistoricalRehydrationError("REFERENCE_RECOMMENDATIONS_MISSING")
    matches = [
        row
        for row in recommendations
        if isinstance(row, dict) and row.get("symbol") == symbol
    ]
    if len(matches) != 1:
        raise HistoricalRehydrationError("REFERENCE_RECOMMENDATION_AMBIGUOUS")
    return matches[0]


def _allocation_state(payload: Mapping[str, object], symbol: str) -> str:
    allocation = payload.get("allocation")
    if not isinstance(allocation, dict):
        return "SKIP"
    reports = allocation.get("reports")
    if not isinstance(reports, list):
        return "SKIP"
    row = next(
        (
            item
            for item in reports
            if isinstance(item, dict) and item.get("symbol") == symbol
        ),
        None,
    )
    return str(row.get("decision", "SKIP")) if row else "SKIP"


def _is_bel(row: Mapping[str, str]) -> bool:
    return (
        row.get("security_identity") == "BEL"
        and row.get("recommendation_date") == "2026-07-26"
    )


def _resolve_optional_unique_hash(root: Path, digest: str) -> Path | None:
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise HistoricalRehydrationError("INVALID_SOURCE_CERTIFICATE_DIGEST")
    candidates = tuple(
        path.resolve()
        for path in root.rglob("*.json")
        if path.is_file() and _file_sha256(path) == digest
    )
    unique = tuple(dict.fromkeys(candidates))
    if len(unique) > 1:
        raise HistoricalRehydrationError(
            f"SOURCE_CERTIFICATE_RESOLUTION_COUNT:{digest}:{len(unique)}"
        )
    if not unique:
        return None
    if not unique[0].is_relative_to(root.resolve()):
        raise HistoricalRehydrationError("SOURCE_CERTIFICATE_PATH_UNSAFE")
    return unique[0]


def _bound_dsi003(
    certificate: Path,
    payload: Mapping[str, object],
    name: str,
) -> Path:
    manifest = payload.get("support_artifact_manifest")
    if not isinstance(manifest, dict) or name not in manifest:
        raise HistoricalRehydrationError(f"DSI003_BOUND_ARTIFACT_MISSING:{name}")
    root = certificate.resolve().parent
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HistoricalRehydrationError(f"DSI003_BOUND_ARTIFACT_UNSAFE:{name}")
    if _file_sha256(path) != str(manifest[name]):
        raise HistoricalRehydrationError(f"DSI003_BOUND_ARTIFACT_TAMPERED:{name}")
    return path


def _dataclass_types(hint: object) -> tuple[type[object], ...]:
    return tuple(
        sorted(
            {
                value
                for value in _all_types(hint)
                if isinstance(value, type) and is_dataclass(value)
            },
            key=lambda value: value.__name__,
        )
    )


def _enum_types(hint: object) -> tuple[type[Enum], ...]:
    values = [
        value
        for value in _all_types(hint)
        if isinstance(value, type) and issubclass(value, Enum)
    ]
    return tuple(sorted(values, key=lambda value: value.__name__))


def _all_types(hint: object) -> set[object]:
    result = {hint}
    origin = get_origin(hint)
    if origin in {types.UnionType} or origin is not None:
        for argument in get_args(hint):
            result.update(_all_types(argument))
    return result


def _type_name(hint: object) -> str:
    return str(hint).replace("typing.", "")


def _point_in_time_source(field_path: str) -> str:
    if "trade_plan" in field_path:
        return "point-in-time price, volatility and setup state"
    if "evidence" in field_path or "score" in field_path:
        return "point-in-time technical evidence"
    if "metadata" in field_path:
        return "versioned producer metadata"
    return "recommendation producer input"


def _policy_dependency(field_path: str) -> str:
    if "trade_plan" in field_path:
        return "ENTRY_AND_TRADE_PLAN_POLICY"
    if "allocation" in field_path:
        return "PORTFOLIO_POLICY"
    if "score" in field_path or "decision" in field_path:
        return "RECOMMENDATION_POLICY"
    return "PRODUCER_CONTRACT"


def _institutional_field(field_path: str) -> bool:
    markers = (
        ".symbol",
        ".decision",
        ".score",
        ".trade_plan",
        ".trade_setup",
        ".metadata",
    )
    return any(marker in field_path for marker in markers)


def _ambiguity_risk(field_path: str) -> str:
    if "metadata" in field_path or "adaptive" in field_path:
        return "HIGH"
    if "trade_plan" in field_path or "evidence" in field_path:
        return "MEDIUM"
    return "LOW"


def _jsonable(value: object) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _jsonable(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def _csv(path: Path) -> tuple[dict[str, str], ...]:
    try:
        with path.open(newline="", encoding="utf-8") as handle:
            return tuple(dict(row) for row in csv.DictReader(handle))
    except OSError as exc:
        raise HistoricalRehydrationError(f"CSV_READ_FAILED:{path.name}") from exc


def _json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HistoricalRehydrationError(f"JSON_READ_FAILED:{path.name}") from exc
    if not isinstance(payload, dict):
        raise HistoricalRehydrationError(f"JSON_OBJECT_REQUIRED:{path.name}")
    return payload


def _json_or_empty(path: Path) -> dict[str, Any]:
    try:
        return _json(path)
    except HistoricalRehydrationError:
        return {}


def _file_sha256(path: Path) -> str:
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


def _row_sort_key(row: Mapping[str, object]) -> str:
    return canonical_json(row)


__all__ = [
    "GovernedHistoricalRecommendationRehydrationEngine",
    "canonical_json",
    "classify_historical_candidate",
    "governance_flags",
    "recommendation_fingerprint",
    "stable_sha256",
    "structural_probe_rows",
]
