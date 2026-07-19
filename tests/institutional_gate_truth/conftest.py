from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pandas as pd
import pytest

from alpha.institutional_gate_truth.counterfactual import (
    CounterfactualPortfolioEngine,
)
from alpha.institutional_gate_truth.false_rejection_analysis import (
    component_attribution,
)
from alpha.institutional_gate_truth.gate_effectiveness import gate_effectiveness
from alpha.institutional_gate_truth.models import (
    IGTAManifest,
    InstitutionalGateTruthReport,
    RejectionCandidate,
)
from alpha.institutional_gate_truth.rejection_outcomes import (
    RejectionOutcomeEngine,
)
from alpha.institutional_gate_truth.rejection_reason_analysis import (
    reason_statistics,
)


def candidate(
    *,
    candidate_id: str = "IGTA-TEST",
    symbol: str = "TEST",
    reason: str = "WEAK_SETUP",
    reasons: tuple[str, ...] = ("WEAK_SETUP", "INSUFFICIENT_EVIDENCE"),
    entry: Decimal | None = Decimal("100"),
    stop: Decimal | None = Decimal("90"),
    target: Decimal | None = Decimal("120"),
    holding: int = 2,
) -> RejectionCandidate:
    return RejectionCandidate(
        candidate_id=candidate_id,
        observed_on=date(2024, 1, 1),
        symbol=symbol,
        final_signal="BUY",
        candidate_score=Decimal("82"),
        confidence="HIGH",
        setup="MOMENTUM CONTINUATION",
        timing="ENTRY_READY",
        trade_plan_status="VALID",
        rejection_reason=reason,
        rejection_reasons=reasons,
        rejection_categories=("Trend", "Approval"),
        component_scores={"status": "UNAVAILABLE_IN_CABR_BASELINE"},
        entry_price=entry,
        prospective_stop=stop,
        prospective_target=target,
        expected_reward_risk=Decimal("2"),
        expected_return=Decimal("0.10"),
        holding_period_sessions=holding,
        sector="UNKNOWN",
        liquidity_bucket="HIGH",
        rank=1,
    )


def bars(
    candidate_id: str,
    values: tuple[tuple[str, str, str, str, str], ...],
) -> pd.DataFrame:
    return pd.DataFrame.from_records(
        (
            {
                "candidate_id": candidate_id,
                "symbol": "TEST",
                "trade_date": date.fromisoformat(day),
                "open": Decimal(open_price),
                "high": Decimal(high),
                "low": Decimal(low),
                "close": Decimal(close),
                "volume": 1000,
                "sector": "UNKNOWN",
                "exchange": "NSE",
            }
            for day, open_price, high, low, close in values
        )
    )


@pytest.fixture
def gate_report() -> InstitutionalGateTruthReport:
    first = candidate(candidate_id="IGTA-WIN", symbol="WIN")
    second = candidate(candidate_id="IGTA-LOSS", symbol="LOSS")
    frame = pd.concat(
        (
            bars(
                "IGTA-WIN",
                (
                    ("2024-01-02", "100", "105", "95", "102"),
                    ("2024-01-03", "102", "121", "101", "120"),
                ),
            ),
            bars(
                "IGTA-LOSS",
                (
                    ("2024-01-02", "100", "105", "95", "102"),
                    ("2024-01-03", "88", "92", "85", "89"),
                ),
            ),
        ),
        ignore_index=True,
    )
    assessments = RejectionOutcomeEngine().evaluate(
        candidates=(first, second),
        future_bars=frame,
    )
    trades, curve, counterfactual = CounterfactualPortfolioEngine().run(
        assessments=assessments,
        future_bars=frame,
        sessions=(date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)),
        starting_capital=Decimal("1000000"),
        round_trip_friction_percent=Decimal("0.30"),
    )
    manifest = IGTAManifest(
        audit_version="IGTA_v1.0",
        baseline_id="ALPHA_BASELINE_v1.0",
        baseline_manifest_hash="baseline-hash",
        source_commit="commit",
        warehouse_version="warehouse-v1",
        warehouse_hash="warehouse-hash",
        candidate_version="candidate-v1",
        candidate_hash="candidate-hash",
        feature_version="feature-v1",
        feature_hash="feature-hash",
        approval_policy_version="approval-v1",
        approval_policy_hash="approval-hash",
        trade_plan_version="trade-v1",
        trade_plan_hash="trade-hash",
        replay_start=date(2024, 1, 1),
        replay_end=date(2024, 1, 3),
        transaction_cost_percent=Decimal("0.20"),
        slippage_percent=Decimal("0.10"),
        entry_validity_sessions=5,
        horizons=(20, 60, 120),
        source_hashes=MappingProxyType({"baseline": "hash"}),
    )
    return InstitutionalGateTruthReport(
        manifest=manifest,
        assessments=assessments,
        reason_statistics=reason_statistics(
            assessments,
            initial_capital=Decimal("1000000"),
        ),
        component_attribution=component_attribution(assessments),
        effectiveness=gate_effectiveness(
            assessments,
            initial_capital=Decimal("1000000"),
            counterfactual=counterfactual,
        ),
        counterfactual_trades=trades,
        counterfactual_curve=curve,
        counterfactual_statistics=counterfactual,
    )


__all__ = ["bars", "candidate"]
