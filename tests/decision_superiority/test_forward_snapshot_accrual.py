from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.application.intelligence import IntelligenceApplicationService
from alpha.decision_intelligence import InstitutionalDecisionEngine
from alpha.decision_superiority.forward_snapshot_accrual import (
    GovernedForwardSnapshotAccrualEngine,
    governance_flags,
    structural_probe_rows,
)
from alpha.decision_superiority.forward_snapshot_artifacts import (
    DSI006_ARTIFACTS,
    DSI006_CERTIFICATE,
    DSI006_EVENTS,
    DSI006_REPORT,
    export_forward_snapshot_accrual,
    validate_forward_snapshot_certificate,
)
from alpha.decision_superiority.forward_snapshot_models import (
    CaptureSessionState,
    ForwardSnapshotError,
    ForwardSnapshotSourcePaths,
    OutcomeEventType,
    RepositoryDisposition,
    SliceReadiness,
)
from alpha.decision_superiority.forward_snapshot_repository import (
    ContentAddressedSnapshotRepository,
    GovernedForwardSnapshotRecorder,
)
from alpha.decision_superiority.historical_rehydration import (
    canonical_json,
    stable_sha256,
)
from alpha.decision_superiority.recommendation_snapshot_recorder import (
    replay_snapshot_package,
    validate_snapshot_package,
)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_DSI005_CERTIFICATE = (
    _PROJECT_ROOT
    / "artifacts/dsi005_acceptance/20260726T112316Z/run_a"
    / "dsi005_replay_retention_certificate.json"
)
_SESSION_DATE = date(2026, 7, 26)


class _FakeHistoricalTruthStore:
    def __init__(self, **_: object) -> None:
        self.frame = _raw_frame()

    def __enter__(self) -> _FakeHistoricalTruthStore:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def find_by_trade_date(self, trade_date: date) -> pd.DataFrame:
        assert trade_date == _SESSION_DATE
        return self.frame.copy()

    def find_history_by_symbols(
        self,
        *,
        symbols: tuple[str, ...],
        end_date: date,
        limit: int,
    ) -> pd.DataFrame:
        assert end_date == _SESSION_DATE
        assert limit == 250
        return self.frame[self.frame["symbol"].isin(symbols)].copy()


def _raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "symbol": "ALPHAONE",
                "trade_date": _SESSION_DATE,
                "open": 100.0,
                "high": 108.0,
                "low": 99.0,
                "close": 107.0,
                "volume": 1_500_000,
                "sector": "Industrials",
                "exchange": "NSE",
            },
            {
                "symbol": "ALPHATWO",
                "trade_date": _SESSION_DATE,
                "open": 200.0,
                "high": 204.0,
                "low": 196.0,
                "close": 202.0,
                "volume": 900_000,
                "sector": "Technology",
                "exchange": "NSE",
            },
            {
                "symbol": "ALPHATHREE",
                "trade_date": _SESSION_DATE,
                "open": 80.0,
                "high": 81.0,
                "low": 75.0,
                "close": 76.0,
                "volume": 600_000,
                "sector": "Financials",
                "exchange": "NSE",
            },
        ]
    )


def _capture(repository: ContentAddressedSnapshotRepository) -> Path:
    recorder = GovernedForwardSnapshotRecorder(repository)
    IntelligenceApplicationService(
        institutional_engine=InstitutionalDecisionEngine(),
        governed_institutional_evaluation_enabled=True,
        governed_recommendation_snapshot_recorder=recorder,
        governed_recommendation_snapshot_capture_enabled=True,
    ).run(observed_on=_SESSION_DATE)
    return repository.package_paths()[0]


@pytest.fixture()
def captured_repository(
    tmp_path: Path,
) -> ContentAddressedSnapshotRepository:
    repository = ContentAddressedSnapshotRepository(tmp_path / "repository")
    _capture(repository)
    return repository


@pytest.fixture()
def governed_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        "alpha.decision_superiority.forward_snapshot_accrual."
        "HistoricalTruthReplayStore",
        _FakeHistoricalTruthStore,
    )
    return GovernedForwardSnapshotAccrualEngine().run(
        sources=ForwardSnapshotSourcePaths(
            dsi005_certificate=_DSI005_CERTIFICATE,
            database=tmp_path / "historical_truth.duckdb",
            historical_truth_snapshots=tmp_path / "snapshots",
            capture_root=tmp_path / "capture",
            project_root=_PROJECT_ROOT,
        ),
        session_date=_SESSION_DATE,
    )


