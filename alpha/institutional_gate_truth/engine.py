from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any

from alpha.benchmark_replay.provenance import file_hash
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.institutional_gate_truth.counterfactual import (
    CounterfactualPortfolioEngine,
)
from alpha.institutional_gate_truth.false_rejection_analysis import (
    component_attribution,
)
from alpha.institutional_gate_truth.gate_effectiveness import gate_effectiveness
from alpha.institutional_gate_truth.models import (
    BASELINE_ID,
    IGTA_VERSION,
    IGTAManifest,
    InstitutionalGateTruthReport,
)
from alpha.institutional_gate_truth.rejection_outcomes import (
    OutcomePolicy,
    RejectionOutcomeEngine,
    candidate_frame,
)
from alpha.institutional_gate_truth.rejection_population import (
    RejectionPopulationBuilder,
)
from alpha.institutional_gate_truth.rejection_reason_analysis import (
    reason_statistics,
)


class InstitutionalGateTruthAuditEngine:
    """Measure what the unchanged institutional gate prevented."""

    def run(
        self,
        *,
        store: LegacyMarketDataStore,
        benchmark_output: Path | str,
        acu_output: Path | str,
    ) -> InstitutionalGateTruthReport:
        population = RejectionPopulationBuilder().build(
            benchmark_output=benchmark_output,
            acu_output=acu_output,
        )
        baseline = dict(population.baseline_manifest)
        versions = _mapping(baseline, "versions")
        policy_payload = _mapping(baseline, "policy")
        warehouse_hash = _text(versions, "warehouse_hash")
        observed_hash = file_hash(store.path)
        if observed_hash != warehouse_hash:
            raise ValueError(
                "IGTA warehouse checksum does not match ALPHA_BASELINE_v1.0"
            )
        outcome_policy = OutcomePolicy(
            transaction_cost_percent=Decimal(
                _text(policy_payload, "transaction_cost_percent")
            ),
            slippage_percent=Decimal(_text(policy_payload, "slippage_percent")),
            entry_validity_sessions=int(
                _text(policy_payload, "entry_validity_sessions")
            ),
        )
        frame = candidate_frame(population.candidates)
        future = store.future_bars(frame, limit=max(outcome_policy.horizons))
        assessments = RejectionOutcomeEngine(outcome_policy).evaluate(
            candidates=population.candidates,
            future_bars=future,
        )
        replay_start = date.fromisoformat(_text(baseline, "replay_start"))
        replay_end = date.fromisoformat(_text(baseline, "replay_end"))
        sessions = store.trade_dates(start=replay_start, end=replay_end)
        initial_capital = Decimal(_text(policy_payload, "initial_capital"))
        trades, curve, counterfactual = CounterfactualPortfolioEngine().run(
            assessments=assessments,
            future_bars=future,
            sessions=sessions,
            starting_capital=initial_capital,
            round_trip_friction_percent=(outcome_policy.round_trip_friction_percent),
        )
        effectiveness = gate_effectiveness(
            assessments,
            initial_capital=initial_capital,
            counterfactual=counterfactual,
        )
        source_hashes = dict(population.source_hashes)
        source_hashes["warehouse"] = observed_hash
        manifest = IGTAManifest(
            audit_version=IGTA_VERSION,
            baseline_id=BASELINE_ID,
            baseline_manifest_hash=source_hashes["baseline_manifest.json"],
            source_commit=_text(versions, "source_commit"),
            warehouse_version=_text(versions, "warehouse_version"),
            warehouse_hash=warehouse_hash,
            candidate_version=_text(versions, "candidate_generation_version"),
            candidate_hash=_text(versions, "candidate_generation_hash"),
            feature_version=_text(versions, "feature_version"),
            feature_hash=_text(versions, "feature_hash"),
            approval_policy_version=_text(versions, "approval_policy_version"),
            approval_policy_hash=_text(versions, "approval_policy_hash"),
            trade_plan_version=_text(versions, "trade_plan_policy_version"),
            trade_plan_hash=_text(versions, "trade_plan_policy_hash"),
            replay_start=replay_start,
            replay_end=replay_end,
            transaction_cost_percent=outcome_policy.transaction_cost_percent,
            slippage_percent=outcome_policy.slippage_percent,
            entry_validity_sessions=outcome_policy.entry_validity_sessions,
            horizons=outcome_policy.horizons,
            source_hashes=MappingProxyType(source_hashes),
        )
        return InstitutionalGateTruthReport(
            manifest=manifest,
            assessments=assessments,
            reason_statistics=reason_statistics(
                assessments,
                initial_capital=initial_capital,
            ),
            component_attribution=component_attribution(assessments),
            effectiveness=effectiveness,
            counterfactual_trades=trades,
            counterfactual_curve=curve,
            counterfactual_statistics=counterfactual,
        )


def _mapping(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"CABR manifest field must be an object: {key}")
    return {str(item_key): item for item_key, item in value.items()}


def _text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None or not str(value).strip():
        raise ValueError(f"CABR manifest field is unavailable: {key}")
    return str(value)


__all__ = ["InstitutionalGateTruthAuditEngine"]
