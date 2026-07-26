from __future__ import annotations

import csv
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pytest

from alpha.decision_superiority.gate_isolation_baseline import (
    FrozenBaselineCandidate,
    FrozenBaselinePopulation,
    FrozenBaselineSourcePaths,
)
from alpha.decision_superiority.gate_isolation_models import FrozenCandidateKey
from alpha.decision_superiority.gate_isolation_orchestration import (
    GateIsolationDryRunOrchestrator,
)
from alpha.decision_superiority.gate_isolation_source_contract import (
    GateIsolationSourcePaths,
    VerifiedGateIsolationSources,
)
from alpha.decision_superiority.gate_isolation_transitions import (
    StageEvaluation,
    StageEvaluationStatus,
)


@dataclass(slots=True)
class _RecordingEvaluator:
    calls: list[str] = field(default_factory=list)

    def evaluate(self, *, candidate, arm):
        self.calls.append(arm.arm_id)
        return StageEvaluation(
            approval=StageEvaluationStatus.PASSED,
            portfolio_eligibility=StageEvaluationStatus.PASSED,
            entry_readiness=StageEvaluationStatus.PASSED,
            trade_formation=StageEvaluationStatus.PASSED,
            outcome=StageEvaluationStatus.PASSED,
        )


def _candidate() -> FrozenBaselineCandidate:
    return FrozenBaselineCandidate(
        candidate=FrozenCandidateKey("RAW", "2026-01-02", "AAA", "fp-a"),
        observed_failure_codes=("GATE_A", "GATE_B"),
        resolved_outcome=True,
        outcome_status="RESOLVED",
        realized_return_pct=Decimal("5"),
        realized_r=Decimal("1"),
        b5_present=True,
        b7_present=True,
        b10_present=True,
        dsi001_present=True,
    )


def _population() -> FrozenBaselinePopulation:
    return FrozenBaselinePopulation(
        candidates=(_candidate(),),
        raw_candidate_count=1,
        adjusted_candidate_count=0,
        raw_adjusted_identity_mismatch_count=1,
    )


def _source_paths(root: Path) -> GateIsolationSourcePaths:
    files = [root / f"source-{index}.csv" for index in range(18)]
    for path in files:
        path.write_text("value\n1\n", encoding="utf-8")
    return GateIsolationSourcePaths(*files)


def _baseline_paths(root: Path) -> FrozenBaselineSourcePaths:
    b10 = root / "b10.csv"
    with b10.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "price_view",
                "observed_on",
                "symbol",
                "default_accepted",
                "default_portfolio_eligible",
                "default_entry_ready",
                "default_trade_formed",
                "default_outcome_available",
            ),
        )
        writer.writeheader()
        writer.writerow(
            {
                "price_view": "RAW",
                "observed_on": "2026-01-02",
                "symbol": "AAA",
                "default_accepted": "false",
                "default_portfolio_eligible": "false",
                "default_entry_ready": "false",
                "default_trade_formed": "false",
                "default_outcome_available": "false",
            }
        )
    placeholder = root / "placeholder.csv"
    placeholder.write_text("value\n1\n", encoding="utf-8")
    return FrozenBaselineSourcePaths(
        b5_candidate_ledger=placeholder,
        b7_outcome_ledger=placeholder,
        b10_decision_ledger=b10,
        dsi001_candidate_ledger=placeholder,
    )


def _patch_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_orchestration."
        "GateIsolationSourceContractVerifier.verify",
        lambda self, paths: VerifiedGateIsolationSources((), ()),
    )
    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_orchestration."
        "FrozenBaselineReconstructor.reconstruct",
        lambda self, paths: _population(),
    )


def test_injected_evaluator_runs_only_for_fully_cleared_nonbaseline_arm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inputs(monkeypatch)
    evaluator = _RecordingEvaluator()

    result = GateIsolationDryRunOrchestrator(stage_evaluator=evaluator).run(
        source_paths=_source_paths(tmp_path),
        baseline_paths=_baseline_paths(tmp_path),
    )

    assert len(evaluator.calls) == 1
    assert "MINIMAL_REMEDIATION_SET" in evaluator.calls[0]
    assert result.summary.newly_approved_count == 1
    assert result.summary.newly_trade_formed_count == 1
    assert result.summary.resolved_outcome_transition_count == 1


def test_default_evaluator_remains_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_inputs(monkeypatch)

    result = GateIsolationDryRunOrchestrator().run(
        source_paths=_source_paths(tmp_path),
        baseline_paths=_baseline_paths(tmp_path),
    )

    assert result.summary.newly_approved_count == 0
    assert result.summary.newly_trade_formed_count == 0
