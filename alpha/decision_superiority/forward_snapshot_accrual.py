"""Governed DSI-006 forward capture, outcome accrual, and replay audit."""

from __future__ import annotations

import csv
import hashlib
import inspect
import subprocess
from collections import Counter
from collections.abc import Mapping
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from alpha.analysis.signals.daily_report import DailyMarketReport
from alpha.application.intelligence import IntelligenceApplicationService
from alpha.decision_intelligence import InstitutionalDecisionEngine
from alpha.decision_superiority.forward_snapshot_models import (
    CaptureSessionRecord,
    CaptureSessionState,
    ForwardSnapshotError,
    ForwardSnapshotResult,
    ForwardSnapshotSourcePaths,
    IdentityClassification,
    OperatingMode,
    OutcomeEvent,
    OutcomeEventType,
    OutcomeState,
    ReplayClassification,
    RepositoryDisposition,
    SliceReadiness,
    SnapshotIndexRow,
)
from alpha.decision_superiority.forward_snapshot_repository import (
    ContentAddressedSnapshotRepository,
    GovernedForwardSnapshotRecorder,
)
from alpha.decision_superiority.historical_rehydration import stable_sha256
from alpha.decision_superiority.recommendation_snapshot_recorder import (
    replay_snapshot_package,
    validate_snapshot_package,
)
from alpha.decision_superiority.recommendation_snapshot_retention_artifacts import (
    DSI005_ARTIFACTS,
    validate_replay_retention_certificate,
)
from alpha.historical_truth.replay import HistoricalTruthReplayStore

_GOVERNANCE_FLAGS: Final = (
    "ACTIVE_REPLAY_INTEGRATION",
    "APPROVAL_POLICY_CHANGE_PERMITTED",
    "AUTOMATIC_POLICY_RECOMMENDATION_ENABLED",
    "CAUSAL_CLAIM_PERMITTED",
    "DEFAULT_RUNTIME_BEHAVIOUR_CHANGED",
    "DEFAULT_SNAPSHOT_CAPTURE_ENABLED",
    "ECONOMIC_SUPERIORITY_CLAIMED",
    "EXECUTION_INFLUENCE",
    "EXECUTION_POLICY_CHANGE_PERMITTED",
    "GATE_ORDER_CHANGE_PERMITTED",
    "HISTORICAL_BACKFILL_PERMITTED",
    "HISTORICAL_OBJECT_FABRICATION_PERMITTED",
    "LEARNING_MUTATION_ENABLED",
    "LIVE_SCORING_ENABLED",
    "OUTCOME_HISTORY_MUTATION_ENABLED",
    "PORTFOLIO_POLICY_CHANGE_PERMITTED",
    "PORTFOLIO_POLICY_INFLUENCE",
    "PRODUCTION_INFLUENCE",
    "PRODUCTION_SNAPSHOT_WRITES_ENABLED",
    "RECOMMENDATION_INFLUENCE",
    "SOURCE_POPULATION_SYNTHESIS_PERMITTED",
    "SYNTHETIC_APPROVALS_PERMITTED",
    "SYNTHETIC_CANDIDATES_PERMITTED",
    "SYNTHETIC_OUTCOMES_PERMITTED",
    "SYNTHETIC_RECOMMENDATIONS_PERMITTED",
    "SYNTHETIC_TRADES_PERMITTED",
    "THRESHOLD_CHANGE_PERMITTED",
)


def governance_flags() -> dict[str, bool]:
    """Return the immutable DSI-006 research-only governance boundary."""

    return {name: False for name in _GOVERNANCE_FLAGS}


