from __future__ import annotations

import csv
import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from typing import Any

from alpha.benchmark_replay.provenance import file_hash
from alpha.institutional_gate_truth.models import BASELINE_ID, RejectionCandidate


@dataclass(frozen=True, slots=True)
class RejectionPopulationEvidence:
    candidates: tuple[RejectionCandidate, ...]
    baseline_manifest: MappingProxyType[str, Any]
    source_hashes: MappingProxyType[str, str]


class RejectionPopulationBuilder:
    """Build the rejected BUY population from frozen CABR/ACU artifacts."""

    def build(
        self,
        *,
        benchmark_output: Path | str,
        acu_output: Path | str,
    ) -> RejectionPopulationEvidence:
        benchmark = Path(benchmark_output)
        acu = Path(acu_output)
        manifest_path = benchmark / "manifest.json"
        approvals_path = benchmark / "approval_statistics.csv"
        rankings_path = acu / "candidate_rankings.csv"
        gates_path = acu / "gate_attribution.csv"
        required = (manifest_path, approvals_path, rankings_path, gates_path)
        missing = tuple(str(path) for path in required if not path.exists())
        if missing:
            raise FileNotFoundError(
                "IGTA frozen evidence is incomplete: " + ", ".join(missing)
            )
        manifest = _manifest(manifest_path)
        _verify_benchmark_artifacts(benchmark, manifest)
        approvals = _approvals(approvals_path)
        gates = _gates(gates_path)
        candidates: list[RejectionCandidate] = []
        seen: set[tuple[date, str]] = set()
        with rankings_path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                signal = row.get("final_signal", "").strip().upper()
                if signal not in {"BUY", "STRONG_BUY"}:
                    continue
                observed_on = date.fromisoformat(_required(row, "observed_on"))
                symbol = _required(row, "symbol").strip().upper()
                key = (observed_on, symbol)
                if key in seen:
                    raise ValueError(f"duplicate frozen candidate: {key}")
                seen.add(key)
                approval = approvals.get(key)
                if approval is None:
                    raise ValueError(f"CABR approval evidence missing for {key}")
                if _boolean(approval.get("approved")):
                    continue
                gate_rows = gates.get(key, ())
                primary_reason = _required(approval, "primary_reason_code")
                approval_score = _decimal(approval.get("opportunity_score"))
                ranking_score = _decimal(row.get("score"))
                if approval_score != ranking_score:
                    raise ValueError(f"CABR/ACU score mismatch for {key}")
                frozen_primary = next(
                    (
                        _required(item, "gate_code")
                        for item in gate_rows
                        if _boolean(item.get("primary"))
                    ),
                    None,
                )
                if frozen_primary is not None and frozen_primary != primary_reason:
                    raise ValueError(f"CABR/ACU primary gate mismatch for {key}")
                gate_reasons = tuple(
                    dict.fromkeys(_required(item, "gate_code") for item in gate_rows)
                )
                reasons = gate_reasons or (primary_reason,)
                categories = tuple(
                    dict.fromkeys(
                        item.get("category", "UNKNOWN").strip() or "UNKNOWN"
                        for item in gate_rows
                    )
                ) or ("UNKNOWN",)
                entry = _decimal(row.get("entry_price"))
                stop = _decimal(row.get("initial_stop"))
                target = _decimal(row.get("target_1"))
                valid = (
                    entry is not None
                    and stop is not None
                    and target is not None
                    and stop > 0
                    and stop < entry < target
                )
                score = ranking_score
                if score is None:
                    raise ValueError(f"candidate score missing for {key}")
                expected_r = _decimal(row.get("expected_r"))
                expected_return = _decimal(row.get("expected_return"))
                component_scores = {
                    "aggregate_score": str(score),
                    "expected_reward_risk": _text(expected_r),
                    "expected_return": _text(expected_return),
                    "status": "UNAVAILABLE_IN_CABR_BASELINE",
                }
                rank = int(_required(row, "rank"))
                candidates.append(
                    RejectionCandidate(
                        candidate_id=_candidate_id(observed_on, symbol, rank),
                        observed_on=observed_on,
                        symbol=symbol,
                        final_signal=signal,
                        candidate_score=score,
                        confidence=row.get("confidence", "UNKNOWN").strip().upper()
                        or "UNKNOWN",
                        setup=row.get("setup_type", "UNKNOWN").strip() or "UNKNOWN",
                        timing=row.get("setup_stage", "UNKNOWN").strip() or "UNKNOWN",
                        trade_plan_status=(
                            "VALID" if valid else "INCOMPLETE_OR_INVALID"
                        ),
                        rejection_reason=primary_reason,
                        rejection_reasons=reasons,
                        rejection_categories=categories,
                        component_scores=component_scores,
                        entry_price=entry,
                        prospective_stop=stop,
                        prospective_target=target,
                        expected_reward_risk=expected_r,
                        expected_return=expected_return,
                        holding_period_sessions=max(
                            1, int(row.get("holding_period_days") or "20")
                        ),
                        sector=row.get("sector", "UNKNOWN").strip() or "UNKNOWN",
                        liquidity_bucket=row.get(
                            "liquidity_bucket", "UNAVAILABLE"
                        ).strip()
                        or "UNAVAILABLE",
                        rank=rank,
                    )
                )
        candidates.sort(key=lambda item: (item.observed_on, item.rank, item.symbol))
        if not candidates:
            raise ValueError("frozen CABR contains no rejected BUY candidates")
        frozen_manifest = MappingProxyType(
            {str(key): value for key, value in manifest.items()}
        )
        source_hashes = MappingProxyType(
            {
                "approval_statistics.csv": file_hash(approvals_path),
                "baseline_manifest.json": file_hash(manifest_path),
                "candidate_rankings.csv": file_hash(rankings_path),
                "gate_attribution.csv": file_hash(gates_path),
            }
        )
        return RejectionPopulationEvidence(
            candidates=tuple(candidates),
            baseline_manifest=frozen_manifest,
            source_hashes=source_hashes,
        )


