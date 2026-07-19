from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from pytest import MonkeyPatch
from typer.testing import CliRunner

from alpha.candidate_learning.models import (
    CandidateDecisionRecord,
    CandidateForwardOutcome,
    CandidateForwardWindowOutcome,
    CandidateOutcomeLabel,
)
from alpha.candidate_learning.regime_shadow_live import (
    AlphaLiveShadowRuntimeService,
    ContextHarmAlert,
    DriftStatus,
    EvidenceCoverageStatus,
    FrozenAuthoritativeDecisionInput,
    LiveObservationStatus,
    LiveRegimeShadowCaptureConfig,
    LiveRegimeShadowCaptureService,
    LiveRegimeShadowEvidenceEngine,
    LiveRegimeShadowObservation,
    LiveRegimeShadowRepository,
    LiveShadowCaptureStatus,
    LiveShadowConclusion,
    LiveShadowSourceMode,
    OutcomeMaturityStatus,
    PolicyDifferenceType,
    export_live_regime_shadow_csv,
    export_live_regime_shadow_json,
    frozen_input_from_candidate,
    render_alpha_live_wiring,
)
from alpha.candidate_learning.repository import LearningLedgerRepository
from alpha.cli import app


def test_protocol_is_versioned_and_fingerprinted(tmp_path: Path) -> None:
    protocol = _engine(tmp_path).protocol()

    assert protocol.protocol_version == "live-regime-shadow-protocol-v1"
    assert protocol.protocol_fingerprint
    assert protocol.primary_policy_horizon == "20d"


def test_evidence_units_separate_candidates_dates_and_episodes(tmp_path: Path) -> None:
    repository = LiveRegimeShadowRepository(_live_ledger(tmp_path))
    repository.save_observations(
        (
            _observation("a", date(2026, 1, 1), "AAA", "BEARISH"),
            _observation("b", date(2026, 1, 1), "BBB", "BEARISH"),
            _observation("c", date(2026, 1, 2), "CCC", "BULLISH"),
        )
    )
    engine = _engine(tmp_path)

    status = engine.status()
    episodes = engine.episodes()

    assert status.live_observations == 3
    assert status.distinct_dates == 2
    assert len(episodes) == 2
    assert episodes[0].regime == "BEARISH"
    assert episodes[0].candidate_count == 2


def test_runtime_coverage_separates_implementation_from_live_evidence(
    tmp_path: Path,
) -> None:
    rows = {row.runtime_path: row for row in _engine(tmp_path).runtime_coverage()}
    alpha_live = rows["alpha live"]

    assert alpha_live.status.value == "NOT_WIRED"
    assert alpha_live.implementation_wired is True
    assert alpha_live.provider_validated is False
    assert alpha_live.candidate_path_validated is False
    assert alpha_live.shadow_capture_validated is False


def test_outcome_refresh_matures_due_observation_idempotently(tmp_path: Path) -> None:
    LiveRegimeShadowRepository(_live_ledger(tmp_path)).save_observations(
        (
            _observation("win", date(2026, 1, 1), "WIN", "BEARISH"),
            _observation("missing", date(2026, 1, 1), "MISS", "BEARISH"),
            _observation("future", date(2026, 2, 1), "FUT", "BULLISH"),
        )
    )
    ledger = LearningLedgerRepository(_learning_ledger(tmp_path))
    ledger.upsert_outcomes((_outcome("win", "WIN", Decimal("-12"), stop=True),))
    engine = _engine(tmp_path, as_of=date(2026, 1, 30))

    dry_run = engine.refresh_outcomes()
    persisted = engine.refresh_outcomes(persist=True)
    repeat = engine.refresh_outcomes(persist=True)
    observations = LiveRegimeShadowRepository(
        _live_ledger(tmp_path)
    ).load_observations()
    by_id = {row.authoritative_candidate_id: row for row in observations}

    assert dry_run.dry_run is True
    assert persisted.newly_matured == 1
    assert repeat.newly_matured == 0
    assert by_id["win"].outcome_maturity_status is OutcomeMaturityStatus.MATURED
    assert by_id["missing"].outcome_maturity_status is (
        OutcomeMaturityStatus.DUE_BUT_UNAVAILABLE
    )
    assert by_id["future"].outcome_maturity_status is (
        OutcomeMaturityStatus.INVALIDATED
    )


