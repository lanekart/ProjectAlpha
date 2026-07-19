from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from alpha.benchmark_replay.provenance import file_hash
from alpha.market_opportunity_truth.models import BASELINE_ID, RawOpportunityOnset

DEFAULT_FEATURE_OUTPUT = Path(
    ".alpha/feature_attribution/POINT_IN_TIME_FEATURE_ATTRIBUTION_v1.0"
)
DEFAULT_BENCHMARK_OUTPUT = Path(".alpha/benchmark/ALPHA_BASELINE_v1.0")
DEFAULT_ACU_OUTPUT = Path(".alpha/acu/ALPHA_CANONICAL_v1.0")


@dataclass(frozen=True, slots=True)
class PopulationEvidence:
    onsets: tuple[RawOpportunityOnset, ...]
    feature_manifest: MappingProxyType[str, Any]
    baseline_manifest: MappingProxyType[str, Any]
    source_hashes: MappingProxyType[str, str]


class OpportunityPopulationLoader:
    """Load the frozen pre-association onset population without future labels."""

    def load(
        self,
        *,
        feature_output: Path | str = DEFAULT_FEATURE_OUTPUT,
        benchmark_output: Path | str = DEFAULT_BENCHMARK_OUTPUT,
        acu_output: Path | str = DEFAULT_ACU_OUTPUT,
    ) -> PopulationEvidence:
        feature_root = Path(feature_output)
        benchmark_root = Path(benchmark_output)
        acu_root = Path(acu_output)
        feature_manifest_path = feature_root / "manifest.json"
        population_path = feature_root / "research_population.csv"
        outcomes_path = feature_root / "outcome_labels.csv"
        baseline_path = benchmark_root / "manifest.json"
        candidate_statistics_path = benchmark_root / "candidate_statistics.csv"
        trade_log_path = benchmark_root / "trade_log.csv"
        candidate_rankings_path = acu_root / "candidate_rankings.csv"
        required = (
            feature_manifest_path,
            population_path,
            outcomes_path,
            baseline_path,
            candidate_statistics_path,
            trade_log_path,
            candidate_rankings_path,
        )
        missing = tuple(path for path in required if not path.exists())
        if missing:
            raise FileNotFoundError(
                "MOTA evidence is unavailable: "
                + ", ".join(str(path) for path in missing)
            )
        feature_manifest = _json_object(feature_manifest_path)
        baseline_manifest = _json_object(baseline_path)
        self._validate_manifests(feature_manifest, baseline_manifest)
        _validate_baseline_artifact(
            baseline_manifest,
            candidate_statistics_path,
        )
        _validate_baseline_artifact(baseline_manifest, trade_log_path)
        onsets = _load_onsets(population_path)
        expected = int(
            _mapping(feature_manifest, "population_summary").get(
                "reconstructed_market_opportunities", -1
            )
        )
        if len(onsets) != expected:
            raise ValueError(
                "MOTA population does not match the frozen feature manifest"
            )
        return PopulationEvidence(
            onsets=onsets,
            feature_manifest=MappingProxyType(feature_manifest),
            baseline_manifest=MappingProxyType(baseline_manifest),
            source_hashes=MappingProxyType(
                {
                    "baseline_manifest.json": file_hash(baseline_path),
                    "candidate_rankings.csv": file_hash(candidate_rankings_path),
                    "candidate_statistics.csv": file_hash(candidate_statistics_path),
                    "feature_manifest.json": file_hash(feature_manifest_path),
                    "outcome_labels.csv": file_hash(outcomes_path),
                    "research_population.csv": file_hash(population_path),
                    "trade_log.csv": file_hash(trade_log_path),
                }
            ),
        )

    @staticmethod
    def _validate_manifests(
        feature: dict[str, Any],
        baseline: dict[str, Any],
    ) -> None:
        if baseline.get("baseline_id") != BASELINE_ID:
            raise ValueError("MOTA requires ALPHA_BASELINE_v1.0")
        if baseline.get("production_influence") is not False:
            raise ValueError("CABR production isolation is invalid")
        if baseline.get("point_in_time_enforced") is not True:
            raise ValueError("CABR point-in-time enforcement is unavailable")
        if feature.get("production_influence") is not False:
            raise ValueError("feature population production isolation is invalid")
        if feature.get("primary_population") != "ALL_MARKET_OPPORTUNITIES":
            raise ValueError("MOTA requires the pre-association market population")
        guardrails = _mapping(feature, "guardrails")
        if guardrails.get("POINT_IN_TIME_ONLY") is not True:
            raise ValueError("feature population is not point-in-time certified")
        versions = _mapping(baseline, "versions")
        if feature.get("source_commit") != versions.get("source_commit"):
            raise ValueError("MOTA source commit does not match CABR")
        if feature.get("canonical_policy_id") != "ALPHA_CANONICAL_v1.0":
            raise ValueError("MOTA canonical policy identity is invalid")