def _manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("CABR manifest must be an object")
    if payload.get("baseline_id") != BASELINE_ID:
        raise ValueError("IGTA requires ALPHA_BASELINE_v1.0")
    if payload.get("production_influence") is not False:
        raise ValueError("CABR production isolation is invalid")
    return {str(key): value for key, value in payload.items()}


def _verify_benchmark_artifacts(root: Path, manifest: dict[str, Any]) -> None:
    hashes = manifest.get("artifact_hashes")
    if not isinstance(hashes, dict):
        raise ValueError("CABR manifest artifact hashes are unavailable")
    for name in ("approval_statistics.csv",):
        expected = hashes.get(name)
        path = root / name
        if not isinstance(expected, str) or file_hash(path) != expected:
            raise ValueError(f"CABR artifact checksum mismatch: {name}")


def _approvals(path: Path) -> dict[tuple[date, str], dict[str, str]]:
    result: dict[tuple[date, str], dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (
                date.fromisoformat(_required(row, "observed_on")),
                _required(row, "symbol").strip().upper(),
            )
            if key in result:
                raise ValueError(f"duplicate CABR approval row: {key}")
            result[key] = row
    return result


def _gates(path: Path) -> dict[tuple[date, str], tuple[dict[str, str], ...]]:
    grouped: dict[tuple[date, str], list[dict[str, str]]] = defaultdict(list)
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (
                date.fromisoformat(_required(row, "observed_on")),
                _required(row, "symbol").strip().upper(),
            )
            grouped[key].append(row)
    return {
        key: tuple(
            sorted(
                rows,
                key=lambda item: (
                    0 if _boolean(item.get("primary")) else 1,
                    item.get("gate_code", ""),
                ),
            )
        )
        for key, rows in grouped.items()
    }


def _candidate_id(observed_on: date, symbol: str, rank: int) -> str:
    raw = f"{BASELINE_ID}|{observed_on.isoformat()}|{symbol}|{rank}"
    return "IGTA-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20].upper()


def _required(row: dict[str, str], key: str) -> str:
    value = row.get(key, "").strip()
    if not value:
        raise ValueError(f"required frozen field is missing: {key}")
    return value


def _decimal(value: str | None) -> Decimal | None:
    if value is None or not value.strip():
        return None
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"invalid frozen decimal: {value}") from error


def _boolean(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes"}


def _text(value: Decimal | None) -> str:
    return "UNAVAILABLE" if value is None else str(value)


__all__ = ["RejectionPopulationBuilder", "RejectionPopulationEvidence"]