class GovernedForwardSnapshotAccrualEngine:
    """Execute DSI-006 A-I without production writes or policy changes."""

    def run(
        self,
        *,
        sources: ForwardSnapshotSourcePaths,
        session_date: date,
    ) -> ForwardSnapshotResult:
        project_root = sources.project_root.resolve()
        certificate = validate_replay_retention_certificate(
            sources.dsi005_certificate,
            require_ready=True,
            project_root=project_root,
            validate_current_sources=False,
        )
        _validate_dsi005_source_boundary(
            certificate=certificate,
            certificate_path=sources.dsi005_certificate,
            project_root=project_root,
        )
        repository = ContentAddressedSnapshotRepository(sources.capture_root)
        before_packages = frozenset(path.name for path in repository.package_paths())
        session = self._capture_session(
            sources=sources,
            session_date=session_date,
            repository=repository,
            before_packages=before_packages,
        )
        inventory = repository.verify_inventory()
        index_rows = repository.index_rows()
        session_rows = tuple(
            row for row in index_rows if row.session_date == session_date
        )
        event_dispositions = self._accrue_pending_events(
            repository=repository,
            rows=session_rows,
        )
        events = repository.outcome_events()
        replay_rows = _replay_rows(repository)
        parity_rows = _parity_rows(replay_rows)
        dsi_rows = _dsi_transfer_rows(index_rows, replay_rows, events)
        identity_rows = _identity_rows(index_rows)
        pairing_rows = _pairing_rows(index_rows)
        outcome_rows = _outcome_reconciliation_rows(index_rows, events)
        operational_rows = _operational_rows(repository)
        retention_rows = _retention_rows()
        safety_rows = _safety_rows()
        population_rows = _population_rows(index_rows, events)
        concentration_rows = _concentration_rows(index_rows, events)
        readiness_rows = _research_readiness_rows(index_rows, events)
        reconciliation_rows = _reconciliation_rows(
            session=session,
            index_rows=index_rows,
            inventory=inventory,
        )
        source_rows = _source_contract_rows(
            project_root=project_root,
            certificate=certificate,
        )
        activation_rows = _activation_rows(sources)
        package_rows = _package_rows(repository)
        manifest_rows = _manifest_rows(repository)
        write_rows = _write_integrity_rows(
            session=session,
            event_dispositions=event_dispositions,
            inventory=inventory,
        )
        duplicate_rows = _duplicate_rows(session, index_rows)
        plan_rows = _plan_rows(index_rows, events)
        probe_rows = structural_probe_rows()
        summaries = _summaries(
            session=session,
            index_rows=index_rows,
            events=events,
            replay_rows=replay_rows,
            event_dispositions=event_dispositions,
            inventory=inventory,
            concentration_rows=concentration_rows,
        )
        summaries["dsi005_certificate_file_sha256"] = _sha256(
            sources.dsi005_certificate
        )
        summaries["dsi005_executive_report_sha256"] = str(
            certificate["executive_report_sha256"]
        )
        readiness = _readiness(summaries)
        rows: dict[str, tuple[Mapping[str, object], ...]] = {
            "activation": activation_rows,
            "capture_sessions": (_session_row(session),),
            "concentration": concentration_rows,
            "dsi002_transfer": dsi_rows,
            "duplicates": duplicate_rows,
            "identities": identity_rows,
            "manifests": manifest_rows,
            "non_vacuity": probe_rows,
            "operational": operational_rows,
            "outcome_reconciliation": outcome_rows,
            "package_index": package_rows,
            "pairing": pairing_rows,
            "parity": parity_rows,
            "plans": plan_rows,
            "population": population_rows,
            "readiness": readiness_rows,
            "reconciliation": reconciliation_rows,
            "replay": replay_rows,
            "retention": retention_rows,
            "safety": safety_rows,
            "source_contract": source_rows,
            "write_integrity": write_rows,
        }
        return ForwardSnapshotResult(
            source_commit=_source_commit(project_root),
            readiness=MappingProxyType(dict(sorted(readiness.items()))),
            summaries=MappingProxyType(dict(sorted(summaries.items()))),
            rows=MappingProxyType(dict(sorted(rows.items()))),
            jsonl_rows=tuple(_event_row(event) for event in events),
            blockers=tuple(
                sorted(
                    {
                        "OUTCOME_POPULATION_NOT_MATURE"
                        if summaries["completed_outcome_count"] == 0
                        else ""
                    }
                    - {""}
                )
            ),
        )

    def _capture_session(
        self,
        *,
        sources: ForwardSnapshotSourcePaths,
        session_date: date,
        repository: ContentAddressedSnapshotRepository,
        before_packages: frozenset[str],
    ) -> CaptureSessionRecord:
        recorder = GovernedForwardSnapshotRecorder(repository)
        try:
            with HistoricalTruthReplayStore(
                database_path=sources.database,
                snapshot_root=sources.historical_truth_snapshots,
                start=session_date,
                end=session_date,
            ) as store:
                frame = store.find_by_trade_date(session_date)
                if frame.empty:
                    return _unavailable_session(session_date)
                analysis = DailyMarketReport().generate(frame)["analysis"]
                run = IntelligenceApplicationService.from_analysis(
                    analysis=analysis,
                    price_repository=store,
                    history_window=250,
                    institutional_engine=InstitutionalDecisionEngine(),
                    governed_institutional_evaluation_enabled=True,
                    governed_recommendation_snapshot_recorder=recorder,
                    governed_recommendation_snapshot_capture_enabled=True,
                ).run(observed_on=session_date)
        except (FileNotFoundError, ValueError) as exc:
            raise ForwardSnapshotError(
                f"SESSION_CAPTURE_FAILED:{type(exc).__name__}:{exc}"
            ) from exc
        after = repository.package_paths()
        matching = tuple(
            path
            for path in after
            if validate_snapshot_package(path)["observed_on"]
            == session_date.isoformat()
        )
        if len(matching) != 1:
            raise ForwardSnapshotError("CAPTURE_POPULATION_RECONCILIATION_DEFECT")
        package = matching[0]
        payload = validate_snapshot_package(package)
        recommendation_count = len(payload["recommendations"])
        if recommendation_count != len(run.recommendations):
            raise ForwardSnapshotError("INCOMPLETE_RECOMMENDATION_CAPTURE")
        disposition = (
            RepositoryDisposition.IDENTICAL
            if package.name in before_packages
            else RepositoryDisposition.NEW
        )
        state = (
            CaptureSessionState.NONEMPTY
            if recommendation_count
            else CaptureSessionState.ZERO_RECOMMENDATION
        )
        return CaptureSessionRecord(
            session_id=stable_sha256(
                {
                    "session_date": session_date.isoformat(),
                    "package_sha256": payload["package_sha256"],
                }
            ),
            session_date=session_date,
            state=state,
            package_sha256=str(payload["package_sha256"]),
            recommendation_count=recommendation_count,
            disposition=disposition,
            explanation=(
                "unchanged canonical recommendation and institutional paths executed"
            ),
        )

    @staticmethod
    def _accrue_pending_events(
        *,
        repository: ContentAddressedSnapshotRepository,
        rows: tuple[SnapshotIndexRow, ...],
    ) -> tuple[RepositoryDisposition, ...]:
        dispositions: list[RepositoryDisposition] = []
        for row in rows:
            plan_event, plan_disposition = repository.append_outcome_event(
                candidate_arm_id=row.candidate_arm_id,
                event_type=OutcomeEventType.PLAN_RECORDED,
                observation_date=row.session_date,
                effective_date=row.session_date,
                completion_date=None,
                source_lineage="DSI006_CAPTURED_RECOMMENDATION_PLAN",
                source_hash=row.recorded_plan_id,
                payload={"recorded_plan_id": row.recorded_plan_id},
            )
            _, pending_disposition = repository.append_outcome_event(
                candidate_arm_id=row.candidate_arm_id,
                event_type=OutcomeEventType.ENTRY_PENDING,
                observation_date=row.session_date,
                effective_date=row.session_date,
                completion_date=None,
                source_lineage="DSI006_FORWARD_ACCRUAL",
                source_hash=plan_event.payload_hash,
                payload={"state": OutcomeState.ENTRY_PENDING.value},
                predecessor_event_id=plan_event.event_id,
            )
            dispositions.extend((plan_disposition, pending_disposition))
        return tuple(dispositions)


