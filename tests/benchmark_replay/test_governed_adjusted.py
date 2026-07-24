from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

import duckdb
import pandas as pd
import pytest
from typer.testing import CliRunner

from alpha.application.benchmark_cli import benchmark_app
from alpha.benchmark_replay.engine import (
    CanonicalBenchmarkReplayEngine,
    _eligible_security_count,
)
from alpha.benchmark_replay.governed_adjusted import (
    _AdmittedReplayPriceSource,
    _benchmark_population_nonempty,
    _canonical_identity_frame,
    _identity_coverage,
    _readiness_decision,
    build_governed_benchmark_stores,
    validate_governed_adjusted_handoff,
)
from alpha.benchmark_replay.models import ReplayRequest
from alpha.canonical_universe_audit.store import LegacyMarketDataStore
from alpha.recovery.security_timeline import (
    SecurityIdentityRecord,
    SecurityIdentityTimeline,
)


def _digest(value: object) -> str:
    if isinstance(value, dict):
        value = {key: item for key, item in value.items() if key != "report_sha256"}
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _closure_digest(value: dict[str, object]) -> str:
    payload = {**value, "report_sha256": ""}
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), default=str
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _write_json(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _source_database(path: Path) -> Path:
    connection = duckdb.connect(str(path))
    connection.execute(
        """
        CREATE TABLE daily_prices (
            symbol VARCHAR,
            trade_date DATE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume BIGINT,
            sector VARCHAR,
            exchange VARCHAR
        )
        """
    )
    connection.executemany(
        "INSERT INTO daily_prices VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("ALPHA", date(2026, 1, 2), 100, 110, 90, 100, 1000, "TEST", "NSE"),
            ("ALPHA", date(2026, 1, 3), 110, 120, 100, 110, 1100, "TEST", "NSE"),
            ("ALPHA", date(2026, 1, 4), 55, 60, 50, 55, 2200, "TEST", "NSE"),
        ],
    )
    connection.close()
    return path


def _artifacts(tmp_path: Path, *, ready: bool = True) -> dict[str, Path]:
    identity = _write_json(
        tmp_path / "identities.json",
        {
            "records": [
                {
                    "security_id": "SEC-1",
                    "symbol": "ALPHA",
                    "exchange": "NSE",
                    "effective_from": "2020-01-01",
                    "effective_to": None,
                    "historical_symbols": [],
                    "recovery_version": "HTR-010B2-test",
                }
            ]
        },
    )
    action = _write_json(
        tmp_path / "actions.json",
        {
            "records": [
                {
                    "event_id": "SEC-1:SPLIT:2026-01-04",
                    "security_id": "SEC-1",
                    "symbol": "ALPHA",
                    "action_type": "SPLIT",
                    "effective_date": "2026-01-04",
                    "announced_at": "2025-12-20",
                    "price_factor": "0.5",
                    "volume_factor": "2",
                    "old_symbol": None,
                    "new_symbol": None,
                    "cash_amount": None,
                    "ratio_numerator": "2",
                    "ratio_denominator": "1",
                    "status": "RESOLVED",
                    "confidence": "1",
                    "evidence_ids": ["official:test"],
                    "source": "HTR-010B2-test",
                }
            ]
        },
    )
    universe = ("SEC-1",)
    universe_sha = _digest(list(universe))
    admission_payload = {
        "contract_version": "HTR-010B1H-v1.0.0",
        "replay_start": "2026-01-02",
        "replay_end": "2026-01-04",
        "dependency_start": "2026-01-02",
        "dependency_end": "2026-01-04",
        "admitted_identity_count": 1,
        "admitted_unresolved_action_count": 0,
        "raw_adjusted_universe_difference_count": 0,
        "raw_adjusted_session_difference_count": 0,
        "contract_contradiction_count": 0,
        "implementation_defect_count": 0,
        "raw_universe_sha256": universe_sha,
        "adjusted_universe_sha256": universe_sha,
        "shadow_replay_ready": True,
        "production_influence": False,
    }
    admission_payload["report_sha256"] = _digest(admission_payload)
    admission = _write_json(tmp_path / "admission.json", admission_payload)
    identity_admission = _write_json(
        tmp_path / "identity_admission.json",
        [
            {
                "security_id": "SEC-1",
                "symbol": "ALPHA",
                "raw_admitted": True,
                "adjusted_admitted": True,
            }
        ],
    )
    raw_universe = _write_json(tmp_path / "raw_universe.json", list(universe))
    adjusted_universe = _write_json(tmp_path / "adjusted_universe.json", list(universe))
    closure_payload = {
        "contract_version": "HTR-010B1-FINAL-v1.0.0",
        "final_readiness_decision": (
            "READY_WITH_GOVERNED_EXCLUSIONS" if ready else "BLOCKED_BY_DATA_GAPS"
        ),
        "contract_contradiction_count": 0,
        "implementation_defect_count": 0,
        "adjusted_replay_integration_enabled": False,
        "production_influence": False,
    }
    closure_payload["report_sha256"] = _closure_digest(closure_payload)
    closure = _write_json(tmp_path / "closure.json", closure_payload)
    return {
        "identity": identity,
        "action": action,
        "admission": admission,
        "identity_admission": identity_admission,
        "raw_universe": raw_universe,
        "adjusted_universe": adjusted_universe,
        "closure": closure,
    }