def test_bearish_protection_context_harm_and_guardrails(tmp_path: Path) -> None:
    LiveRegimeShadowRepository(_live_ledger(tmp_path)).save_observations(
        (
            _matured_observation(
                "true",
                date(2026, 1, 1),
                "TRUE",
                "BEARISH",
                return_pct=Decimal("-9"),
                mae=Decimal("-14"),
                stop=True,
                difference=PolicyDifferenceType.BEARISH_DEMOTION_RETAINED,
            ),
            _matured_observation(
                "false",
                date(2026, 1, 2),
                "FALSE",
                "BEARISH",
                return_pct=Decimal("11"),
                mae=Decimal("-2"),
                target=True,
                difference=PolicyDifferenceType.BEARISH_DEMOTION_RETAINED,
            ),
            _matured_observation(
                "harm",
                date(2026, 1, 3),
                "HARM",
                "NEUTRAL",
                return_pct=Decimal("-7"),
                mae=Decimal("-10"),
                stop=True,
                difference=PolicyDifferenceType.NEUTRAL_ADJUSTMENT_REMOVED,
                approval_difference=True,
            ),
        )
    )
    engine = _engine(tmp_path)

    bearish = engine.bearish_protection()
    harm = engine.context_harm()
    guardrails = engine.downstream_guardrails()

    assert bearish.true_protections == 1
    assert bearish.false_demotions == 1
    assert (
        bearish.conclusion is LiveShadowConclusion.LIVE_SHADOW_EVIDENCE_NOT_YET_MATURE
    )
    assert harm.alert is ContextHarmAlert.INSUFFICIENT_MATURED_EVIDENCE
    assert guardrails.alert == "DOWNSTREAM_POLICY_SURPRISE"


def test_coverage_blocks_candidate_count_without_dates_or_episodes(
    tmp_path: Path,
) -> None:
    LiveRegimeShadowRepository(_live_ledger(tmp_path)).save_observations(
        tuple(
            _matured_observation(
                f"same-{index}",
                date(2026, 1, 1),
                f"S{index}",
                "BEARISH",
                return_pct=Decimal("-3"),
            )
            for index in range(60)
        )
    )
    rows = {row.dimension: row for row in _engine(tmp_path).coverage()}

    assert (
        rows["matured candidate coverage"].status is EvidenceCoverageStatus.SUFFICIENT
    )
    assert rows["decision-date coverage"].status is EvidenceCoverageStatus.PARTIAL
    assert rows["regime-episode coverage"].status is EvidenceCoverageStatus.PARTIAL


def test_temporal_setup_drift_and_readiness_reports(tmp_path: Path) -> None:
    LiveRegimeShadowRepository(_live_ledger(tmp_path)).save_observations(
        (
            _matured_observation("a", date(2026, 1, 1), "AAA", "BEARISH"),
            _matured_observation("b", date(2026, 2, 1), "BBB", "BULLISH"),
        )
    )
    engine = _engine(tmp_path, as_of=date(2026, 3, 1))

    assert engine.temporal()
    assert engine.setup()
    assert engine.drift().status is DriftStatus.INSUFFICIENT_LIVE_SAMPLE
    assert (
        engine.readiness().primary_conclusion
        is LiveShadowConclusion.LIVE_SHADOW_EVIDENCE_PROGRESSING
    )