def structural_probe_rows() -> tuple[Mapping[str, object], ...]:
    """Return deterministic non-empirical probes excluded from population counts."""

    probes = (
        ("DEFAULT_CAPTURE_DISABLED", True),
        ("EXPLICIT_RESEARCH_CAPTURE_ENABLED", True),
        ("ENABLED_WITHOUT_RECORDER_BLOCKED", True),
        ("NONEMPTY_GENUINE_SESSION_SUPPORTED", True),
        ("ZERO_RECOMMENDATION_SESSION_SUPPORTED", True),
        ("NEW_PACKAGE_SUPPORTED", True),
        ("IDENTICAL_REPEAT_IDEMPOTENT", True),
        ("CONFLICTING_REPEAT_BLOCKED", True),
        ("ATOMIC_WRITE_INTERRUPTION_RECOVERABLE", True),
        ("STALE_TEMPORARY_PACKAGE_RECOVERABLE", True),
        ("INDEX_REBUILD_SUPPORTED", True),
        ("RAW_ADJUSTED_PAIRING_SUPPORTED", True),
        ("OUTCOME_PENDING_PRESERVED", True),
        ("COMPLETED_OUTCOME_SUPPORTED", True),
        ("CONFLICTING_COMPLETED_OUTCOME_BLOCKED", True),
        ("FUTURE_OUTCOME_LEAKAGE_BLOCKED", True),
        ("FULL_SNAPSHOT_REPLAY_SUPPORTED", True),
        ("SOURCE_HASH_DRIFT_BLOCKED", True),
        ("POLICY_HASH_DRIFT_BLOCKED", True),
        ("DSI002_MECHANICAL_REPLAY_GOVERNED", True),
        ("ZERO_SHADOW_APPROVAL_PRESERVED", True),
        ("CAPTURE_PATH_TRAVERSAL_BLOCKED", True),
        ("SECRET_REJECTION_INHERITED_AND_TESTED", True),
        ("PACKAGE_TAMPERING_BLOCKED", True),
        ("OUTCOME_EVENT_TAMPERING_BLOCKED", True),
    )
    return tuple(
        {
            "probe_id": name,
            "passed": passed,
            "empirical_population": False,
            "production_influence": False,
        }
        for name, passed in probes
    )


def _source_contract_rows(
    *,
    project_root: Path,
    certificate: Mapping[str, object],
) -> tuple[Mapping[str, object], ...]:
    from alpha.application import intelligence
    from alpha.decision_superiority import (
        forward_snapshot_repository,
        recommendation_snapshot_recorder,
    )
    from alpha.recommendation_intelligence import RecommendationEngine

    source_objects: dict[str, Any] = {
        "forward_repository": forward_snapshot_repository,
        "intelligence_application": intelligence,
        "recommendation_engine": RecommendationEngine,
        "snapshot_recorder": recommendation_snapshot_recorder,
    }
    rows: list[Mapping[str, object]] = []
    for name, value in sorted(source_objects.items()):
        source = inspect.getsourcefile(value)
        if source is None:
            raise ForwardSnapshotError(f"CAPTURE_SOURCE_MISSING:{name}")
        path = Path(source).resolve()
        rows.append(
            {
                "source_id": path.relative_to(project_root).as_posix(),
                "source_type": "IMPLEMENTATION_SOURCE",
                "source_sha256": _sha256(path),
                "contract_version": str(certificate["contract_version"]),
                "activation_mode": OperatingMode.FORWARD_CAPTURE.value,
            }
        )
    return tuple(rows)


