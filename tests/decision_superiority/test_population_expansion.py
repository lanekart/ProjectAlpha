from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType

import pytest
import typer
from typer.testing import CliRunner

from alpha.application.decision_superiority_population_expansion_cli import (
    register_decision_superiority_population_expansion_command,
)
from alpha.decision_superiority import population_expansion as module
from alpha.decision_superiority import population_expansion_artifacts as artifact_module
from alpha.decision_superiority.population_expansion import (
    GovernedPopulationExpansionEngine,
    classify_outcome,
    concentration,
    effective_number,
    stable_identity,
    structural_probe_rows,
)
from alpha.decision_superiority.population_expansion_artifacts import (
    DSI003_ARTIFACTS,
    DSI003_CERTIFICATE,
    DSI003_REPORT,
    export_population_expansion,
    validate_population_expansion_certificate,
)
from alpha.decision_superiority.population_expansion_models import (
    PopulationExpansionError,
    PopulationExpansionResult,
    PopulationExpansionSourcePaths,
)


def test_economic_identity_is_stable_and_input_sensitive() -> None:
    first = stable_identity("BEL", "2026-07-26", "policy", "capture")
    assert first == stable_identity("BEL", "2026-07-26", "policy", "capture")
    assert first != stable_identity("BEL", "2026-07-25", "policy", "capture")


def test_effective_number_and_concentration_use_known_values_only() -> None:
    top, hhi = concentration(("A", "A", "B", "UNKNOWN"))
    assert str(top) == "0.6667"
    assert str(hhi) == "0.5556"
    assert str(effective_number(("A", "A", "B", "UNKNOWN"))) == "1.8000"
    assert effective_number(("UNKNOWN",)) == 0


@pytest.mark.parametrize(
    ("status", "expected"),
    (
        ("COMPLETED_WIN", "COMPLETED_COMPARABLE_OUTCOME"),
        ("COMPLETED_LOSS_OR_FLAT", "COMPLETED_COMPARABLE_OUTCOME"),
        ("NOT_ENTERED", "NOT_ENTERED"),
        ("PENDING_END_OF_DATA", "PENDING_END_OF_DATA"),
        ("", "MISSING_OUTCOME"),
    ),
)
def test_outcome_classification(status: str, expected: str) -> None:
    assert classify_outcome({"forward_outcome_status": status}) == expected


def test_missing_outcome_is_not_fabricated() -> None:
    assert classify_outcome(None) == "MISSING_OUTCOME"


def test_structural_probes_are_excluded_from_empirical_counts() -> None:
    rows = structural_probe_rows()
    assert len(rows) == 22
    assert all(row["included_in_empirical_counts"] is False for row in rows)
    assert {row["probe_id"] for row in rows} >= {
        "RAW_ADJUSTED_PAIR",
        "CONFLICTING_TERMINAL",
        "DSI002_BATCH_SUCCESS",
        "CERTIFICATE_TAMPER",
    }


def test_engine_pairs_arms_and_preserves_exact_dsi002_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle()
    monkeypatch.setattr(
        module, "_verify_source_chain", lambda *_args, **_kwargs: bundle
    )
    monkeypatch.setattr(module, "_source_commit", lambda _root: "a" * 40)

    result = GovernedPopulationExpansionEngine().run(
        sources=_paths(),
        project_root=Path("."),
    )

    assert result.summaries["candidate_arm_count"] == 3
    assert result.summaries["unique_economic_candidate_count"] == 2
    assert result.summaries["completed_outcome_count"] == 1
    assert result.summaries["exact_dsi002_candidate_count"] == 1
    assert result.readiness["I"] == "READY_FOR_DESCRIPTIVE_DSI_RESEARCH_ONLY"
    assert len(result.rows["complete_stack_stages"]) == 24
    assert sum(int(row["arm_count"]) for row in result.rows["economic_identity"]) == 3


