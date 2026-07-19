from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from alpha.benchmark_replay.provenance import file_hash
from alpha.gate_dependency_audit.gate_sequence import (
    AGGREGATE_GATES,
    CORE_GATE_SEQUENCE,
    criterion_for_failure,
)
from alpha.gate_dependency_audit.models import (
    BASELINE_ID,
    CandidateGateLineage,
    GateLineageStep,
    GateStatus,
)


@dataclass(frozen=True, slots=True)
class LineageEvidence:
    lineages: tuple[CandidateGateLineage, ...]
    igta_manifest: MappingProxyType[str, Any]
    source_hashes: MappingProxyType[str, str]


@dataclass(frozen=True, slots=True)
class _Failure:
    code: str
    explanation: str


class DecisionLineageBuilder:
    """Reconstruct complete criterion paths from frozen IGTA and ACU evidence."""

    def build(
        self,
        *,
        igta_output: Path | str,
        acu_output: Path | str,
        project_root: Path | str,
    ) -> LineageEvidence:
        igta = Path(igta_output)
        acu = Path(acu_output)
        root = Path(project_root)
        manifest_path = igta / "manifest.json"
        classifications_path = igta / "rejection_classification.csv"
        gates_path = acu / "gate_attribution.csv"
        for path in (manifest_path, classifications_path, gates_path):
            if not path.exists():
                raise FileNotFoundError(f"GDSBA evidence is unavailable: {path}")
        manifest = _manifest(manifest_path)
        _verify_inputs(
            manifest=manifest,
            classifications_path=classifications_path,
            gates_path=gates_path,
            approval_engine_path=root / "alpha/decision_intelligence/engine.py",
        )
        candidates = _candidate_rows(classifications_path)
        failures = _failure_rows(gates_path, set(candidates))
        lineages = tuple(
            reconstruct_candidate_lineage(row, failures.get(key, ()))
            for key, row in sorted(candidates.items())
        )
        if len(lineages) != 1781:
            raise ValueError(
                "GDSBA requires the complete 1,781-candidate IGTA population"
            )
        return LineageEvidence(
            lineages=lineages,
            igta_manifest=MappingProxyType(manifest),
            source_hashes=MappingProxyType(
                {
                    "gate_attribution.csv": file_hash(gates_path),
                    "igta_manifest.json": file_hash(manifest_path),
                    "rejection_classification.csv": file_hash(classifications_path),
                }
            ),
        )


def reconstruct_candidate_lineage(
    row: dict[str, str],
    raw_failures: tuple[dict[str, str], ...],
) -> CandidateGateLineage:
    by_gate: dict[str, list[_Failure]] = defaultdict(list)
    for failure in raw_failures:
        code = _required(failure, "gate_code")
        explanation = _required(failure, "explanation")
        by_gate[criterion_for_failure(code, explanation)].append(
            _Failure(code=code, explanation=explanation)
        )
    observed: dict[str, GateStatus] = {}
    for gate in CORE_GATE_SEQUENCE:
        status = GateStatus.FAIL if by_gate.get(gate.gate_id) else GateStatus.PASS
        if gate.gate_id == "REWARD_RISK_MINIMUM" and (
            by_gate.get("REWARD_RISK_AVAILABILITY")
            or by_gate.get("TRADE_PLAN_COMPLETENESS")
        ):
            status = GateStatus.NOT_APPLICABLE
        observed[gate.gate_id] = status
    first_failed = next(
        (
            gate
            for gate in CORE_GATE_SEQUENCE
            if observed[gate.gate_id] is GateStatus.FAIL
        ),
        None,
    )
    reached = True
    steps: list[GateLineageStep] = []
    for gate in CORE_GATE_SEQUENCE:
        observed_status = observed[gate.gate_id]
        if not reached:
            sequential = GateStatus.NOT_REACHED
        else:
            sequential = observed_status
            if observed_status is GateStatus.FAIL:
                reached = False
        gate_failures = tuple(by_gate.get(gate.gate_id, ()))
        steps.append(
            GateLineageStep(
                gate_id=gate.gate_id,
                display_name=gate.display_name,
                gate_group=gate.group,
                sequence=gate.sequence,
                observed_status=observed_status,
                sequential_status=sequential,
                failure_codes=tuple(item.code for item in gate_failures),
                failure_explanations=tuple(item.explanation for item in gate_failures),
                first_failure=first_failed == gate,
            )
        )
    for gate in AGGREGATE_GATES:
        is_institutional = gate.gate_id == "INSTITUTIONAL_DECISION"
        steps.append(
            GateLineageStep(
                gate_id=gate.gate_id,
                display_name=gate.display_name,
                gate_group=gate.group,
                sequence=gate.sequence,
                observed_status=(
                    GateStatus.FAIL if is_institutional else GateStatus.NOT_REACHED
                ),
                sequential_status=GateStatus.NOT_REACHED,
                failure_codes=("INSTITUTIONAL_REJECT",) if is_institutional else (),
                failure_explanations=(
                    "One or more frozen institutional criteria failed.",
                )
                if is_institutional
                else (),
                first_failure=False,
            )
        )
    failed_gates = tuple(
        gate.gate_id
        for gate in CORE_GATE_SEQUENCE
        if observed[gate.gate_id] is GateStatus.FAIL
    )
    failed_groups = tuple(
        dict.fromkeys(
            gate.group
            for gate in CORE_GATE_SEQUENCE
            if observed[gate.gate_id] is GateStatus.FAIL
        )
    )
    return CandidateGateLineage(
        candidate_id=_required(row, "candidate_id"),
        observed_on=date.fromisoformat(_required(row, "observed_on")),
        symbol=_required(row, "symbol").upper(),
        final_signal=_required(row, "final_signal"),
        candidate_score=Decimal(_required(row, "candidate_score")),
        outcome_classification=_required(row, "classification"),
        planned_net_return_percent=_decimal(row.get("planned_net_return_percent")),
        planned_realized_r=_decimal(row.get("planned_realized_r")),
        first_failed_gate=None if first_failed is None else first_failed.gate_id,
        first_failed_group=None if first_failed is None else first_failed.group,
        failed_gates=failed_gates,
        failed_groups=failed_groups,
        lineage=tuple(steps),
    )