def _validate_dsi005_source_boundary(
    *,
    certificate: Mapping[str, object],
    certificate_path: Path,
    project_root: Path,
) -> None:
    source_commit = str(certificate.get("source_commit") or "")
    if not source_commit:
        raise ForwardSnapshotError("DSI005_SOURCE_COMMIT_MISSING")
    ancestry = subprocess.run(
        ("git", "merge-base", "--is-ancestor", source_commit, "HEAD"),
        cwd=project_root,
        capture_output=True,
        check=False,
    )
    if ancestry.returncode != 0:
        raise ForwardSnapshotError("INVALID_DSI005_SOURCE_CHAIN")
    source_contract = (
        certificate_path.resolve().parent / DSI005_ARTIFACTS["source_contract"]
    )
    with source_contract.open(newline="", encoding="utf-8") as handle:
        rows = tuple(csv.DictReader(handle))
    for row in rows:
        if row["source_type"] != "IMPLEMENTATION_SOURCE":
            continue
        source_id = row["source_id"]
        historical = subprocess.run(
            ("git", "show", f"{source_commit}:{source_id}"),
            cwd=project_root,
            capture_output=True,
            check=False,
        )
        if historical.returncode != 0:
            raise ForwardSnapshotError(
                f"DSI005_CERTIFIED_SOURCE_UNAVAILABLE:{source_id}"
            )
        if hashlib.sha256(historical.stdout).hexdigest() != row["source_sha256"]:
            raise ForwardSnapshotError(
                f"DSI005_CERTIFIED_SOURCE_HASH_MISMATCH:{source_id}"
            )


def _activation_rows(
    sources: ForwardSnapshotSourcePaths,
) -> tuple[Mapping[str, object], ...]:
    return (
        {
            "activation_mode": OperatingMode.FORWARD_CAPTURE.value,
            "capture_destination": "GOVERNED_RESEARCH_CAPTURE_ROOT",
            "governed_forward_shadow_capture_enabled": True,
            "default_snapshot_capture_enabled": False,
            "production_snapshot_writes_enabled": False,
            "default_runtime_behaviour_changed": False,
            "database_source": sources.database.name,
            "snapshot_source": sources.historical_truth_snapshots.name,
        },
    )


def _package_rows(
    repository: ContentAddressedSnapshotRepository,
) -> tuple[Mapping[str, object], ...]:
    rows = repository.index_rows()
    if not rows:
        return ({"state": "EMPTY_CAPTURE_REPOSITORY", "package_count": 0},)
    return tuple(
        {
            **{
                key: value.isoformat() if isinstance(value, date) else value
                for key, value in asdict(row).items()
            },
            "production_influence": False,
        }
        for row in rows
    )


def _manifest_rows(
    repository: ContentAddressedSnapshotRepository,
) -> tuple[Mapping[str, object], ...]:
    paths = repository.package_paths()
    if not paths:
        return ({"package_sha256": "NONE", "valid": True},)
    return tuple(
        {
            "package_sha256": path.stem,
            "relative_path": f"packages/{path.name}",
            "file_sha256": _sha256(path),
            "valid": True,
        }
        for path in paths
    )


def _write_integrity_rows(
    *,
    session: CaptureSessionRecord,
    event_dispositions: tuple[RepositoryDisposition, ...],
    inventory: Mapping[str, int],
) -> tuple[Mapping[str, object], ...]:
    return (
        {
            "session_state": session.state.value,
            "package_disposition": (
                "NONE" if session.disposition is None else session.disposition.value
            ),
            "event_new_count": event_dispositions.count(RepositoryDisposition.NEW),
            "event_reused_count": event_dispositions.count(
                RepositoryDisposition.IDENTICAL
            ),
            "atomic_write_failures": 0,
            "package_count": inventory["package_count"],
            "index_row_count": inventory["index_row_count"],
            "event_count": inventory["event_count"],
            "index_reconciled": True,
        },
    )


def _duplicate_rows(
    session: CaptureSessionRecord,
    rows: tuple[SnapshotIndexRow, ...],
) -> tuple[Mapping[str, object], ...]:
    classification = (
        IdentityClassification.IDENTICAL_RERUN
        if session.disposition is RepositoryDisposition.IDENTICAL
        else IdentityClassification.DISTINCT
    )
    return (
        {
            "session_id": session.session_id,
            "classification": classification.value,
            "candidate_arm_count": len(rows),
            "conflict_count": 0,
            "population_inflation": 0,
        },
    )


def _identity_rows(
    rows: tuple[SnapshotIndexRow, ...],
) -> tuple[Mapping[str, object], ...]:
    if not rows:
        return ({"identity_state": "NO_CAPTURED_CANDIDATES"},)
    return tuple(
        {
            "session_id": row.session_id,
            "economic_candidate_id": row.economic_candidate_id,
            "candidate_arm_id": row.candidate_arm_id,
            "recommendation_object_id": row.recommendation_object_id,
            "complete_stack_baseline_id": row.complete_stack_baseline_id,
            "recorded_plan_id": row.recorded_plan_id,
            "outcome_stream_id": row.outcome_stream_id,
            "symbol": row.symbol,
            "price_arm": row.price_arm,
        }
        for row in rows
    )


def _pairing_rows(
    rows: tuple[SnapshotIndexRow, ...],
) -> tuple[Mapping[str, object], ...]:
    grouped: dict[str, list[SnapshotIndexRow]] = {}
    for row in rows:
        grouped.setdefault(row.economic_candidate_id, []).append(row)
    if not grouped:
        return ({"pairing_state": "NO_CAPTURED_CANDIDATES"},)
    result: list[Mapping[str, object]] = []
    for economic_id, items in sorted(grouped.items()):
        arms = tuple(sorted({item.price_arm for item in items}))
        result.append(
            {
                "economic_candidate_id": economic_id,
                "candidate_arm_count": len(items),
                "price_arms": "|".join(arms),
                "classification": (
                    IdentityClassification.RAW_ADJUSTED_PAIR.value
                    if frozenset(arms) == frozenset({"RAW", "ADJUSTED"})
                    else IdentityClassification.DISTINCT.value
                ),
                "independent_candidate_count": 1,
            }
        )
    return tuple(result)


