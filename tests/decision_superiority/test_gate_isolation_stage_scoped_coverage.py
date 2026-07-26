from __future__ import annotations

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


def _candidate(*, b10_present: bool) -> FrozenBaselineCandidate:
    return FrozenBaselineCandidate(
        candidate=FrozenCandidateKey("RAW", "2026-01-02", "AAA", "fp-a"),
        observed_failure_codes=("GATE_A",),
        resolved_outcome=True,
        outcome_status="RESOLVED",
        realized_return_pct=Decimal("5"),
        realized_r=Decimal("1"),
        b5_present=True,
        b7_present=False,
        b10_present=b10_present,
        dsi001_present=True,
    )


def _population(*, b10_present: bool) -> FrozenBaselinePopulation:
    return FrozenBaselinePopulation(
        candidates=(_candidate(b10_present=b10_present),),
        raw_candidate_count=1,
        adjusted_candidate_count=0,
        raw_adjusted_identity_mismatch_count=1,
    )


def _source_paths(root: Path) -> GateIsolationSourcePaths:
    paths = [root / f"source-{index}.csv" for index in range(18)]
    for path in paths:
        path.write_text("value\n1\n", encoding="utf-8")
    return GateIsolationSourcePaths(*paths)


def _baseline_paths(root: Path, *, b10_text: str) -> FrozenBaselineSourcePaths:
    placeholder = root / "placeholder.csv"
    placeholder.write_text("value\n1\n", encoding="utf-8")
    b10 = root / "b10.csv"
    b10.write_text(b10_text, encoding="utf-8")
    return FrozenBaselineSourcePaths(
        b5_candidate_ledger=placeholder,
        b7_outcome_ledger=placeholder,
        b10_decision_ledger=b10,
        dsi001_candidate_ledger=placeholder,
    )


def _patch_population(
    monkeypatch: pytest.MonkeyPatch,
    population: FrozenBaselinePopulation,
) -> None:
    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_orchestration."
        "GateIsolationSourceContractVerifier.verify",
        lambda self, paths: VerifiedGateIsolationSources((), ()),
    )
    monkeypatch.setattr(
        "alpha.decision_superiority.gate_isolation_orchestration."
        "FrozenBaselineReconstructor.reconstruct",
        lambda self, paths: population,
    )


def test_unreached_b10_candidate_uses_false_downstream_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_population(monkeypatch, _population(b10_present=False))
    result = GateIsolationDryRunOrchestrator().run(
        source_paths=_source_paths(tmp_path),
        baseline_paths=_baseline_paths(
            tmp_path,
            b10_text="price_view,observed_on,symbol\n",
        ),
    )

    baseline = next(
        item for item in result.transitions if item.arm.arm_type.value == "BASELINE"
    )
    assert baseline.baseline.approved is False
    assert baseline.baseline.trade_formed is False
    assert result.summary.candidate_count == 1


def test_extra_b10_downstream_identity_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_population(monkeypatch, _population(b10_present=False))
    text = (
        "price_view,observed_on,symbol,default_accepted\nRAW,2026-01-02,EXTRA,false\n"
    )
    with pytest.raises(ValueError, match="B10 downstream identity lineage mismatch"):
        GateIsolationDryRunOrchestrator().run(
            source_paths=_source_paths(tmp_path),
            baseline_paths=_baseline_paths(tmp_path, b10_text=text),
        )