def test_governance_flags_are_all_false() -> None:
    flags = governance_flags()
    assert flags
    assert not any(flags.values())
    assert flags["DEFAULT_SNAPSHOT_CAPTURE_ENABLED"] is False
    assert flags["PRODUCTION_SNAPSHOT_WRITES_ENABLED"] is False
    assert flags["PRODUCTION_INFLUENCE"] is False


def test_default_application_capture_remains_disabled(tmp_path: Path) -> None:
    IntelligenceApplicationService().run(observed_on=_SESSION_DATE)
    assert tuple(tmp_path.iterdir()) == ()


def test_enabled_capture_without_recorder_fails_closed() -> None:
    with pytest.raises(ValueError, match="requires an injected recorder"):
        IntelligenceApplicationService(
            governed_recommendation_snapshot_capture_enabled=True
        )


def test_new_package_is_published_atomically(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    paths = captured_repository.package_paths()
    assert len(paths) == 1
    assert paths[0].stem == validate_snapshot_package(paths[0])["package_sha256"]
    assert not captured_repository.temporary.exists() or not tuple(
        captured_repository.temporary.iterdir()
    )


def test_identical_repeat_is_idempotent(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    before = captured_repository.verify_inventory()
    _capture(captured_repository)
    after = captured_repository.verify_inventory()
    assert after == before


def test_conflicting_repeat_fails_closed(
    captured_repository: ContentAddressedSnapshotRepository,
    tmp_path: Path,
) -> None:
    original = captured_repository.package_paths()[0]
    payload = validate_snapshot_package(original)
    payload["outcome_links"] = [{"state": "CONFLICT_PROBE"}]
    body = dict(payload)
    body.pop("package_sha256")
    payload["package_sha256"] = stable_sha256(body)
    conflict = tmp_path / "conflict.json"
    conflict.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    with pytest.raises(
        ForwardSnapshotError,
        match="CONFLICTING_CAPTURE_FOR_SAME_CANDIDATE_ARM",
    ):
        captured_repository.publish_package(conflict)
    assert len(captured_repository.package_paths()) == 1


def test_invalid_package_is_rejected(
    captured_repository: ContentAddressedSnapshotRepository,
    tmp_path: Path,
) -> None:
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"contract_version":"wrong"}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        captured_repository.publish_package(invalid)


def test_package_secret_field_is_rejected(
    captured_repository: ContentAddressedSnapshotRepository,
    tmp_path: Path,
) -> None:
    payload = validate_snapshot_package(captured_repository.package_paths()[0])
    payload["client_secret"] = "must-never-persist"
    body = dict(payload)
    body.pop("package_sha256")
    payload["package_sha256"] = stable_sha256(body)
    secret = tmp_path / "secret.json"
    secret.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="SECRET_FIELD_REJECTED"):
        captured_repository.publish_package(secret)