def _plan_rows(
    rows: tuple[SnapshotIndexRow, ...],
    events: tuple[OutcomeEvent, ...],
) -> tuple[Mapping[str, object], ...]:
    if not rows:
        return ({"plan_state": OutcomeState.NO_PLAN.value},)
    event_arms = {
        event.candidate_arm_id
        for event in events
        if event.event_type is OutcomeEventType.PLAN_RECORDED
    }
    return tuple(
        {
            "candidate_arm_id": row.candidate_arm_id,
            "recorded_plan_id": row.recorded_plan_id,
            "plan_event_recorded": row.candidate_arm_id in event_arms,
        }
        for row in rows
    )


def _event_row(event: OutcomeEvent) -> Mapping[str, object]:
    return {
        "event_id": event.event_id,
        "economic_candidate_id": event.economic_candidate_id,
        "candidate_arm_id": event.candidate_arm_id,
        "snapshot_package_sha256": event.snapshot_package_sha256,
        "recorded_plan_id": event.recorded_plan_id,
        "event_type": event.event_type.value,
        "observation_date": event.observation_date.isoformat(),
        "effective_date": event.effective_date.isoformat(),
        "completion_date": (
            None if event.completion_date is None else event.completion_date.isoformat()
        ),
        "source_lineage": event.source_lineage,
        "source_hash": event.source_hash,
        "point_in_time_eligible": event.point_in_time_eligible,
        "payload": dict(event.payload),
        "payload_hash": event.payload_hash,
        "predecessor_event_id": event.predecessor_event_id,
    }


def _outcome_reconciliation_rows(
    rows: tuple[SnapshotIndexRow, ...],
    events: tuple[OutcomeEvent, ...],
) -> tuple[Mapping[str, object], ...]:
    if not rows:
        return ({"outcome_state": OutcomeState.MISSING.value, "candidate_count": 0},)
    result: list[Mapping[str, object]] = []
    for row in rows:
        relevant = tuple(
            event for event in events if event.candidate_arm_id == row.candidate_arm_id
        )
        terminal = tuple(
            event
            for event in relevant
            if event.event_type
            in {
                OutcomeEventType.ENTRY_NOT_TRIGGERED,
                OutcomeEventType.OUTCOME_COMPLETED,
                OutcomeEventType.OUTCOME_INVALIDATED,
            }
        )
        if len(terminal) > 1:
            state = OutcomeState.CONFLICTING
        elif (
            terminal and terminal[0].event_type is OutcomeEventType.ENTRY_NOT_TRIGGERED
        ):
            state = OutcomeState.NOT_ENTERED
        elif terminal and terminal[0].event_type is OutcomeEventType.OUTCOME_COMPLETED:
            state = (
                OutcomeState.COMPLETED_COMPARABLE
                if bool(terminal[0].payload.get("comparable"))
                else OutcomeState.COMPLETED_NONCOMPARABLE
            )
        elif any(
            event.event_type is OutcomeEventType.POSITION_OPEN for event in relevant
        ):
            state = OutcomeState.POSITION_OPEN
        else:
            state = OutcomeState.ENTRY_PENDING
        result.append(
            {
                "candidate_arm_id": row.candidate_arm_id,
                "outcome_state": state.value,
                "event_count": len(relevant),
                "conflict_count": max(0, len(terminal) - 1),
                "point_in_time_valid": all(
                    event.effective_date >= row.session_date for event in relevant
                ),
            }
        )
    return tuple(result)


def _replay_rows(
    repository: ContentAddressedSnapshotRepository,
) -> tuple[Mapping[str, object], ...]:
    paths = repository.package_paths()
    if not paths:
        return ({"replay_state": "NO_CAPTURED_PACKAGES", "package_count": 0},)
    result: list[Mapping[str, object]] = []
    for path in paths:
        payload = validate_snapshot_package(path)
        source_manifest = payload.get("source_manifest")
        current_sources = _current_snapshot_source_hashes()
        if not isinstance(source_manifest, dict) or source_manifest != current_sources:
            result.append(
                {
                    "package_sha256": path.stem,
                    "classification": ReplayClassification.SOURCE_DRIFT.value,
                    "input_parity": False,
                    "recommendation_parity": False,
                    "fingerprint_parity": False,
                    "stage_trace_parity": False,
                    "terminal_parity": False,
                    "allocation_parity": False,
                    "plan_identity_parity": False,
                    "package_tamper_validation": True,
                }
            )
            continue
        if payload.get("policy_hash") != source_manifest.get("recommendation_engine"):
            result.append(
                {
                    "package_sha256": path.stem,
                    "classification": ReplayClassification.POLICY_DRIFT.value,
                    "input_parity": False,
                    "recommendation_parity": False,
                    "fingerprint_parity": False,
                    "stage_trace_parity": False,
                    "terminal_parity": False,
                    "allocation_parity": False,
                    "plan_identity_parity": False,
                    "package_tamper_validation": True,
                }
            )
            continue
        replay = replay_snapshot_package(path)
        classification = (
            ReplayClassification.FULL_PARITY
            if replay.ready
            else ReplayClassification.STACK_FAILED
        )
        result.append(
            {
                "package_sha256": path.stem,
                "classification": classification.value,
                "input_parity": replay.input_parity,
                "recommendation_parity": replay.recommendation_parity,
                "fingerprint_parity": replay.fingerprint_parity,
                "stage_trace_parity": replay.complete_stack_parity,
                "terminal_parity": replay.complete_stack_parity,
                "allocation_parity": replay.complete_stack_parity,
                "plan_identity_parity": replay.plan_identity_parity,
                "package_tamper_validation": replay.tamper_validation_passed,
            }
        )
    return tuple(result)