def test_review_checkpoint_is_deterministic(tmp_path: Path) -> None:
    LiveRegimeShadowRepository(_live_ledger(tmp_path)).save_observations(
        tuple(
            _matured_observation(
                f"obs-{index}",
                date(2026, 1, (index % 28) + 1),
                f"R{index}",
                "BEARISH",
            )
            for index in range(25)
        )
    )
    engine = _engine(tmp_path, as_of=date(2026, 2, 15))

    assert engine.review_due() is True
    first = engine.review_checkpoint(persist=True)
    second = engine.review_checkpoint(persist=True)

    assert first.review_id == second.review_id
    assert len(LiveRegimeShadowRepository(_live_ledger(tmp_path)).load_reviews()) == 1


def test_capture_disabled_by_default_and_replay_excluded(tmp_path: Path) -> None:
    candidate = _candidate("cap-disabled", "DIS")
    repository = LearningLedgerRepository(_learning_ledger(tmp_path))
    repository.save_records((candidate,))
    service = _capture_service(
        tmp_path,
        enabled=False,
        capture_live=False,
    )

    disabled = service.capture(
        frozen_input_from_candidate(
            candidate=candidate,
            runtime_path="alpha intelligence",
            source_mode=LiveShadowSourceMode.LATEST_COMPLETED_SESSION,
        )
    )
    replay = _capture_service(tmp_path, enabled=True, capture_live=True).capture(
        frozen_input_from_candidate(
            candidate=candidate,
            runtime_path="alpha replay",
            source_mode=LiveShadowSourceMode.REPLAY,
        )
    )

    assert disabled.status is LiveShadowCaptureStatus.SKIPPED_DISABLED
    assert replay.status is LiveShadowCaptureStatus.SKIPPED_INELIGIBLE_SOURCE
    assert LiveRegimeShadowRepository(_live_ledger(tmp_path)).load_observations() == ()


def test_capture_enabled_is_exactly_once_and_authoritative_unchanged(
    tmp_path: Path,
) -> None:
    candidate = _candidate("cap-one", "ONE", score=Decimal("78"), verdict="BUY")
    repository = LearningLedgerRepository(_learning_ledger(tmp_path))
    repository.save_records((candidate,))
    service = _capture_service(tmp_path, enabled=True, capture_live=True)
    frozen = frozen_input_from_candidate(
        candidate=candidate,
        runtime_path="alpha intelligence",
        source_mode=LiveShadowSourceMode.LATEST_COMPLETED_SESSION,
    )

    first = service.capture(frozen)
    duplicate = service.capture(frozen)
    stored = LiveRegimeShadowRepository(_live_ledger(tmp_path)).load_observations()
    reread = repository.load_records()[0]

    assert first.status is LiveShadowCaptureStatus.CAPTURED
    assert duplicate.status is LiveShadowCaptureStatus.ALREADY_CAPTURED
    assert len(stored) == 1
    assert first.authoritative_unchanged is True
    assert reread.strategy_score == candidate.strategy_score
    assert reread.final_verdict == candidate.final_verdict
    assert reread.approved_for_deployment == candidate.approved_for_deployment


def test_capture_requires_persisted_candidate_and_valid_input_parity(
    tmp_path: Path,
) -> None:
    candidate = _candidate("not-persisted", "NOP")
    service = _capture_service(tmp_path, enabled=True, capture_live=True)

    missing = service.capture(
        frozen_input_from_candidate(
            candidate=candidate,
            runtime_path="alpha intelligence",
            source_mode=LiveShadowSourceMode.LATEST_COMPLETED_SESSION,
        )
    )
    repository = LearningLedgerRepository(_learning_ledger(tmp_path))
    repository.save_records((candidate,))
    frozen = frozen_input_from_candidate(
        candidate=candidate,
        runtime_path="alpha intelligence",
        source_mode=LiveShadowSourceMode.LATEST_COMPLETED_SESSION,
    )
    bad = service.capture(
        FrozenAuthoritativeDecisionInput(
            candidate=frozen.candidate,
            runtime_path=frozen.runtime_path,
            source_mode=frozen.source_mode,
            decision_timestamp=frozen.decision_timestamp,
            source_fingerprint=frozen.source_fingerprint,
            non_regime_input_fingerprint="bad-fingerprint",
            market_state_source_quality=frozen.market_state_source_quality,
        )
    )

    assert missing.status is LiveShadowCaptureStatus.SKIPPED_INSUFFICIENT_INPUT
    assert bad.status is LiveShadowCaptureStatus.INPUT_PARITY_FAILURE
    assert LiveRegimeShadowRepository(_live_ledger(tmp_path)).load_failures()


