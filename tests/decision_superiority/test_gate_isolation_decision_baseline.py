from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_inputs import DemoIntelligenceInputBuilder
from alpha.decision_superiority.gate_isolation_decision_baseline import (
    RecordedDecisionBaselineEnvelope,
    RecordedDecisionBaselineStore,
    compare_run_to_baseline,
)


def _run():
    return IntelligenceApplicationService(
        input_provider=DemoIntelligenceInputBuilder()
    ).run(observed_on=date(2026, 7, 26))


def test_baseline_envelope_round_trip_and_parity(tmp_path: Path) -> None:
    run = _run()
    baseline = RecordedDecisionBaselineEnvelope.from_run(
        run=run,
        candidate_identity="RAW|2026-07-26|BEL|fp",
        snapshot_sha256="a" * 64,
    )
    store = RecordedDecisionBaselineStore(tmp_path)
    path = store.write(baseline)

    loaded = store.load(path)
    parity = compare_run_to_baseline(
        run=_run(),
        baseline=loaded,
        candidate_identity="RAW|2026-07-26|BEL|fp",
        snapshot_sha256="a" * 64,
    )

    assert loaded == baseline
    assert parity.parity_verified is True
    assert parity.production_influence is False


def test_baseline_tamper_fails_closed(tmp_path: Path) -> None:
    baseline = RecordedDecisionBaselineEnvelope.from_run(
        run=_run(),
        candidate_identity="RAW|2026-07-26|BEL|fp",
        snapshot_sha256="a" * 64,
    )
    path = RecordedDecisionBaselineStore(tmp_path).write(baseline)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["output_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="output_sha256"):
        RecordedDecisionBaselineStore(tmp_path).load(path)


def test_identity_mismatch_blocks_parity() -> None:
    run = _run()
    baseline = RecordedDecisionBaselineEnvelope.from_run(
        run=run,
        candidate_identity="RAW|2026-07-26|BEL|fp",
        snapshot_sha256="a" * 64,
    )

    result = compare_run_to_baseline(
        run=run,
        baseline=baseline,
        candidate_identity="RAW|2026-07-26|OTHER|fp",
        snapshot_sha256="a" * 64,
    )

    assert result.exact_payload_match is True
    assert result.candidate_identity_match is False
    assert result.parity_verified is False
