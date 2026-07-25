from __future__ import annotations

import csv
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
    export_gate_isolation_dry_run,
)
from alpha.decision_superiority.gate_isolation_source_contract import (
    GateIsolationSourcePaths,
    VerifiedGateIsolationSources,
)
from alpha.decision_superiority.gate_isolation_transitions import (
    StageEvaluationStatus,
)


def _candidate() -> FrozenBaselineCandidate:
    return FrozenBaselineCandidate(
        candidate=FrozenCandidateKey("RAW", "2026-01-02", "AAA", "fp-a"),
        observed_failure_codes=("GATE_A",),
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
    files = [root / f"item-{index}.csv" for index in range(18)]
    for path in files:
        path.write_text("value\n1\n", encoding="utf-8")
    return GateIsolationSourcePaths(*files)


def _baseline_paths(
    root: Path,
    *,
    fingerprint: str | None = None,
) -> FrozenBaselineSourcePaths:
    b10 = root / "b10.csv"
    fieldnames = [
        "price_view",
        "observed_on",
        "symbol",
        "default_accepted",
        "default_portfolio_eligible",
        "default_entry_ready",
        "default_trade_formed",
        "default_outcome_available",
    ]
    if fingerprint is not None:
        fieldnames.append("input_fingerprint")
    row = {
        "price_view": "RAW",
        "observed_on": "2026-01-02",
        "symbol": "AAA",
        "default_accepted": "false",
        "default_portfolio_eligible": "false",
        "default_entry_ready": "false",
        "default_trade_formed": "false",
        "default_outcome_available": "false",
    }
    if fingerprint is not None:
        row["input_fingerprint"] = fingerprint
    with b10.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(row)
    placeholder = root / "placeholder.csv"
    placeholder.write_text("value\n1\n", encoding="utf-8")
    return FrozenBaselineSourcePaths(
        b5_candidate_ledger=placeholder,
        b7_outcome_ledger=placeholder,
        b10_decision_ledger=b10,
        dsi001_candidate_ledger=placeholder,
    )


def _patch_governed_inputs(monkeypatch: pytest.MonkeyPatch) -> None:
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


def test_orchestrator_bridges_b10_without_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_governed_inputs(monkeypatch)

    result = GateIsolationDryRunOrchestrator().run(
        source_paths=_source_paths(tmp_path),
        baseline_paths=_baseline_paths(tmp_path),
    )

    assert result.summary.candidate_count == 1
    assert result.summary.single_gate_arm_count == 1
    assert result.summary.effective_single_gate_arm_count == 0
    assert result.summary.minimal_remediation_arm_count == 1
    assert result.summary.newly_approved_count == 0
    assert result.summary.newly_trade_formed_count == 0
    assert result.summary.resolved_outcome_transition_count == 0
    assert result.summary.production_influence is False
    clear_arms = [
        item
        for item in result.transitions
        if item.arm.clears_all_observed_failures
        and item.arm.arm_type.value != "BASELINE"
    ]
    assert clear_arms
    assert all(
        item.stage_evaluation.approval is StageEvaluationStatus.UNAVAILABLE
        for item in clear_arms
    )
    assert tuple(item.arm.arm_id for item in result.transitions) == tuple(
        sorted(item.arm.arm_id for item in result.transitions)
    )


def test_export_is_deterministic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_governed_inputs(monkeypatch)
    result = GateIsolationDryRunOrchestrator().run(
        source_paths=_source_paths(tmp_path),
        baseline_paths=_baseline_paths(tmp_path),
    )

    first = export_gate_isolation_dry_run(result, tmp_path / "first")
    second = export_gate_isolation_dry_run(result, tmp_path / "second")

    assert tuple(path.read_bytes() for path in first) == tuple(
        path.read_bytes() for path in second
    )


def test_missing_b10_state_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_governed_inputs(monkeypatch)
    paths = _baseline_paths(tmp_path)
    paths.b10_decision_ledger.write_text(
        "price_view,observed_on,symbol\n",
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError, match="B10 downstream state missing for covered candidate"
    ):
        GateIsolationDryRunOrchestrator().run(
            source_paths=_source_paths(tmp_path),
            baseline_paths=paths,
        )


def test_b10_downstream_fingerprint_conflict_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_governed_inputs(monkeypatch)

    with pytest.raises(ValueError, match="B10 downstream fingerprint mismatch"):
        GateIsolationDryRunOrchestrator().run(
            source_paths=_source_paths(tmp_path),
            baseline_paths=_baseline_paths(tmp_path, fingerprint="wrong"),
        )