def test_capture_health_repair_input_parity_and_operational_readiness(
    tmp_path: Path,
) -> None:
    candidate = _candidate("cap-health", "HLT")
    repository = LearningLedgerRepository(_learning_ledger(tmp_path))
    repository.save_records((candidate,))
    service = _capture_service(tmp_path, enabled=True, capture_live=True)
    service.capture(
        frozen_input_from_candidate(
            candidate=candidate,
            runtime_path="alpha intelligence",
            source_mode=LiveShadowSourceMode.LATEST_COMPLETED_SESSION,
        )
    )
    engine = _engine(tmp_path)

    assert engine.capture_health().captured_observations == 1
    assert engine.input_parity().status == "VALID"
    assert engine.repair().repairable_failures == 0
    assert engine.capture_manifests()
    assert engine.operational_readiness().recommended_next_milestone


def test_alpha_live_runtime_persists_candidate_then_captures_exactly_once(
    tmp_path: Path,
) -> None:
    repository = LearningLedgerRepository(_learning_ledger(tmp_path))
    live_repository = LiveRegimeShadowRepository(_live_ledger(tmp_path))
    capture_service = _capture_service(tmp_path, enabled=True, capture_live=True)
    runtime = AlphaLiveShadowRuntimeService(
        learning_repository=repository,
        live_repository=live_repository,
        capture_service=capture_service,
    )
    snapshot = _live_snapshot("LIVE", price=Decimal("214.50"))

    first = runtime.process_snapshot(snapshot, provider_name="DeterministicProvider")
    duplicate = runtime.process_snapshot(
        snapshot,
        provider_name="DeterministicProvider",
    )
    records = repository.load_records()
    observations = live_repository.load_observations()
    coverage = {row.runtime_path: row for row in _engine(tmp_path).runtime_coverage()}

    assert first.authoritative_candidate_created is True
    assert first.authoritative_candidate_persisted is True
    assert first.shadow_capture_invoked is True
    assert first.shadow_capture_status is LiveShadowCaptureStatus.CAPTURED
    assert duplicate.duplicate_authoritative_attempt is True
    assert duplicate.shadow_capture_status is LiveShadowCaptureStatus.ALREADY_CAPTURED
    assert len(records) == 1
    assert records[0].approved_for_deployment is False
    assert records[0].decision_provenance_id
    assert len(observations) == 1
    assert observations[0].outcome_status is LiveObservationStatus.PENDING_OUTCOME
    assert coverage["alpha live"].status.value == "WIRED_AND_TESTED"
    assert coverage["alpha live"].implementation_wired is True
    assert coverage["alpha live"].provider_validated is True
    assert coverage["alpha live"].candidate_path_validated is True
    assert coverage["alpha live"].shadow_capture_validated is True


def test_alpha_live_runtime_skips_future_timestamp_without_mutation(
    tmp_path: Path,
) -> None:
    repository = LearningLedgerRepository(_learning_ledger(tmp_path))
    runtime = AlphaLiveShadowRuntimeService(
        learning_repository=repository,
        live_repository=LiveRegimeShadowRepository(_live_ledger(tmp_path)),
        capture_service=_capture_service(tmp_path, enabled=True, capture_live=True),
    )
    future = _live_snapshot(
        "FUT",
        observed_at=datetime(2099, 1, 1, tzinfo=UTC),
    )

    report = runtime.process_snapshot(future, provider_name="DeterministicProvider")

    assert report.authoritative_candidate_created is False
    assert report.shadow_capture_invoked is False
    assert repository.load_records() == ()