def _pair(tmp_path: Path):
    artifacts = _artifacts(tmp_path)
    source = LegacyMarketDataStore(_source_database(tmp_path / "source.duckdb"))
    return build_governed_benchmark_stores(
        source=source,
        identity_artifact=artifacts["identity"],
        corporate_action_artifact=artifacts["action"],
        final_closure_report=artifacts["closure"],
        admission_contract=artifacts["admission"],
        identity_admission=artifacts["identity_admission"],
        raw_universe=artifacts["raw_universe"],
        adjusted_universe=artifacts["adjusted_universe"],
        output=tmp_path / "contracts",
    )


def test_b2_command_is_registered() -> None:
    result = CliRunner().invoke(benchmark_app, ["--help"])

    assert result.exit_code == 0, result.output
    assert "governed-adjusted-replay" in result.output


def test_adjusted_history_is_rebased_as_of_replay_date(tmp_path: Path) -> None:
    pair = _pair(tmp_path)
    try:
        raw = pair.raw.find_history_by_symbols(
            symbols=("ALPHA",),
            end_date=date(2026, 1, 4),
            limit=10,
        )
        adjusted = pair.adjusted.find_history_by_symbols(
            symbols=("ALPHA",),
            end_date=date(2026, 1, 4),
            limit=10,
        )
        raw_daily = pair.raw.find_by_trade_date(date(2026, 1, 2))
        adjusted_daily = pair.adjusted.find_by_trade_date(date(2026, 1, 2))

        assert raw["close"].tolist() == [100.0, 110.0, 55.0]
        assert adjusted["close"].tolist() == [50.0, 55.0, 55.0]
        assert raw_daily["close"].tolist() == [100.0]
        assert adjusted_daily["close"].tolist() == [100.0]
        assert pair.raw.path != pair.adjusted.path
        assert pair.identity_session_sha256
    finally:
        pair.close()


def test_future_labels_use_one_consistent_end_of_window_basis(tmp_path: Path) -> None:
    pair = _pair(tmp_path)
    candidates = pd.DataFrame(
        [
            {
                "candidate_id": "candidate-1",
                "symbol": "ALPHA",
                "observed_on": date(2026, 1, 2),
            }
        ]
    )
    try:
        raw = pair.raw.future_bars(candidates, limit=2)
        adjusted = pair.adjusted.future_bars(candidates, limit=2)

        assert raw["close"].tolist() == [110.0, 55.0]
        assert adjusted["close"].tolist() == [55.0, 55.0]
        assert raw["candidate_id"].tolist() == ["candidate-1", "candidate-1"]
        assert adjusted["candidate_id"].tolist() == [
            "candidate-1",
            "candidate-1",
        ]
    finally:
        pair.close()


def test_b2_fails_closed_when_final_closure_is_not_ready(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path, ready=False)
    source = LegacyMarketDataStore(_source_database(tmp_path / "source.duckdb"))
    with pytest.raises(ValueError, match="does not permit"):
        build_governed_benchmark_stores(
            source=source,
            identity_artifact=artifacts["identity"],
            corporate_action_artifact=artifacts["action"],
            final_closure_report=artifacts["closure"],
            admission_contract=artifacts["admission"],
            identity_admission=artifacts["identity_admission"],
            raw_universe=artifacts["raw_universe"],
            adjusted_universe=artifacts["adjusted_universe"],
            output=tmp_path / "contracts",
        )
    source.close()


def test_b2_uses_source_stable_identity_across_interval_gap() -> None:
    trading_date = date(2026, 1, 2)
    identities = SecurityIdentityTimeline(
        (
            SecurityIdentityRecord(
                security_id="nse:isin:INE000A01001",
                symbol="ALPHA",
                exchange="NSE",
                effective_from=date(2026, 2, 1),
            ),
        )
    )
    frame = pd.DataFrame(
        [
            {
                "symbol": "ALPHA",
                "trade_date": trading_date,
                "exchange": "NSE",
                "security_id": "nse:isin:INE000A01001",
                "isin": "INE000A01001",
                "open": 100,
                "high": 110,
                "low": 90,
                "close": 100,
                "volume": 1000,
                "sector": "TEST",
            }
        ]
    )
    admitted = _AdmittedReplayPriceSource(
        LegacyMarketDataStore.__new__(LegacyMarketDataStore),
        identities,
        frozenset({"nse:isin:INE000A01001"}),
    )

    filtered = admitted._filter(frame)
    canonical = _canonical_identity_frame(frame, identities=identities)

    assert filtered["security_id"].tolist() == ["nse:isin:INE000A01001"]
    assert canonical["security_id"].tolist() == ["nse:isin:INE000A01001"]