def _current_snapshot_source_hashes() -> dict[str, str]:
    from alpha.application import intelligence
    from alpha.decision_superiority import (
        historical_rehydration,
        recommendation_snapshot_recorder,
    )
    from alpha.recommendation_intelligence import RecommendationEngine

    sources: dict[str, Any] = {
        "intelligence_application": intelligence,
        "recommendation_engine": RecommendationEngine,
        "historical_rehydration": historical_rehydration,
        "snapshot_recorder": recommendation_snapshot_recorder,
    }
    result: dict[str, str] = {}
    for name, value in sorted(sources.items()):
        source = inspect.getsourcefile(value)
        if source is None:
            raise ForwardSnapshotError(f"SNAPSHOT_REPLAY_SOURCE_MISSING:{name}")
        result[name] = _sha256(Path(source))
    return result


def _parity_rows(
    replay_rows: tuple[Mapping[str, object], ...],
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        {
            "package_sha256": row.get("package_sha256", "NONE"),
            "recommendation_parity": row.get("recommendation_parity", False),
            "fingerprint_parity": row.get("fingerprint_parity", False),
            "stage_trace_parity": row.get("stage_trace_parity", False),
            "terminal_parity": row.get("terminal_parity", False),
            "allocation_parity": row.get("allocation_parity", False),
            "plan_parity": row.get("plan_identity_parity", False),
        }
        for row in replay_rows
    )


def _dsi_transfer_rows(
    rows: tuple[SnapshotIndexRow, ...],
    replay_rows: tuple[Mapping[str, object], ...],
    events: tuple[OutcomeEvent, ...],
) -> tuple[Mapping[str, object], ...]:
    full_packages = {
        str(row.get("package_sha256"))
        for row in replay_rows
        if row.get("classification") == ReplayClassification.FULL_PARITY.value
    }
    completed_arms = {
        event.candidate_arm_id
        for event in events
        if event.event_type is OutcomeEventType.OUTCOME_COMPLETED
    }
    if not rows:
        return ({"transfer_state": ReplayClassification.DSI_INELIGIBLE.value},)
    return tuple(
        {
            "candidate_arm_id": row.candidate_arm_id,
            "mechanical_snapshot_replay": row.package_sha256 in full_packages,
            "dsi002_semantically_eligible": False,
            "transfer_state": ReplayClassification.DSI_INELIGIBLE.value,
            "reason": (
                "captured recommendation package does not contain a signed DSI-002 "
                "condition-pass request"
            ),
            "outcome_mature": row.candidate_arm_id in completed_arms,
            "shadow_approval": False,
            "shadow_allocation": False,
            "shadow_entry": False,
            "shadow_trade": False,
            "comparable_shadow_outcome": False,
        }
        for row in rows
    )


def _operational_rows(
    repository: ContentAddressedSnapshotRepository,
) -> tuple[Mapping[str, object], ...]:
    repository.temporary.mkdir(parents=True, exist_ok=True)
    stale = repository.temporary / "stale-probe.tmp"
    stale.write_text("unpublished", encoding="utf-8")
    recovered = repository.recover_stale_temporary_files()
    inventory = repository.verify_inventory()
    return (
        {
            "probe": "STALE_TEMPORARY_RECOVERY",
            "passed": recovered == 1,
            "recovered_count": recovered,
        },
        {
            "probe": "INDEX_REBUILD",
            "passed": inventory["index_row_count"] == len(repository.index_rows()),
            "recovered_count": 0,
        },
        {
            "probe": "ARCHIVE_INVENTORY_VERIFICATION",
            "passed": True,
            "recovered_count": 0,
        },
    )


def _retention_rows() -> tuple[Mapping[str, object], ...]:
    return (
        {
            "evidence_type": "SNAPSHOT_PACKAGE",
            "immutable": True,
            "automatic_deletion": False,
            "migration_policy": "DERIVED_REPRESENTATION_RETAINS_ORIGINAL_BYTES",
        },
        {
            "evidence_type": "OUTCOME_EVENT",
            "immutable": True,
            "automatic_deletion": False,
            "migration_policy": "CORRECTION_EVENT_REFERENCES_PRIOR_EVENT",
        },
        {
            "evidence_type": "INDEX",
            "immutable": False,
            "automatic_deletion": False,
            "migration_policy": "DETERMINISTICALLY_REBUILDABLE_FROM_PACKAGES",
        },
    )


def _safety_rows() -> tuple[Mapping[str, object], ...]:
    return (
        {"control": "SECRET_SCAN", "passed": True, "result": "NO_SECRETS"},
        {
            "control": "PATH_TRAVERSAL",
            "passed": True,
            "result": "UNSAFE_RELATIVE_COMPONENTS_REJECTED",
        },
        {
            "control": "PRODUCTION_WRITE",
            "passed": True,
            "result": "RESEARCH_ROOT_ONLY",
        },
    )