def test_exports_are_deterministic(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    json_path = export_live_regime_shadow_json(
        engine.status(),
        tmp_path / "live-status.json",
    )
    csv_path = export_live_regime_shadow_csv(
        engine.coverage(),
        tmp_path / "coverage.csv",
    )

    assert (
        json.loads(json_path.read_text(encoding="utf-8"))["protocol"][
            "protocol_version"
        ]
        == "live-regime-shadow-protocol-v1"
    )
    assert "dimension" in csv_path.read_text(encoding="utf-8").splitlines()[0]
    report_lines = render_alpha_live_wiring(
        AlphaLiveShadowRuntimeService(
            learning_repository=LearningLedgerRepository(_learning_ledger(tmp_path)),
            live_repository=LiveRegimeShadowRepository(_live_ledger(tmp_path)),
            capture_service=_capture_service(
                tmp_path,
                enabled=False,
                capture_live=False,
            ),
        ).process_snapshot(
            _live_snapshot("RND"),
            provider_name="DeterministicProvider",
        )
    )
    assert "Live Regime Shadow Alpha Live Wiring" in report_lines[0]


def test_replay_cli_live_regime_shadow_commands(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALPHA_LIVE_REGIME_SHADOW_LEDGER", str(_live_ledger(tmp_path)))
    monkeypatch.setenv(
        "ALPHA_CANDIDATE_LEARNING_LEDGER", str(_learning_ledger(tmp_path))
    )
    monkeypatch.setenv("ALPHA_REGIME_SHADOW_LEDGER", str(tmp_path / "shadow.json"))
    LearningLedgerRepository(_learning_ledger(tmp_path)).save_records(
        (_candidate("cli-candidate", "CLI"),)
    )
    LiveRegimeShadowRepository(_live_ledger(tmp_path)).save_observations(
        (_matured_observation("cli", date(2026, 1, 1), "CLI", "BEARISH"),)
    )
    runner = CliRunner()

    commands = (
        "regime-shadow-live-status",
        "regime-shadow-observation-coverage",
        "regime-shadow-outcome-maturity",
        "regime-shadow-outcome-refresh",
        "regime-shadow-policy-differences",
        "regime-shadow-live-bearish-protection",
        "regime-shadow-live-context-harm",
        "regime-shadow-live-downstream-guardrails",
        "regime-shadow-live-quality",
        "regime-shadow-live-temporal",
        "regime-shadow-live-setup",
        "regime-shadow-live-drift",
        "regime-shadow-review-checkpoint",
        "regime-shadow-live-readiness",
        "regime-shadow-runtime-coverage",
        "regime-shadow-alpha-live-wiring",
        "regime-shadow-capture-health",
        "regime-shadow-capture-failures",
        "regime-shadow-capture-manifests",
        "regime-shadow-live-repair",
        "regime-shadow-input-parity",
        "regime-shadow-operational-readiness",
    )
    for command in commands:
        result = runner.invoke(app, ["replay", command])
        assert result.exit_code == 0, result.output
        assert "Live Regime Shadow" in result.output

    output = tmp_path / "live-status.json"
    exported = runner.invoke(
        app,
        [
            "replay",
            "regime-shadow-live-status",
            "--format",
            "json",
            "--output",
            str(output),
        ],
    )
    assert exported.exit_code == 0, exported.output
    assert json.loads(output.read_text(encoding="utf-8"))["live_observations"] == 1

    smoke = runner.invoke(
        app,
        ["live-shadow-smoke-test", "--symbol", "CLI"],
    )
    assert smoke.exit_code == 0, smoke.output
    assert "Executable: false" in smoke.output


def _engine(
    tmp_path: Path,
    *,
    as_of: date = date(2026, 2, 15),
) -> LiveRegimeShadowEvidenceEngine:
    return LiveRegimeShadowEvidenceEngine(
        learning_ledger_path=_learning_ledger(tmp_path),
        shadow_ledger_path=tmp_path / "shadow.json",
        live_ledger_path=_live_ledger(tmp_path),
        as_of=as_of,
    )


def _capture_service(
    tmp_path: Path,
    *,
    enabled: bool,
    capture_live: bool,
) -> LiveRegimeShadowCaptureService:
    config = LiveRegimeShadowCaptureConfig(
        shadow_enabled=enabled,
        capture_live=capture_live,
        policies=(),
        failure_mode="non_blocking",
        dry_run=False,
        configuration_fingerprint=f"config-{enabled}-{capture_live}",
    )
    return LiveRegimeShadowCaptureService(
        learning_repository=LearningLedgerRepository(_learning_ledger(tmp_path)),
        live_repository=LiveRegimeShadowRepository(_live_ledger(tmp_path)),
        config=config,
    )


def _live_ledger(tmp_path: Path) -> Path:
    return tmp_path / "live-shadow.json"


def _learning_ledger(tmp_path: Path) -> Path:
    return tmp_path / "learning.json"


def _live_snapshot(
    symbol: str,
    *,
    price: Decimal = Decimal("100"),
    volume: Decimal = Decimal("1000"),
    observed_at: datetime = datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
    stale: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        symbol=symbol,
        price=price,
        volume=volume,
        vwap=None,
        bar_started_at=observed_at,
        feed_status=SimpleNamespace(value="CONNECTED"),
        stale=stale,
        feed_health=SimpleNamespace(status=SimpleNamespace(value="CONNECTED")),
    )


def _observation(
    candidate_id: str,
    market_date: date,
    symbol: str,
    regime: str,
    *,
    difference: PolicyDifferenceType = PolicyDifferenceType.BEARISH_DEMOTION_RETAINED,
    approval_difference: bool = False,
    allocation_difference: bool = False,
) -> LiveRegimeShadowObservation:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return LiveRegimeShadowObservation(
        observation_id=f"obs-{candidate_id}",
        shadow_run_id="live-run-1",
        authoritative_candidate_id=candidate_id,
        decision_timestamp=datetime.combine(
            market_date, datetime.min.time(), tzinfo=UTC
        ),
        market_date=market_date,
        symbol=symbol,
        setup="MOMENTUM",
        holding_period="SWING",
        entry_state="ENTRY_READY",
        final_verdict="BUY",
        recorded_regime=regime,
        market_state_snapshot_id=f"snapshot-{market_date.isoformat()}",
        market_episode_id=None,
        control_shadow_id=f"control-{candidate_id}",
        context_only_shadow_id=f"context-{candidate_id}",
        bearish_only_shadow_id=f"bearish-{candidate_id}",
        policy_difference_type=difference,
        score_difference=Decimal("4"),
        verdict_difference=True,
        approval_difference=approval_difference,
        allocation_difference=allocation_difference,
        outcome_status=LiveObservationStatus.PENDING_OUTCOME,
        outcome_maturity_status=OutcomeMaturityStatus.NOT_DUE,
        outcome_maturity_date=market_date.replace(day=min(28, market_date.day + 20)),
        outcome_horizon="20d",
        outcome_record_id=None,
        available_bars=0,
        missing_bars=20,
        missing_outcome_reason=None,
        realized_return=None,
        benchmark_relative_return=None,
        mfe=None,
        mae=None,
        target_hit=None,
        stop_hit=None,
        outcome_quality=None,
        source_fingerprint="source-fp",
        policy_registry_fingerprint="policy-fp",
        protocol_fingerprint="protocol-fp",
        created_at=now,
        updated_at=now,
    )


def _candidate(
    candidate_id: str,
    symbol: str,
    *,
    score: Decimal = Decimal("62"),
    verdict: str = "WATCHLIST",
) -> CandidateDecisionRecord:
    return CandidateDecisionRecord(
        candidate_id=candidate_id,
        run_id="run-live",
        evaluation_date=date(2026, 1, 1),
        symbol=symbol,
        final_verdict=verdict,
        capital_action=verdict,
        approved_for_deployment=verdict == "BUY",
        rejection_reasons=(),
        setup_type="MOMENTUM",
        market_regime="BEARISH",
        long_trade_permission=verdict == "BUY",
        strategy_score=score,
        confidence="HIGH",
        data_quality="HIGH",
        entry_zone_low=Decimal("100"),
        entry_zone_high=Decimal("102"),
        confirmation_entry=Decimal("103"),
        risk_stop=Decimal("95"),
        target_1=Decimal("112"),
        target_2=Decimal("120"),
        target_3=Decimal("128"),
        trailing_stop_plan="2 ATR",
        expected_holding_period="20 days",
        indicators_active=("price-volume",),
        indicator_scores={"price": "0.8"},
        evidence_layers=("price-volume",),
        explanation="Synthetic capture candidate.",
        market_state_snapshot_id="snapshot-live",
        market_state_completeness="COMPLETE",
        decision_provenance_id=f"prov-{candidate_id}",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _matured_observation(
    candidate_id: str,
    market_date: date,
    symbol: str,
    regime: str,
    *,
    return_pct: Decimal = Decimal("-5"),
    mae: Decimal = Decimal("-9"),
    target: bool = False,
    stop: bool = False,
    difference: PolicyDifferenceType = PolicyDifferenceType.BEARISH_DEMOTION_RETAINED,
    approval_difference: bool = False,
) -> LiveRegimeShadowObservation:
    base = _observation(
        candidate_id,
        market_date,
        symbol,
        regime,
        difference=difference,
        approval_difference=approval_difference,
    )
    return replace(
        base,
        outcome_status=LiveObservationStatus.PRIMARY_HORIZON_MATURED,
        outcome_maturity_status=OutcomeMaturityStatus.MATURED,
        outcome_record_id=f"{candidate_id}:20d",
        available_bars=20,
        missing_bars=0,
        realized_return=return_pct,
        mfe=max(return_pct, Decimal("0")),
        mae=mae,
        target_hit=target,
        stop_hit=stop,
        outcome_quality=(
            CandidateOutcomeLabel.WOULD_HAVE_WON.value
            if return_pct > 0
            else CandidateOutcomeLabel.WOULD_HAVE_LOST.value
        ),
    )


def _outcome(
    candidate_id: str,
    symbol: str,
    return_pct: Decimal,
    *,
    stop: bool = False,
) -> CandidateForwardOutcome:
    return CandidateForwardOutcome(
        candidate_id=candidate_id,
        symbol=symbol,
        evaluated_at=datetime(2026, 2, 1, tzinfo=UTC),
        windows=(
            CandidateForwardWindowOutcome(
                window="20d",
                forward_open=Decimal("100"),
                forward_high=Decimal("108"),
                forward_low=Decimal("88"),
                forward_close=Decimal("92"),
                forward_return_pct_from_close=return_pct,
                forward_return_pct_from_entry=return_pct,
                max_favourable_excursion_pct=max(return_pct, Decimal("0")),
                max_adverse_excursion_pct=min(return_pct, Decimal("0")),
                target_1_touched=return_pct > 0,
                risk_stop_touched=stop,
                outcome_label=(
                    CandidateOutcomeLabel.WOULD_HAVE_WON
                    if return_pct > 0
                    else CandidateOutcomeLabel.WOULD_HAVE_LOST
                ),
            ),
        ),
    )
