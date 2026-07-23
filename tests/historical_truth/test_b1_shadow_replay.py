from __future__ import annotations

import dataclasses
import datetime
import decimal
import inspect
import json
import pathlib

import alpha.historical_replay.models as replay_models
import alpha.historical_truth.b1_shadow_replay as shadow_replay
import alpha.historical_truth.b1_shadow_replay_cli as shadow_replay_cli


@dataclasses.dataclass(frozen=True)
class _Run:
    replay_date: datetime.date
    symbols_scanned: int
    candidates_stored: int
    emitted_decisions: int
    approved_recommendations: int
    data_gaps: int


def _runs(*, symbols: int = 10, candidates: int = 2) -> tuple[_Run, ...]:
    return (
        _Run(datetime.date(2026, 1, 2), symbols, candidates, 1, 0, 0),
        _Run(datetime.date(2026, 1, 5), symbols, candidates, 1, 1, 0),
    )


def test_shadow_replay_accepts_equal_metrics_from_distinct_sources(
    tmp_path: pathlib.Path,
) -> None:
    result = shadow_replay.B1ShadowReplayRunner(
        raw_leg=_runs,
        adjusted_leg=_runs,
    ).run()

    assert result.raw_summary["price_view"] == "RAW"
    assert result.adjusted_summary["price_view"] == "ADJUSTED"
    assert (
        result.raw_summary["source_contract"]
        != result.adjusted_summary["source_contract"]
    )
    assert result.comparison["unexplained_divergence_count"] == 0
    assert result.comparison["source_contracts_distinct"] is True

    paths = shadow_replay.B1ShadowReplayRunner.export(result, tmp_path)
    assert len(paths) == 4
    report = json.loads(paths[2].read_text(encoding="utf-8"))
    assert report["contract_version"] == shadow_replay.HTR010B1_SHADOW_CONTRACT_VERSION
    assert report["production_influence"] is False


def test_shadow_replay_flags_session_and_universe_divergence() -> None:
    raw = _runs(symbols=10)
    adjusted = (_Run(datetime.date(2026, 1, 2), 9, 2, 1, 0, 0),)

    result = shadow_replay.B1ShadowReplayRunner(
        raw_leg=lambda: raw,
        adjusted_leg=lambda: adjusted,
    ).run()

    assert result.comparison["unexplained_divergence_count"] == 2
    assert result.comparison["metric_deltas"]["session_count"] == -1
    assert result.comparison["metric_deltas"]["eligible_security_count"] == -1


def test_shadow_replay_accepts_real_frozen_replay_run_records() -> None:
    replay_run = replay_models.ReplayRunRecord(
        replay_run_id="run-1",
        replay_date=datetime.date(2026, 1, 2),
        symbols_scanned=10,
        candidates_stored=2,
        emitted_decisions=1,
        approved_recommendations=1,
        market_regime="BULL",
        long_trade_permission=True,
        data_cutoff_date=datetime.date(2026, 1, 2),
        outcome_windows_available=("1D",),
        data_gaps=0,
        runtime_seconds=decimal.Decimal("0.10"),
        created_at=datetime.datetime(2026, 1, 2, tzinfo=datetime.UTC),
    )

    def replay_leg() -> tuple[replay_models.ReplayRunRecord, ...]:
        return (replay_run,)

    result = shadow_replay.B1ShadowReplayRunner(
        raw_leg=replay_leg,
        adjusted_leg=replay_leg,
    ).run()

    assert result.raw_summary["session_count"] == 1
    assert result.raw_summary["eligible_security_count"] == 10
    assert result.adjusted_summary["institutional_approval_count"] == 1


def test_shadow_replay_counts_source_sessions_without_candidates() -> None:
    replay_dates = (
        datetime.date(2026, 1, 2),
        datetime.date(2026, 1, 5),
    )

    def empty_leg() -> shadow_replay.B1ShadowReplayLegResult:
        return shadow_replay.B1ShadowReplayLegResult(
            runs=(),
            replay_dates=replay_dates,
            eligible_security_count=10,
            observation_count=0,
        )

    result = shadow_replay.B1ShadowReplayRunner(
        raw_leg=empty_leg,
        adjusted_leg=empty_leg,
    ).run()

    assert result.raw_summary["session_count"] == 2
    assert result.raw_summary["executed_session_count"] == 0
    assert result.raw_summary["observation_count"] == 0
    assert result.comparison["replay_population_nonempty"] is True
    assert result.comparison["unexplained_divergence_count"] == 0


def test_shadow_replay_blocks_vacuous_zero_population_parity() -> None:
    def empty_population() -> shadow_replay.B1ShadowReplayLegResult:
        return shadow_replay.B1ShadowReplayLegResult(
            runs=(),
            replay_dates=(),
            eligible_security_count=10,
            observation_count=0,
        )

    result = shadow_replay.B1ShadowReplayRunner(
        raw_leg=empty_population,
        adjusted_leg=empty_population,
    ).run()

    assert result.comparison["replay_population_nonempty"] is False
    assert result.comparison["unexplained_divergence_count"] == 1


def test_shadow_cli_keeps_diagnostic_leg_outside_full_readiness_wrapper() -> None:
    source = inspect.getsource(shadow_replay_cli)

    assert "execute_governed_historical_replay" not in source
    assert "GovernedHistoricalObservationFactory" in source
    assert source.count("HistoricalReplayEngine(") == 2
    assert "B1ShadowReplayLegResult" in source