def test_index_rebuild_is_deterministic(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    first = captured_repository.rebuild_index()
    first_bytes = captured_repository.index_path.read_bytes()
    second = captured_repository.rebuild_index()
    assert second == first
    assert captured_repository.index_path.read_bytes() == first_bytes


def test_stale_temporary_files_are_recovered(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    captured_repository.temporary.mkdir(parents=True, exist_ok=True)
    stale = captured_repository.temporary / "stale.tmp"
    stale.write_text("partial", encoding="utf-8")
    assert captured_repository.recover_stale_temporary_files() == 1
    assert not stale.exists()


def test_disk_space_preflight_fails_closed(tmp_path: Path) -> None:
    repository = ContentAddressedSnapshotRepository(
        tmp_path / "repository",
        minimum_free_bytes=10**30,
    )
    staging = ContentAddressedSnapshotRepository(tmp_path / "source")
    package = _capture(staging)
    with pytest.raises(ForwardSnapshotError, match="DISK_SPACE"):
        repository.publish_package(package)


def test_capture_path_traversal_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ForwardSnapshotError, match="PATH_TRAVERSAL"):
        ContentAddressedSnapshotRepository(tmp_path / ".." / "unsafe")


def test_index_detects_package_tampering(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    package = captured_repository.package_paths()[0]
    original = package.read_bytes()
    package.write_bytes(original + b" ")
    with pytest.raises(ValueError):
        captured_repository.verify_inventory()


def test_plan_and_pending_events_are_append_only(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    row = captured_repository.index_rows()[0]
    package_before = captured_repository.package_paths()[0].read_bytes()
    plan, plan_state = captured_repository.append_outcome_event(
        candidate_arm_id=row.candidate_arm_id,
        event_type=OutcomeEventType.PLAN_RECORDED,
        observation_date=row.session_date,
        effective_date=row.session_date,
        completion_date=None,
        source_lineage="TEST_PLAN",
        source_hash=row.recorded_plan_id,
    )
    pending, pending_state = captured_repository.append_outcome_event(
        candidate_arm_id=row.candidate_arm_id,
        event_type=OutcomeEventType.ENTRY_PENDING,
        observation_date=row.session_date,
        effective_date=row.session_date,
        completion_date=None,
        source_lineage="TEST_PENDING",
        source_hash=plan.payload_hash,
        predecessor_event_id=plan.event_id,
    )
    assert plan_state is RepositoryDisposition.NEW
    assert pending_state is RepositoryDisposition.NEW
    assert pending.predecessor_event_id == plan.event_id
    assert captured_repository.package_paths()[0].read_bytes() == package_before


def test_identical_event_is_idempotent(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    row = captured_repository.index_rows()[0]
    arguments = {
        "candidate_arm_id": row.candidate_arm_id,
        "event_type": OutcomeEventType.ENTRY_PENDING,
        "observation_date": row.session_date,
        "effective_date": row.session_date,
        "completion_date": None,
        "source_lineage": "TEST",
        "source_hash": "source",
    }
    first, first_state = captured_repository.append_outcome_event(**arguments)
    second, second_state = captured_repository.append_outcome_event(**arguments)
    assert first == second
    assert first_state is RepositoryDisposition.NEW
    assert second_state is RepositoryDisposition.IDENTICAL


def test_future_event_before_recommendation_is_blocked(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    row = captured_repository.index_rows()[0]
    with pytest.raises(ForwardSnapshotError, match="POINT_IN_TIME_OUTCOME_LEAKAGE"):
        captured_repository.append_outcome_event(
            candidate_arm_id=row.candidate_arm_id,
            event_type=OutcomeEventType.OUTCOME_COMPLETED,
            observation_date=date(2026, 7, 25),
            effective_date=date(2026, 7, 25),
            completion_date=date(2026, 7, 25),
            source_lineage="INVALID",
            source_hash="invalid",
        )


def test_same_date_terminal_outcome_is_blocked(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    row = captured_repository.index_rows()[0]
    with pytest.raises(
        ForwardSnapshotError,
        match="SAME_DATE_TERMINAL_OUTCOME_INVALID",
    ):
        captured_repository.append_outcome_event(
            candidate_arm_id=row.candidate_arm_id,
            event_type=OutcomeEventType.OUTCOME_COMPLETED,
            observation_date=row.session_date,
            effective_date=row.session_date,
            completion_date=row.session_date,
            source_lineage="IMPOSSIBLE_SAME_DATE",
            source_hash="invalid",
        )


def test_wrong_candidate_identity_is_blocked(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    with pytest.raises(ForwardSnapshotError, match="CANDIDATE_IDENTITY_DEFECT"):
        captured_repository.append_outcome_event(
            candidate_arm_id="unknown",
            event_type=OutcomeEventType.ENTRY_PENDING,
            observation_date=_SESSION_DATE,
            effective_date=_SESSION_DATE,
            completion_date=None,
            source_lineage="INVALID",
            source_hash="invalid",
        )


def test_conflicting_terminal_events_are_blocked(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    row = captured_repository.index_rows()[0]
    captured_repository.append_outcome_event(
        candidate_arm_id=row.candidate_arm_id,
        event_type=OutcomeEventType.ENTRY_NOT_TRIGGERED,
        observation_date=date(2026, 7, 27),
        effective_date=date(2026, 7, 27),
        completion_date=date(2026, 7, 27),
        source_lineage="EXPIRY",
        source_hash="expiry",
    )
    with pytest.raises(ForwardSnapshotError, match="CONFLICTING_OUTCOME_EVENTS"):
        captured_repository.append_outcome_event(
            candidate_arm_id=row.candidate_arm_id,
            event_type=OutcomeEventType.OUTCOME_COMPLETED,
            observation_date=date(2026, 7, 28),
            effective_date=date(2026, 7, 28),
            completion_date=date(2026, 7, 28),
            source_lineage="CONFLICT",
            source_hash="conflict",
        )


def test_outcome_correction_references_existing_event(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    row = captured_repository.index_rows()[0]
    terminal, _ = captured_repository.append_outcome_event(
        candidate_arm_id=row.candidate_arm_id,
        event_type=OutcomeEventType.OUTCOME_COMPLETED,
        observation_date=date(2026, 7, 27),
        effective_date=date(2026, 7, 27),
        completion_date=date(2026, 7, 27),
        source_lineage="OUTCOME",
        source_hash="outcome",
    )
    correction, _ = captured_repository.append_outcome_event(
        candidate_arm_id=row.candidate_arm_id,
        event_type=OutcomeEventType.OUTCOME_CORRECTION,
        observation_date=date(2026, 7, 28),
        effective_date=date(2026, 7, 28),
        completion_date=date(2026, 7, 28),
        source_lineage="CORRECTION",
        source_hash="correction",
        predecessor_event_id=terminal.event_id,
    )
    assert correction.predecessor_event_id == terminal.event_id


def test_event_tampering_is_detected(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    row = captured_repository.index_rows()[0]
    event, _ = captured_repository.append_outcome_event(
        candidate_arm_id=row.candidate_arm_id,
        event_type=OutcomeEventType.ENTRY_PENDING,
        observation_date=row.session_date,
        effective_date=row.session_date,
        completion_date=None,
        source_lineage="TEST",
        source_hash="source",
    )
    event_path = captured_repository.events / f"{event.event_id}.json"
    payload = json.loads(event_path.read_text(encoding="utf-8"))
    payload["source_hash"] = "tampered"
    event_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ForwardSnapshotError, match="EVENT_TAMPERED"):
        captured_repository.outcome_events()


def test_full_snapshot_replay_has_complete_stack_parity(
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    result = replay_snapshot_package(captured_repository.package_paths()[0])
    assert result.input_parity is True
    assert result.recommendation_parity is True
    assert result.fingerprint_parity is True
    assert result.complete_stack_parity is True
    assert result.plan_identity_parity is True


def test_snapshot_replay_accepts_midnight_iso_date_values(
    captured_repository: ContentAddressedSnapshotRepository,
    tmp_path: Path,
) -> None:
    payload = validate_snapshot_package(captured_repository.package_paths()[0])
    stock = payload["input_snapshot"]["stock"]
    stock["observed_on"] = f"{stock['observed_on']}T00:00:00"
    payload["capture_id"] = stable_sha256(
        {
            "contract": payload["contract_version"],
            "observed_on": payload["observed_on"],
            "inputs": payload["input_snapshot"],
        }
    )
    body = dict(payload)
    body.pop("package_sha256")
    payload["package_sha256"] = stable_sha256(body)
    package = tmp_path / "timestamp-date.json"
    package.write_text(canonical_json(payload) + "\n", encoding="utf-8")
    assert replay_snapshot_package(package).ready is True


def test_engine_captures_genuine_nonempty_session(governed_result) -> None:
    assert governed_result.summaries["capture_session_count"] == 1
    assert governed_result.summaries["recommendation_count"] > 0
    assert governed_result.summaries["economic_candidate_count"] > 0
    assert governed_result.rows["capture_sessions"][0]["state"] == (
        CaptureSessionState.NONEMPTY.value
    )


def test_engine_captures_all_generated_verdicts(governed_result) -> None:
    recommendations = governed_result.rows["package_index"]
    assert len(recommendations) == governed_result.summaries["recommendation_count"]
    assert all(row["verdict"] for row in recommendations)


def test_engine_accrues_only_pending_forward_events(governed_result) -> None:
    assert governed_result.summaries["plan_count"] > 0
    assert governed_result.summaries["entry_count"] == 0
    assert governed_result.summaries["completed_outcome_count"] == 0
    assert all(
        row["outcome_state"] == "ENTRY_PENDING"
        for row in governed_result.rows["outcome_reconciliation"]
    )


def test_engine_replay_is_full_parity(governed_result) -> None:
    assert governed_result.summaries["replay_package_count"] == 1
    row = governed_result.rows["replay"][0]
    assert row["recommendation_parity"] is True
    assert row["fingerprint_parity"] is True
    assert row["stage_trace_parity"] is True
    assert row["terminal_parity"] is True
    assert row["allocation_parity"] is True
    assert row["plan_identity_parity"] is True


def test_dsi002_transfer_remains_semantically_conservative(governed_result) -> None:
    assert governed_result.summaries["dsi002_replayable_candidate_count"] == 0
    assert governed_result.summaries["shadow_approval_count"] == 0
    assert governed_result.summaries["shadow_trade_count"] == 0
    assert all(
        row["dsi002_semantically_eligible"] is False
        for row in governed_result.rows["dsi002_transfer"]
    )


def test_engine_readiness_preserves_outcome_immaturity(governed_result) -> None:
    assert governed_result.readiness["A"] == SliceReadiness.A_READY
    assert governed_result.readiness["E"] == SliceReadiness.E_NO_MATURE
    assert governed_result.readiness["H"] == SliceReadiness.H_ACCRUAL
    assert governed_result.readiness["I"] == SliceReadiness.I_ACCRUAL
    assert governed_result.blockers == ("OUTCOME_POPULATION_NOT_MATURE",)


def test_population_uses_independent_economic_candidates(governed_result) -> None:
    population = governed_result.rows["population"][0]
    assert (
        population["independent_economic_candidates"]
        <= (population["candidate_arm_packages"])
    )
    assert population["completed_outcomes"] == 0


def test_structural_probes_are_not_empirical_population() -> None:
    rows = structural_probe_rows()
    assert len(rows) >= 25
    assert all(row["passed"] is True for row in rows)
    assert all(row["empirical_population"] is False for row in rows)


def test_export_is_deterministic(
    governed_result,
    tmp_path: Path,
) -> None:
    first = export_forward_snapshot_accrual(governed_result, tmp_path / "first")
    second = export_forward_snapshot_accrual(governed_result, tmp_path / "second")
    first_by_name = {path.name: path.read_bytes() for path in first}
    second_by_name = {path.name: path.read_bytes() for path in second}
    assert first_by_name == second_by_name
    assert len(first) == len(DSI006_ARTIFACTS) + 3


def test_certificate_and_artifacts_validate(
    governed_result,
    tmp_path: Path,
) -> None:
    paths = export_forward_snapshot_accrual(governed_result, tmp_path)
    certificate = next(path for path in paths if path.name == DSI006_CERTIFICATE)
    payload = validate_forward_snapshot_certificate(
        certificate,
        require_ready=True,
        project_root=_PROJECT_ROOT,
    )
    assert payload["readiness_decision"] == SliceReadiness.I_ACCRUAL.value
    assert payload["governance_flags"] == governance_flags()


def test_certificate_tampering_is_detected(
    governed_result,
    tmp_path: Path,
) -> None:
    paths = export_forward_snapshot_accrual(governed_result, tmp_path)
    certificate = next(path for path in paths if path.name == DSI006_CERTIFICATE)
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    payload["readiness_decision"] = "TAMPERED"
    certificate.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ForwardSnapshotError, match="REPORT_HASH_MISMATCH"):
        validate_forward_snapshot_certificate(
            certificate,
            project_root=_PROJECT_ROOT,
        )


def test_support_artifact_tampering_is_detected(
    governed_result,
    tmp_path: Path,
) -> None:
    paths = export_forward_snapshot_accrual(governed_result, tmp_path)
    certificate = next(path for path in paths if path.name == DSI006_CERTIFICATE)
    report = tmp_path / DSI006_REPORT
    report.write_text("tampered", encoding="utf-8")
    with pytest.raises(ForwardSnapshotError, match="ARTIFACT_TAMPERED"):
        validate_forward_snapshot_certificate(
            certificate,
            project_root=_PROJECT_ROOT,
        )


def test_source_drift_is_detected(
    governed_result,
    tmp_path: Path,
) -> None:
    paths = export_forward_snapshot_accrual(governed_result, tmp_path)
    certificate = next(path for path in paths if path.name == DSI006_CERTIFICATE)
    source_contract = tmp_path / DSI006_ARTIFACTS["source_contract"]
    text = source_contract.read_text(encoding="utf-8")
    source_contract.write_text(
        text.replace(text.splitlines()[1].split(",")[2], "0" * 64, 1),
        encoding="utf-8",
    )
    payload = json.loads(certificate.read_text(encoding="utf-8"))
    manifest = payload["support_artifact_manifest"]
    manifest[source_contract.name] = hashlib.sha256(
        source_contract.read_bytes()
    ).hexdigest()
    payload.pop("report_sha256")
    payload["report_sha256"] = stable_sha256(payload)
    certificate.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ForwardSnapshotError):
        validate_forward_snapshot_certificate(
            certificate,
            project_root=_PROJECT_ROOT,
        )


def test_event_jsonl_and_report_are_present(
    governed_result,
    tmp_path: Path,
) -> None:
    export_forward_snapshot_accrual(governed_result, tmp_path)
    assert (tmp_path / DSI006_EVENTS).is_file()
    report = (tmp_path / DSI006_REPORT).read_text(encoding="utf-8")
    assert "Forward Snapshot Accrual" in report
    assert "profitability is not established" in report
    assert "PRODUCTION_INFLUENCE=false" in report


def test_cli_certificate_and_repository_verifiers(
    governed_result,
    tmp_path: Path,
    captured_repository: ContentAddressedSnapshotRepository,
) -> None:
    paths = export_forward_snapshot_accrual(governed_result, tmp_path)
    certificate = next(path for path in paths if path.name == DSI006_CERTIFICATE)
    runner = CliRunner()
    certificate_result = runner.invoke(
        benchmark_app,
        [
            "decision-superiority-forward-snapshot-verify",
            "--certificate",
            str(certificate),
            "--require-ready",
        ],
    )
    assert certificate_result.exit_code == 0
    assert "Certificate: VALID" in certificate_result.output
    repository_result = runner.invoke(
        benchmark_app,
        [
            "decision-superiority-forward-repository-verify",
            "--repository",
            str(captured_repository.root),
        ],
    )
    assert repository_result.exit_code == 0
    assert "Repository: VALID" in repository_result.output


def test_cli_capture_prints_governance_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "alpha.decision_superiority.forward_snapshot_accrual."
        "HistoricalTruthReplayStore",
        _FakeHistoricalTruthStore,
    )
    result = CliRunner().invoke(
        benchmark_app,
        [
            "decision-superiority-forward-snapshot-capture",
            "--session-date",
            _SESSION_DATE.isoformat(),
            "--database",
            str(tmp_path / "warehouse.duckdb"),
            "--historical-truth-snapshots",
            str(tmp_path / "snapshots"),
            "--dsi005-certificate",
            str(_DSI005_CERTIFICATE),
            "--output",
            str(tmp_path / "output"),
        ],
    )
    assert result.exit_code == 0
    assert "DSI-006I Readiness" in result.output
    assert "DEFAULT_SNAPSHOT_CAPTURE_ENABLED=false" in result.output
    assert "PRODUCTION_SNAPSHOT_WRITES_ENABLED=false" in result.output
    assert "PRODUCTION_INFLUENCE=false" in result.output


def test_dsi005_validator_remains_strict_by_default() -> None:
    from alpha.decision_superiority.recommendation_snapshot_retention_artifacts import (
        validate_replay_retention_certificate,
    )

    with pytest.raises(ValueError, match="IMPLEMENTATION_SOURCE_DRIFT"):
        validate_replay_retention_certificate(
            _DSI005_CERTIFICATE,
            require_ready=True,
            project_root=_PROJECT_ROOT,
        )


def test_models_are_immutable(captured_repository) -> None:
    row = captured_repository.index_rows()[0]
    with pytest.raises(FrozenInstanceError):
        row.symbol = ""  # type: ignore[misc]
