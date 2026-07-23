from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpha.historical_truth.b1_final_closure import (
    HTR010B1_FINAL_CONTRACT_VERSION,
    B1FinalClosureEngine,
)
from alpha.historical_truth.b1_final_closure_cli import _validate_shadow_population
from alpha.historical_truth.b1_shadow_replay import (
    FULL_DIAGNOSTIC_REPLAY_SCOPE,
    HTR010B1_SHADOW_CONTRACT_VERSION,
    POPULATION_PARITY_SCOPE,
)


def _write(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _population() -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    certifications: list[dict[str, object]] = []
    directives: list[dict[str, object]] = []
    for index in range(24):
        certified = index < 23
        case_id = f"case-{index}"
        certifications.append(
            {
                "bridge_case_id": case_id,
                "continuity_decision": (
                    "CERTIFIED_CONTINUOUS_IDENTITY"
                    if certified
                    else "INSUFFICIENT_OFFICIAL_EVIDENCE"
                ),
                "post_symbol": "MCX" if not certified else f"SYM{index}",
                "pre_isin": f"PRE{index}",
                "post_isin": f"POST{index}",
                "effective_from": "2026-01-02",
                "price_series_continuity_certified": certified,
                "tradability_continuity_certified": certified,
                "factor_basis_compatible": certified,
                "adjusted_replay_certified": certified,
                "official_evidence_ids": [f"evidence-{index}"],
                "official_document_sha256": ["a" * 64],
            }
        )
        directives.append(
            {
                "bridge_case_id": case_id,
                "reconciliation_state": (
                    "CERTIFIED_BUT_DOWNSTREAM_STALE"
                    if certified
                    else "GOVERNED_EXCLUSION_PROPAGATED"
                ),
                "required_admission_state": (
                    "REBUILD_FROM_CERTIFIED_BRIDGE"
                    if certified
                    else "BRIDGE_UNCERTIFIED_QUARANTINED"
                ),
            }
        )
    return certifications, directives


def test_b1_final_closure_rebuilds_and_returns_ready_with_exclusion(
    tmp_path: Path,
) -> None:
    certifications, directives = _population()
    validations = [
        {"bridge_case_id": f"case-{index}", "bridge_certified_for_replay": False}
        for index in range(24)
    ]
    intervals = [
        {
            "bridge_case_id": f"case-{index}",
            "admission_state": "BRIDGE_UNCERTIFIED_QUARANTINED",
            "admitted_price_view": "NONE",
        }
        for index in range(24)
    ]
    raw = {"session_count": 126, "eligible_security_count": 657}
    adjusted = {"session_count": 126, "eligible_security_count": 657}
    upstream = {
        name: _write(tmp_path / name / "report.json", {"contract": name})
        for name in ("B1A", "B1B", "B1C", "B1D", "B1E", "B1F", "B1G")
    }

    report = B1FinalClosureEngine().run(
        b1f_certifications_path=_write(
            tmp_path / "certifications.json", certifications
        ),
        b1g_directives_path=_write(tmp_path / "directives.json", directives),
        validation_results_path=_write(tmp_path / "validations.json", validations),
        admission_intervals_path=_write(tmp_path / "intervals.json", intervals),
        upstream_reports=upstream,
        raw_replay_summary_path=_write(tmp_path / "raw.json", raw),
        adjusted_replay_summary_path=_write(tmp_path / "adjusted.json", adjusted),
    )

    assert report["contract_version"] == HTR010B1_FINAL_CONTRACT_VERSION
    assert report["certified_bridge_case_count"] == 23
    assert report["governed_exclusion_count"] == 1
    assert report["contract_contradiction_count"] == 0
    assert report["implementation_defect_count"] == 0
    assert report["final_readiness_decision"] == "READY_WITH_GOVERNED_EXCLUSIONS"
    assert report["production_influence"] is False
    exclusion = report["governed_exclusions"][0]
    assert exclusion["symbol"] == "MCX"
    assert exclusion["required_admission_state"] == ("BRIDGE_UNCERTIFIED_QUARANTINED")


def test_b1_final_closure_blocks_without_shadow_replay(tmp_path: Path) -> None:
    certifications, directives = _population()
    validations = [{"bridge_case_id": f"case-{index}"} for index in range(24)]
    intervals = [{"bridge_case_id": f"case-{index}"} for index in range(24)]

    report = B1FinalClosureEngine().run(
        b1f_certifications_path=_write(
            tmp_path / "certifications.json", certifications
        ),
        b1g_directives_path=_write(tmp_path / "directives.json", directives),
        validation_results_path=_write(tmp_path / "validations.json", validations),
        admission_intervals_path=_write(tmp_path / "intervals.json", intervals),
        upstream_reports={},
    )

    assert report["final_readiness_decision"] == "BLOCKED_BY_DATA_GAPS"
    assert report["shadow_replay"]["comparison_state"] == ("NOT_RUN_INPUT_NOT_PROVIDED")


def test_final_closure_cli_rejects_vacuous_shadow_population(tmp_path: Path) -> None:
    summary = {
        "contract_version": HTR010B1_SHADOW_CONTRACT_VERSION,
        "analysis_scope": FULL_DIAGNOSTIC_REPLAY_SCOPE,
        "session_count": 0,
        "eligible_security_count": 2631,
        "replay_dates": [],
        "production_influence": False,
    }
    raw = _write(tmp_path / "raw.json", summary)
    adjusted = _write(tmp_path / "adjusted.json", summary)

    with pytest.raises(ValueError, match="vacuous replay population"):
        _validate_shadow_population(raw_path=raw, adjusted_path=adjusted)


def test_final_closure_cli_accepts_nonempty_shadow_population(tmp_path: Path) -> None:
    summary = {
        "contract_version": HTR010B1_SHADOW_CONTRACT_VERSION,
        "analysis_scope": FULL_DIAGNOSTIC_REPLAY_SCOPE,
        "session_count": 2,
        "eligible_security_count": 10,
        "replay_dates": ["2026-01-02", "2026-01-05"],
        "production_influence": False,
    }
    raw = _write(tmp_path / "raw.json", summary)
    adjusted = _write(tmp_path / "adjusted.json", summary)

    _validate_shadow_population(raw_path=raw, adjusted_path=adjusted)


def test_final_closure_cli_accepts_population_parity_scope(tmp_path: Path) -> None:
    summary = {
        "contract_version": HTR010B1_SHADOW_CONTRACT_VERSION,
        "analysis_scope": POPULATION_PARITY_SCOPE,
        "session_count": 2,
        "eligible_security_count": 10,
        "eligible_observation_count": 17,
        "replay_dates": ["2026-01-02", "2026-01-05"],
        "session_observation_counts": [
            {"replay_date": "2026-01-02", "eligible_observation_count": 8},
            {"replay_date": "2026-01-05", "eligible_observation_count": 9},
        ],
        "production_influence": False,
    }
    raw = _write(tmp_path / "raw.json", summary)
    adjusted = _write(tmp_path / "adjusted.json", summary)

    _validate_shadow_population(raw_path=raw, adjusted_path=adjusted)


def test_final_closure_cli_rejects_population_count_divergence(
    tmp_path: Path,
) -> None:
    raw_summary = {
        "contract_version": HTR010B1_SHADOW_CONTRACT_VERSION,
        "analysis_scope": POPULATION_PARITY_SCOPE,
        "session_count": 1,
        "eligible_security_count": 10,
        "eligible_observation_count": 8,
        "replay_dates": ["2026-01-02"],
        "session_observation_counts": [
            {"replay_date": "2026-01-02", "eligible_observation_count": 8}
        ],
        "production_influence": False,
    }
    adjusted_summary = {
        **raw_summary,
        "eligible_observation_count": 7,
        "session_observation_counts": [
            {"replay_date": "2026-01-02", "eligible_observation_count": 7}
        ],
    }
    raw = _write(tmp_path / "raw.json", raw_summary)
    adjusted = _write(tmp_path / "adjusted.json", adjusted_summary)

    with pytest.raises(ValueError, match="session observation counts differ"):
        _validate_shadow_population(raw_path=raw, adjusted_path=adjusted)