def _load_onsets(path: Path) -> tuple[RawOpportunityOnset, ...]:
    rows: list[RawOpportunityOnset] = []
    seen_ids: set[str] = set()
    seen_symbol_dates: set[tuple[str, date]] = set()
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            opportunity_id = _required(row, "onset_id")
            symbol = _required(row, "symbol").upper()
            onset_date = date.fromisoformat(_required(row, "onset_date"))
            symbol_date = (symbol, onset_date)
            if opportunity_id in seen_ids or symbol_date in seen_symbol_dates:
                raise ValueError("MOTA population contains duplicate opportunities")
            seen_ids.add(opportunity_id)
            seen_symbol_dates.add(symbol_date)
            inputs = _point_in_time_inputs(_required(row, "point_in_time_inputs"))
            rows.append(
                RawOpportunityOnset(
                    opportunity_id=opportunity_id,
                    symbol=symbol,
                    onset_date=onset_date,
                    onset_sequence=int(_required(row, "onset_sequence")),
                    entry=Decimal(_required(row, "entry_trigger")),
                    reference_level=Decimal(_required(row, "reference_level")),
                    initial_stop=Decimal(_required(row, "prospective_stop")),
                    reasonable_target=Decimal(_required(row, "prospective_target")),
                    prospective_rr=Decimal(_required(row, "prospective_rr")),
                    source_confidence=Decimal(_required(row, "confidence")),
                    point_in_time_inputs=inputs,
                    dataset_version=_required(row, "dataset_version"),
                    evidence_hash=_required(row, "feature_snapshot_hash"),
                )
            )
    return tuple(
        sorted(
            rows, key=lambda item: (item.onset_date, item.symbol, item.opportunity_id)
        )
    )


def _point_in_time_inputs(value: str) -> tuple[tuple[str, str], ...]:
    decoded = json.loads(value)
    if not isinstance(decoded, list):
        raise ValueError("MOTA point-in-time inputs must be a list")
    result: list[tuple[str, str]] = []
    for item in decoded:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("MOTA point-in-time input is malformed")
        result.append((str(item[0]), str(item[1])))
    return tuple(sorted(result))


def _validate_baseline_artifact(manifest: dict[str, Any], path: Path) -> None:
    hashes = _mapping(manifest, "artifact_hashes")
    if file_hash(path) != str(hashes.get(path.name, "")):
        raise ValueError(f"CABR artifact checksum mismatch: {path.name}")


def _json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"MOTA manifest must be an object: {path}")
    return {str(key): value for key, value in payload.items()}


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"MOTA manifest field must be an object: {key}")
    return {str(item_key): item for item_key, item in value.items()}


def _required(row: dict[str, str], key: str) -> str:
    value = row.get(key, "").strip()
    if not value:
        raise ValueError(f"MOTA source field is unavailable: {key}")
    return value


__all__ = [
    "DEFAULT_ACU_OUTPUT",
    "DEFAULT_BENCHMARK_OUTPUT",
    "DEFAULT_FEATURE_OUTPUT",
    "OpportunityPopulationLoader",
    "PopulationEvidence",
]