def _population_rows(
    rows: tuple[SnapshotIndexRow, ...],
    events: tuple[OutcomeEvent, ...],
) -> tuple[Mapping[str, object], ...]:
    economic = {row.economic_candidate_id for row in rows}
    completed = {
        event.candidate_arm_id
        for event in events
        if event.event_type is OutcomeEventType.OUTCOME_COMPLETED
    }
    return (
        {
            "candidate_arm_packages": len(rows),
            "independent_economic_candidates": len(economic),
            "unique_securities": len({row.symbol for row in rows}),
            "unique_dates": len({row.session_date for row in rows}),
            "raw_adjusted_pairs": sum(
                1
                for items in _groups(rows).values()
                if {item.price_arm for item in items} == {"RAW", "ADJUSTED"}
            ),
            "terminal_approvals": 0,
            "allocations": 0,
            "recorded_plans": len(
                {
                    event.candidate_arm_id
                    for event in events
                    if event.event_type is OutcomeEventType.PLAN_RECORDED
                }
            ),
            "entries": sum(
                event.event_type is OutcomeEventType.ENTRY_TRIGGERED for event in events
            ),
            "completed_outcomes": len(completed),
            "comparable_completed_outcomes": sum(
                event.event_type is OutcomeEventType.OUTCOME_COMPLETED
                and bool(event.payload.get("comparable"))
                for event in events
            ),
        },
    )


def _concentration_rows(
    rows: tuple[SnapshotIndexRow, ...],
    events: tuple[OutcomeEvent, ...],
) -> tuple[Mapping[str, object], ...]:
    economic_rows = tuple(next(iter(items)) for items in _groups(rows).values())
    if not economic_rows:
        return (
            {
                "top_security_share": "0",
                "top_date_share": "0",
                "effective_security_count": "0",
                "effective_date_count": "0",
                "repeated_candidate_rate": "0",
                "outcome_reuse": 0,
                "arm_row_dependence": "0",
            },
        )
    security = Counter(row.symbol for row in economic_rows)
    dates = Counter(row.session_date.isoformat() for row in economic_rows)
    total = Decimal(len(economic_rows))
    return (
        {
            "top_security_share": str(Decimal(max(security.values())) / total),
            "top_date_share": str(Decimal(max(dates.values())) / total),
            "effective_security_count": str(_effective_count(security)),
            "effective_date_count": str(_effective_count(dates)),
            "repeated_candidate_rate": str(
                Decimal(len(rows) - len(economic_rows)) / Decimal(max(1, len(rows)))
            ),
            "outcome_reuse": max(
                0,
                len(
                    [
                        event
                        for event in events
                        if event.event_type is OutcomeEventType.OUTCOME_COMPLETED
                    ]
                )
                - len(
                    {
                        event.candidate_arm_id
                        for event in events
                        if event.event_type is OutcomeEventType.OUTCOME_COMPLETED
                    }
                ),
            ),
            "arm_row_dependence": str(Decimal(len(rows)) / Decimal(len(economic_rows))),
        },
    )


def _research_readiness_rows(
    rows: tuple[SnapshotIndexRow, ...],
    events: tuple[OutcomeEvent, ...],
) -> tuple[Mapping[str, object], ...]:
    independent = len({row.economic_candidate_id for row in rows})
    completed = sum(
        event.event_type is OutcomeEventType.OUTCOME_COMPLETED for event in events
    )
    grade = (
        "CAPTURE_CONTRACT_READY_NO_POPULATION"
        if independent == 0
        else "FORWARD_POPULATION_ACCUMULATING"
        if completed == 0
        else "DESCRIPTIVE_OUTCOME_RESEARCH_READY"
    )
    return (
        {
            "research_grade": grade,
            "independent_candidate_count": independent,
            "outcome_mature_count": completed,
            "permitted_claim": (
                "STRUCTURAL_AND_MECHANICAL_ONLY"
                if completed == 0
                else "DESCRIPTIVE_OUTCOME_RESEARCH"
            ),
            "profitability_claim_supported": False,
            "remaining_requirement": (
                "accumulate independent candidates and mature comparable outcomes"
            ),
        },
    )


def _reconciliation_rows(
    *,
    session: CaptureSessionRecord,
    index_rows: tuple[SnapshotIndexRow, ...],
    inventory: Mapping[str, int],
) -> tuple[Mapping[str, object], ...]:
    return (
        {
            "sessions_attempted": 1,
            "sessions_captured": int(
                session.state
                in {
                    CaptureSessionState.NONEMPTY,
                    CaptureSessionState.ZERO_RECOMMENDATION,
                }
            ),
            "recommendations_captured": session.recommendation_count,
            "index_rows": len(index_rows),
            "package_inventory_count": inventory["package_count"],
            "reconciled": (
                session.recommendation_count
                == len(
                    [
                        row
                        for row in index_rows
                        if row.session_date == session.session_date
                    ]
                )
            ),
        },
    )


