from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from typer.testing import CliRunner

from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.cli import app
from alpha.forward_validation.models import (
    CounterfactualOperation,
    CounterfactualPolicy,
    PolicyStage,
    PolicyVersion,
)
from alpha.forward_validation.policy_versioning import PolicyVersionRegistry

runner = CliRunner()


def test_policy_versions_are_immutable_and_cannot_self_deploy(tmp_path) -> None:  # type: ignore[no-untyped-def]
    registry = PolicyVersionRegistry(tmp_path / "policies.json")
    candidate = CounterfactualPolicy(
        policy_version=PolicyVersion("APPROVAL_POLICY_V2"),
        operation=CounterfactualOperation.RELAX,
        changed_gate_ids=("stop_distance",),
        description="Relax to observed boundary.",
        parameters={"threshold": "15"},
    )

    assert registry.register(candidate) is True
    assert registry.register(candidate) is False
    registry.promote(candidate.policy_version, PolicyStage.FORWARD_VALIDATION)
    assert registry.register(candidate) is False
    with pytest.raises(ValueError, match="cannot activate or deploy"):
        registry.promote(
            candidate.policy_version,
            PolicyStage.CANDIDATE_FOR_DEPLOYMENT,
        )
    assert registry.current() == PolicyVersion("APPROVAL_POLICY_V1")


def test_forward_cli_start_performance_journal_and_readiness(tmp_path) -> None:  # type: ignore[no-untyped-def]
    registry = tmp_path / "forward.json"
    policies = tmp_path / "policies.json"
    start = runner.invoke(
        app,
        [
            "forward",
            "start",
            "--registry",
            str(registry),
            "--capital",
            "100000",
        ],
    )
    assert start.exit_code == 0, start.output
    assert "Evidence Mode: IMMUTABLE_FORWARD_ONLY" in start.output
    assert "Production Influence: false" in start.output

    performance = runner.invoke(
        app,
        ["forward", "performance", "--registry", str(registry)],
    )
    assert performance.exit_code == 0, performance.output
    assert "Forward Performance" in performance.output
    assert "APPROVAL_POLICY_V1" in performance.output

    journal = runner.invoke(
        app,
        ["forward", "journal", "--registry", str(registry)],
    )
    assert journal.exit_code == 0, journal.output
    assert "Immutable Recommendation Journal" in journal.output

    readiness = runner.invoke(
        app,
        [
            "forward",
            "deployment-readiness",
            "--registry",
            str(registry),
            "--policy-registry",
            str(policies),
        ],
    )
    assert readiness.exit_code == 0, readiness.output
    assert "Classification: NOT_READY" in readiness.output


def test_approval_cli_commands_render_one_unambiguous_recommendation(
    tmp_path, policy_evidence
) -> None:  # type: ignore[no-untyped-def]
    records, outcomes = policy_evidence
    ledger_path = tmp_path / "learning.json"
    ledger = LearningLedgerRepository(ledger_path)
    ledger.save_records(records)
    ledger.upsert_outcomes(outcomes)

    for command in (
        "approval-policy",
        "approval-optimizer",
        "approval-counterfactual",
    ):
        arguments = [
            "forward",
            command,
            "--learning-ledger",
            str(ledger_path),
        ]
        if command == "approval-optimizer":
            arguments.extend(["--policy-registry", str(tmp_path / "policies.json")])
        result = runner.invoke(app, arguments)
        assert result.exit_code == 0, result.output
        assert result.output.count("Recommendation:") == 1
        assert "Production Influence: false" in result.output


def test_all_forward_commands_are_registered() -> None:
    result = runner.invoke(app, ["forward", "--help"])
    assert result.exit_code == 0, result.output
    for command in (
        "start",
        "snapshot",
        "portfolio",
        "performance",
        "journal",
        "approval-policy",
        "approval-optimizer",
        "approval-counterfactual",
        "deployment-readiness",
    ):
        assert command in result.output


def test_forward_config_rejects_negative_capital(tmp_path) -> None:  # type: ignore[no-untyped-def]
    result = runner.invoke(
        app,
        [
            "forward",
            "start",
            "--registry",
            str(tmp_path / "forward.json"),
            "--capital",
            str(Decimal("-1")),
        ],
    )
    assert result.exit_code != 0
    assert "capital must be positive" in result.output


def test_policy_registry_timestamp_is_not_production_state(tmp_path) -> None:  # type: ignore[no-untyped-def]
    registry = PolicyVersionRegistry(tmp_path / "policies.json")
    candidate = CounterfactualPolicy(
        policy_version=PolicyVersion("APPROVAL_POLICY_V2"),
        operation=CounterfactualOperation.REMOVE,
        changed_gate_ids=("score",),
        description="test",
        parameters={},
        stage=PolicyStage.GENERATED,
    )
    registry.register(candidate)
    entry = registry.entries()[0]
    assert entry["production_influence"] == "False"
    assert datetime.fromisoformat(entry["registered_at"]).tzinfo is not None
    assert datetime.fromisoformat(entry["registered_at"]).astimezone(UTC)