def _manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("IGTA manifest must be an object")
    if payload.get("baseline_id") != BASELINE_ID:
        raise ValueError("GDSBA requires ALPHA_BASELINE_v1.0")
    if payload.get("audit_version") != "IGTA_v1.0":
        raise ValueError("GDSBA requires IGTA_v1.0 evidence")
    if payload.get("production_influence") is not False:
        raise ValueError("IGTA production isolation is invalid")
    return {str(key): value for key, value in payload.items()}


def _verify_inputs(
    *,
    manifest: dict[str, Any],
    classifications_path: Path,
    gates_path: Path,
    approval_engine_path: Path,
) -> None:
    artifacts = _mapping(manifest, "artifact_hashes")
    sources = _mapping(manifest, "source_hashes")
    if file_hash(classifications_path) != str(
        artifacts.get("rejection_classification.csv")
    ):
        raise ValueError("IGTA rejection classification checksum mismatch")
    if file_hash(gates_path) != str(sources.get("gate_attribution.csv")):
        raise ValueError("ACU gate attribution checksum mismatch")
    expected_policy = str(manifest.get("approval_policy_hash", ""))
    if _tree_file_hash(approval_engine_path) != expected_policy:
        raise ValueError("frozen approval-policy source checksum mismatch")


def _candidate_rows(path: Path) -> dict[tuple[date, str], dict[str, str]]:
    result: dict[tuple[date, str], dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (
                date.fromisoformat(_required(row, "observed_on")),
                _required(row, "symbol").upper(),
            )
            if key in result:
                raise ValueError(f"duplicate IGTA candidate: {key}")
            result[key] = row
    return result


def _failure_rows(
    path: Path,
    keys: set[tuple[date, str]],
) -> dict[tuple[date, str], tuple[dict[str, str], ...]]:
    grouped: dict[tuple[date, str], list[dict[str, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (
                date.fromisoformat(_required(row, "observed_on")),
                _required(row, "symbol").upper(),
            )
            if key in keys:
                grouped[key].append(row)
    return {key: tuple(values) for key, values in grouped.items()}


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"IGTA manifest field must be an object: {key}")
    return {str(item_key): item for item_key, item in value.items()}


def _tree_file_hash(path: Path) -> str:
    if not path.exists():
        return "UNAVAILABLE"
    root = path.parents[2]
    digest = hashlib.sha256()
    digest.update(str(path.relative_to(root)).encode("utf-8"))
    digest.update(b"\0")
    digest.update(path.read_bytes())
    digest.update(b"\0")
    return digest.hexdigest()


def _required(row: dict[str, str], key: str) -> str:
    value = row.get(key, "").strip()
    if not value:
        raise ValueError(f"required gate evidence is missing: {key}")
    return value


def _decimal(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    return Decimal(value)


__all__ = [
    "DecisionLineageBuilder",
    "LineageEvidence",
    "reconstruct_candidate_lineage",
]