def test_conflicting_terminal_decision_blocks_population(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(adjusted_terminal="ACCEPT")
    monkeypatch.setattr(
        module, "_verify_source_chain", lambda *_args, **_kwargs: bundle
    )
    monkeypatch.setattr(module, "_source_commit", lambda _root: "a" * 40)
    with pytest.raises(
        PopulationExpansionError,
        match="CONFLICTING_TERMINAL_DECISION",
    ):
        GovernedPopulationExpansionEngine().run(
            sources=_paths(),
            project_root=Path("."),
        )


def test_conflicting_raw_adjusted_outcome_blocks_population(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _bundle(adjusted_outcome="NOT_ENTERED")
    monkeypatch.setattr(
        module, "_verify_source_chain", lambda *_args, **_kwargs: bundle
    )
    monkeypatch.setattr(module, "_source_commit", lambda _root: "a" * 40)
    with pytest.raises(
        PopulationExpansionError,
        match="RAW_ADJUSTED_OUTCOME_CONFLICT",
    ):
        GovernedPopulationExpansionEngine().run(
            sources=_paths(),
            project_root=Path("."),
        )


def test_missing_signed_source_blocks_before_population_assembly() -> None:
    with pytest.raises(PopulationExpansionError, match="SOURCE_CHAIN_INVALID"):
        GovernedPopulationExpansionEngine().run(
            sources=_paths(),
            project_root=Path("."),
        )


def test_export_is_deterministic_and_contains_exactly_21_files(
    tmp_path: Path,
) -> None:
    first = export_population_expansion(_result(), tmp_path / "first")
    second = export_population_expansion(_result(), tmp_path / "second")
    assert len(first) == 21
    assert {path.name for path in first} == {
        DSI003_CERTIFICATE,
        DSI003_REPORT,
        *DSI003_ARTIFACTS.values(),
    }
    assert {path.name: path.read_bytes() for path in first} == {
        path.name: path.read_bytes() for path in second
    }


def test_certificate_verifies_ready_governance_and_report(tmp_path: Path) -> None:
    paths = export_population_expansion(_result(), tmp_path)
    certificate = next(path for path in paths if path.name == DSI003_CERTIFICATE)
    payload = validate_population_expansion_certificate(
        certificate,
        require_ready=True,
    )
    assert payload["readiness_decision"] == ("READY_FOR_DESCRIPTIVE_DSI_RESEARCH_ONLY")
    assert payload["governance_flags"]["PRODUCTION_INFLUENCE"] is False
    assert payload["governance_flags"]["THRESHOLD_CHANGE_PERMITTED"] is False


def test_artifact_tampering_is_rejected(tmp_path: Path) -> None:
    export_population_expansion(_result(), tmp_path)
    artifact = tmp_path / DSI003_ARTIFACTS["candidate_reconstruction"]
    artifact.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(PopulationExpansionError, match="ARTIFACT_TAMPERED"):
        validate_population_expansion_certificate(tmp_path / DSI003_CERTIFICATE)


def test_certificate_substitution_and_unsafe_paths_are_rejected(
    tmp_path: Path,
) -> None:
    export_population_expansion(_result(), tmp_path)
    certificate = tmp_path / DSI003_CERTIFICATE
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    manifest = payload["support_artifact_manifest"]
    manifest["../escape.csv"] = manifest.pop(next(iter(manifest)))
    payload["report_sha256"] = artifact_module._report_sha256(payload)
    certificate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PopulationExpansionError, match="SUPPORT_MANIFEST"):
        validate_population_expansion_certificate(certificate)


def test_contract_and_governance_substitution_are_rejected(tmp_path: Path) -> None:
    export_population_expansion(_result(), tmp_path)
    certificate = tmp_path / DSI003_CERTIFICATE
    original = json.loads(certificate.read_text(encoding="utf-8"))

    contract = dict(original)
    contract["contract_version"] = "DSI-003-v0"
    certificate.write_text(json.dumps(contract), encoding="utf-8")
    with pytest.raises(PopulationExpansionError, match="UNSUPPORTED"):
        validate_population_expansion_certificate(certificate)

    governance = dict(original)
    governance["governance_flags"] = dict(governance["governance_flags"])
    governance["governance_flags"]["PRODUCTION_INFLUENCE"] = True
    governance["report_sha256"] = artifact_module._report_sha256(governance)
    certificate.write_text(json.dumps(governance), encoding="utf-8")
    with pytest.raises(PopulationExpansionError, match="GOVERNANCE"):
        validate_population_expansion_certificate(certificate)


def test_portable_artifacts_contain_no_machine_local_paths(tmp_path: Path) -> None:
    paths = export_population_expansion(_result(), tmp_path)
    content = b"\n".join(path.read_bytes() for path in paths)
    assert b"/Users/" not in content
    assert b"ProjectAlpha" not in content


def test_cli_verifier_renders_singular_readiness(tmp_path: Path) -> None:
    export_population_expansion(_result(), tmp_path)
    app = typer.Typer()
    register_decision_superiority_population_expansion_command(app)
    result = CliRunner().invoke(
        app,
        [
            "decision-superiority-population-expansion-verify",
            "--certificate",
            str(tmp_path / DSI003_CERTIFICATE),
            "--require-ready",
        ],
    )
    assert result.exit_code == 0
    assert "Certificate: VALID" in result.stdout
    assert result.stdout.count("Readiness:") == 1


def test_result_rejects_unsorted_or_duplicate_blockers() -> None:
    with pytest.raises(ValueError, match="blockers"):
        PopulationExpansionResult(
            source_commit="a" * 40,
            readiness=MappingProxyType({"A": "READY"}),
            summaries=MappingProxyType({}),
            rows=MappingProxyType({}),
            blockers=("X", "X"),
        )


def _paths() -> PopulationExpansionSourcePaths:
    missing = Path("not-read-by-monkeypatched-source-verifier")
    return PopulationExpansionSourcePaths(
        b5_certificate=missing,
        b7_certificate=missing,
        b10_certificate=missing,
        dsi001_certificate=missing,
        dsi002a_certificate=missing,
        dsi002d1_certificate=missing,
        dsi002b2_certificate=missing,
        dsi002c2_certificate=missing,
        dsi002d2_certificate=missing,
        dsi002_certificate=missing,
    )


def _bundle(
    *,
    adjusted_terminal: str = "REJECT",
    adjusted_outcome: str = "COMPLETED_WIN",
) -> module._SourceBundle:
    b5_rows = (
        _b5_row("RAW", "raw-fingerprint", "REJECT"),
        _b5_row("ADJUSTED", "adjusted-fingerprint", adjusted_terminal),
    )
    dsi_rows = tuple(
        {
            "price_view": row["price_view"],
            "observed_on": row["observed_on"],
            "symbol": row["symbol"],
            "input_fingerprint": row["input_fingerprint"],
            "failure_count": "1",
            "failure_codes": "WEAK_VERDICT",
            "unique_blocker": "True",
            "resolved_outcome": "True",
            "won": "True",
            "realized_return_pct": "5",
            "realized_r": "1",
        }
        for row in b5_rows
    )
    b7_rows = (
        _b7_row("RAW", "COMPLETED_WIN"),
        _b7_row("ADJUSTED", adjusted_outcome),
    )
    sources = tuple(
        module._VerifiedSource(
            source_id=source,
            certificate=Path(f"{source}.json"),
            contract_version=f"{source}-v1",
            readiness="READY",
            report_sha256=source.lower().ljust(64, "0")[:64],
            certificate_sha256=source.lower().ljust(64, "1")[:64],
            candidate_rows=(
                2 if source in {"B5", "DSI001"} else 2 if source == "B7" else 1
            ),
            admissibility="ADMISSIBLE",
            exclusion_reason="",
        )
        for source in (
            "B5",
            "B7",
            "B10",
            "DSI001",
            "DSI002",
            "DSI002A",
            "DSI002B2",
            "DSI002C2",
            "DSI002D1",
            "DSI002D2",
        )
    )
    return module._SourceBundle(
        sources=sources,
        b5_payload={"institutional_policy_source_sha256s": {"policy": "frozen"}},
        b5_candidates=b5_rows,
        b5_gates=(),
        b7_outcomes=b7_rows,
        dsi001_candidates=dsi_rows,
        dsi002_candidate_identity="RAW|2026-07-26|BEL|bel-fingerprint",
        dsi002_events=tuple(
            {
                "stage_order": str(index),
                "stage_id": f"stage_{index}",
                "stage_invoked": "true",
                "invocation_count": "1",
                "result_state": "PASS" if index == 1 else "FAIL",
                "result_code": "RECORDED",
                "observation_mode": "CANONICAL_GOVERNED_COMPLETE_STACK",
            }
            for index in range(1, 7)
        ),
        dsi002_baseline=_bel_baseline(),
        dsi002_eligibility=(
            {"eligibility": "OVERRIDE_ELIGIBLE"},
            {"eligibility": "MULTI_CONDITION_EVALUATOR_NOT_ISOLATABLE"},
        ),
        dsi002_search=({"target_reached": "false"},),
        dsi002_funnel=(
            {
                "institutionally_approved": "false",
                "trade_formed": "false",
            },
        ),
        dsi002_outcomes=({"completed_outcome": "false"},),
    )


def _b5_row(
    price_view: str,
    fingerprint: str,
    terminal: str,
) -> dict[str, str]:
    return {
        "price_view": price_view,
        "observed_on": "2026-01-02",
        "symbol": "AAA",
        "rank": "1",
        "final_signal": "BUY",
        "recommendation_score": "80",
        "setup_stage": "ENTRY_READY",
        "base_gate_decision": "REJECT",
        "stress_stage_reached": "false",
        "trade_plan_stage_reached": "false",
        "institutional_approved": str(terminal == "ACCEPT").lower(),
        "portfolio_eligible": "false",
        "input_fingerprint": fingerprint,
    }


def _b7_row(price_view: str, status: str) -> dict[str, str]:
    return {
        "price_view": price_view,
        "observed_on": "2026-01-02",
        "symbol": "AAA",
        "setup_type": "BREAKOUT",
        "forward_outcome_status": status,
        "entered": "true",
        "completed": "true",
        "won": "true",
        "realized_return_pct": "5",
        "realized_r": "1",
        "holding_period_days": "5",
        "exit_reason": "TARGET",
    }


def _bel_baseline() -> dict[str, object]:
    payload = {
        "recommendations": [
            {
                "symbol": "BEL",
                "rank": 1,
                "decision": "WATCHLIST",
                "score": "62",
                "explanation": ["Setup Stage: BUILDING"],
            }
        ],
        "institutional": {
            "traces": [
                {
                    "base_decision": {"accepted": False},
                    "stress_applicable": False,
                    "trade_plan_applicable": False,
                    "terminal_institutional_decision": "REJECT",
                }
            ]
        },
    }
    return {
        "candidate_identity": "RAW|2026-07-26|BEL|bel-fingerprint",
        "output_payload_json": json.dumps(payload),
    }


def _result() -> PopulationExpansionResult:
    readiness = MappingProxyType(
        {
            "A": "READY_FOR_GOVERNED_POPULATION_ASSEMBLY",
            "B": "READY_FOR_GOVERNED_COMPLETE_STACK_POPULATION",
            "C": "READY_FOR_GOVERNED_POPULATION_BOTTLENECK_RESEARCH",
            "D": "READY_WITH_DEPENDENCE_WARNINGS",
            "E": "READY_WITH_LIMITED_EXTERNAL_VALIDITY",
            "F": "READY_WITH_LIMITED_OUTCOME_COVERAGE",
            "G": "READY_WITH_PARTIAL_DSI002_TRANSFERABILITY",
            "H": "READY_FOR_GOVERNED_POPULATION_SUFFICIENCY_CONCLUSION",
            "I": "READY_FOR_DESCRIPTIVE_DSI_RESEARCH_ONLY",
        }
    )
    summaries = {
        "admissible_source_count": 4,
        "allocation_count": 0,
        "approval_count": 0,
        "candidate_arm_count": 3,
        "completed_outcome_count": 1,
        "conflicting_record_count": 0,
        "coverage_grade": "LIMITED_REGIME_COVERAGE",
        "duplicate_rows_removed": 2,
        "effective_date_count": "2",
        "effective_security_count": "2",
        "exact_dsi002_candidate_count": 1,
        "flat_count": 0,
        "implementation_defect_count": 0,
        "incompatible_source_count": 0,
        "leakage_count": 0,
        "loss_count": 0,
        "missing_lineage_count": 0,
        "pending_outcome_count": 0,
        "plan_count": 1,
        "recorded_stage_candidate_count": 1,
        "research_sufficiency_tier": "SUFFICIENT_FOR_DESCRIPTIVE_GATE_VALUE",
        "sector_count": 1,
        "security_count": 2,
        "setup_count": 2,
        "source_count": 10,
        "source_row_count": 5,
        "top_date_share": "0.5",
        "top_security_share": "0.5",
        "unique_date_count": 2,
        "unique_economic_candidate_count": 2,
        "unique_regime_count": 1,
        "unexplained_divergence_count": 0,
        "win_count": 1,
    }
    row = MappingProxyType({"id": "ROW", "state": "KNOWN"})
    rows = {key: (row,) for key in sorted(DSI003_ARTIFACTS)}
    rows["source_contract"] = (
        MappingProxyType(
            {
                "source_id": "B5",
                "contract_version": "HTR-010B5-v1.0.0",
                "certificate_sha256": "a" * 64,
                "report_sha256": "b" * 64,
                "readiness": "READY",
            }
        ),
    )
    return PopulationExpansionResult(
        source_commit="c" * 40,
        readiness=readiness,
        summaries=MappingProxyType(dict(sorted(summaries.items()))),
        rows=MappingProxyType(dict(sorted(rows.items()))),
        blockers=(),
    )