def test_b2_readiness_blocks_empty_matched_population() -> None:
    raw = {
        "eligible_security_count": 0,
        "eligible_security_observation_count": 0,
    }
    adjusted = dict(raw)

    population_nonempty = _benchmark_population_nonempty(raw, adjusted)

    assert population_nonempty is False
    assert (
        _readiness_decision(
            unexplained=0,
            population_nonempty=population_nonempty,
        )
        == "BLOCKED_BY_EMPTY_BENCHMARK_POPULATION"
    )


def test_b2_readiness_requires_nonempty_parity() -> None:
    raw = {
        "eligible_security_count": 1,
        "eligible_security_observation_count": 3,
    }
    adjusted = dict(raw)

    population_nonempty = _benchmark_population_nonempty(raw, adjusted)

    assert population_nonempty is True
    assert (
        _readiness_decision(
            unexplained=0,
            population_nonempty=population_nonempty,
        )
        == "READY_FOR_GOVERNED_ADJUSTED_BENCHMARK_RESEARCH"
    )
    assert (
        _readiness_decision(
            unexplained=1,
            population_nonempty=population_nonempty,
        )
        == "BLOCKED_BY_BENCHMARK_PARITY_DIVERGENCE"
    )


def test_b2_handoff_uses_final_closure_producer_digest(
    tmp_path: Path,
) -> None:
    artifacts = _artifacts(tmp_path)
    validate_governed_adjusted_handoff(
        final_closure_report=artifacts["closure"],
        admission_contract=artifacts["admission"],
        identity_admission=artifacts["identity_admission"],
        raw_universe=artifacts["raw_universe"],
        adjusted_universe=artifacts["adjusted_universe"],
    )
    payload = json.loads(artifacts["closure"].read_text())
    payload["governed_exclusion_count"] = 1
    artifacts["closure"].write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="digest mismatch"):
        validate_governed_adjusted_handoff(
            final_closure_report=artifacts["closure"],
            admission_contract=artifacts["admission"],
            identity_admission=artifacts["identity_admission"],
            raw_universe=artifacts["raw_universe"],
            adjusted_universe=artifacts["adjusted_universe"],
        )


def test_b2_allows_admitted_identity_without_window_rows() -> None:
    admitted, unobserved = _identity_coverage(
        admitted_ids=("SEC-1", "SEC-2"),
        observed_ids={"SEC-1"},
    )

    assert admitted == ("SEC-1", "SEC-2")
    assert unobserved == ("SEC-2",)


def test_b2_rejects_observed_identity_outside_admission() -> None:
    with pytest.raises(ValueError, match="outside B1H admission"):
        _identity_coverage(
            admitted_ids=("SEC-1",),
            observed_ids={"SEC-1", "SEC-2"},
        )


def test_b2_rejects_empty_observed_identity_population() -> None:
    with pytest.raises(ValueError, match="observed identity population is empty"):
        _identity_coverage(
            admitted_ids=("SEC-1",),
            observed_ids=set(),
        )


def test_governed_store_supports_engine_eligibility_accounting(
    tmp_path: Path,
) -> None:
    pair = _pair(tmp_path)
    try:
        assert (
            pair.raw.eligible_security_count(
                start=date(2026, 1, 2),
                end=date(2026, 1, 4),
                minimum_history=3,
            )
            == 1
        )

        assert (
            pair.adjusted.eligible_security_count(
                start=date(2026, 1, 2),
                end=date(2026, 1, 4),
                minimum_history=3,
            )
            == 1
        )

        # The production benchmark threshold remains unchanged at 200.
        # Most importantly, this must not access store.connection.
        assert (
            _eligible_security_count(
                store=pair.raw,
                start=date(2026, 1, 2),
                end=date(2026, 1, 4),
            )
            == 0
        )
    finally:
        pair.close()


def test_full_benchmark_engine_uses_governed_comparison_capabilities(
    tmp_path: Path,
) -> None:
    pair = _pair(tmp_path)
    request = ReplayRequest(
        start=date(2026, 1, 2),
        end=date(2026, 1, 4),
    )
    try:
        assert not hasattr(pair.raw, "connection")
        assert not hasattr(pair.adjusted, "connection")
        engine = CanonicalBenchmarkReplayEngine()
        raw = engine.run(
            store=pair.raw,
            request=request,
            project_root=tmp_path,
        )
        adjusted = engine.run(
            store=pair.adjusted,
            request=request,
            project_root=tmp_path,
        )

        assert raw.eligible_securities == 0
        assert adjusted.eligible_securities == 0
        raw_comparisons = {item.benchmark: item for item in raw.benchmark_comparison}
        adjusted_comparisons = {
            item.benchmark: item for item in adjusted.benchmark_comparison
        }
        raw_equal = raw_comparisons["OBSERVED_EQUAL_WEIGHT_UNIVERSE"]
        adjusted_equal = adjusted_comparisons["OBSERVED_EQUAL_WEIGHT_UNIVERSE"]
        assert raw_equal.ending_value is not None
        assert adjusted_equal.ending_value is not None
        assert raw_equal.ending_value != adjusted_equal.ending_value
        assert raw_comparisons["NIFTY_50_BUY_AND_HOLD"].ending_value is None
        assert adjusted_comparisons["NIFTY_50_BUY_AND_HOLD"].ending_value is None
    finally:
        pair.close()