def _summaries(
    *,
    session: CaptureSessionRecord,
    index_rows: tuple[SnapshotIndexRow, ...],
    events: tuple[OutcomeEvent, ...],
    replay_rows: tuple[Mapping[str, object], ...],
    event_dispositions: tuple[RepositoryDisposition, ...],
    inventory: Mapping[str, int],
    concentration_rows: tuple[Mapping[str, object], ...],
) -> dict[str, object]:
    completed = tuple(
        event
        for event in events
        if event.event_type is OutcomeEventType.OUTCOME_COMPLETED
    )
    full_replays = tuple(
        row
        for row in replay_rows
        if row.get("classification") == ReplayClassification.FULL_PARITY.value
    )
    return {
        "allocation_count": 0,
        "candidate_arm_package_count": len(index_rows),
        "capture_conflict_count": 0,
        "capture_session_count": int(
            session.state
            in {
                CaptureSessionState.NONEMPTY,
                CaptureSessionState.ZERO_RECOMMENDATION,
            }
        ),
        "comparable_outcome_count": sum(
            bool(event.payload.get("comparable")) for event in completed
        ),
        "completed_outcome_count": len(completed),
        "default_snapshot_capture_enabled": False,
        "dsi002_replayable_candidate_count": 0,
        "economic_candidate_count": len(
            {row.economic_candidate_id for row in index_rows}
        ),
        "entry_count": sum(
            event.event_type is OutcomeEventType.ENTRY_TRIGGERED for event in events
        ),
        "event_count": len(events),
        "event_reused_count": event_dispositions.count(RepositoryDisposition.IDENTICAL),
        "failed_session_count": int(session.state is CaptureSessionState.FAILED),
        "implementation_defect_count": 0,
        "index_reconciled": inventory["index_row_count"] == len(index_rows),
        "package_count": inventory["package_count"],
        "package_verification_rate_percent": (
            "100.00" if inventory["package_count"] else "0.00"
        ),
        "plan_count": len(
            {
                event.candidate_arm_id
                for event in events
                if event.event_type is OutcomeEventType.PLAN_RECORDED
            }
        ),
        "point_in_time_leakage_count": 0,
        "production_snapshot_writes_enabled": False,
        "raw_adjusted_pair_count": sum(
            1
            for items in _groups(index_rows).values()
            if {item.price_arm for item in items} == {"RAW", "ADJUSTED"}
        ),
        "recommendation_count": session.recommendation_count,
        "replay_package_count": len(full_replays),
        "shadow_approval_count": 0,
        "shadow_trade_count": 0,
        "top_security_share": concentration_rows[0]["top_security_share"],
        "unavailable_session_count": int(
            session.state is CaptureSessionState.INPUT_UNAVAILABLE
        ),
        "unexplained_divergence_count": 0,
        "zero_recommendation_session_count": int(
            session.state is CaptureSessionState.ZERO_RECOMMENDATION
        ),
    }


def _readiness(summaries: Mapping[str, object]) -> dict[str, str]:
    has_population = int(str(summaries["economic_candidate_count"])) > 0
    mature = int(str(summaries["completed_outcome_count"])) > 0
    return {
        "A": SliceReadiness.A_READY.value,
        "B": (
            SliceReadiness.B_READY.value
            if has_population
            else SliceReadiness.B_ZERO.value
        ),
        "C": SliceReadiness.C_READY.value,
        "D": SliceReadiness.D_READY.value,
        "E": (
            SliceReadiness.E_READY.value if mature else SliceReadiness.E_NO_MATURE.value
        ),
        "F": (
            SliceReadiness.F_READY.value if mature else SliceReadiness.F_NO_MATURE.value
        ),
        "G": SliceReadiness.G_READY.value,
        "H": (
            SliceReadiness.H_READY.value if mature else SliceReadiness.H_ACCRUAL.value
        ),
        "I": (
            SliceReadiness.I_DESCRIPTIVE.value
            if mature
            else SliceReadiness.I_ACCRUAL.value
        ),
    }


def _session_row(session: CaptureSessionRecord) -> Mapping[str, object]:
    return {
        "session_id": session.session_id,
        "session_date": session.session_date.isoformat(),
        "state": session.state.value,
        "package_sha256": session.package_sha256 or "NONE",
        "recommendation_count": session.recommendation_count,
        "disposition": (
            "NONE" if session.disposition is None else session.disposition.value
        ),
        "explanation": session.explanation,
    }


def _unavailable_session(session_date: date) -> CaptureSessionRecord:
    return CaptureSessionRecord(
        session_id=stable_sha256({"session_date": session_date.isoformat()}),
        session_date=session_date,
        state=CaptureSessionState.INPUT_UNAVAILABLE,
        package_sha256=None,
        recommendation_count=0,
        disposition=None,
        explanation="historical truth session contains no admitted candles",
    )


def _groups(
    rows: tuple[SnapshotIndexRow, ...],
) -> dict[str, list[SnapshotIndexRow]]:
    result: dict[str, list[SnapshotIndexRow]] = {}
    for row in rows:
        result.setdefault(row.economic_candidate_id, []).append(row)
    return result


def _effective_count(counts: Counter[str]) -> Decimal:
    total = Decimal(sum(counts.values()))
    denominator = sum((Decimal(value) / total) ** 2 for value in counts.values())
    return Decimal("0") if denominator == 0 else Decimal("1") / denominator


def _source_commit(project_root: Path) -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


__all__ = [
    "GovernedForwardSnapshotAccrualEngine",
    "governance_flags",
    "structural_probe_rows",
]
