from __future__ import annotations

from pathlib import Path

ENGINE = Path("alpha/historical_truth/complete_corporate_action_engine.py")
TEST = Path("tests/historical_truth/test_complete_corporate_action_pre2016_regressions.py")


def _replace_once(text: str, old: str, new: str, code: str) -> str:
    if old not in text:
        raise RuntimeError(code)
    return text.replace(old, new, 1)


def main() -> None:
    text = ENGINE.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        '''        joins = _records(
            htr010a3_output / "htr010a3_corporate_action_join_readiness.json"
        )
        if len(joins) != 3711:
            raise ValueError(
                "HTR-010A3 Tier A denominator must contain 3,711 identities"
            )
''',
        '''        joins, upstream_a3_readiness = _validated_a3_join_contract(
            htr010a3_output
        )
''',
        "HTR010B_A3_DENOMINATOR_BOUNDARY_MISSING",
    )
    text = _replace_once(
        text,
        '''        readiness = adjusted_replay_readiness(
            canonical, factors, intervals, raw_fingerprint
        )
''',
        '''        readiness = adjusted_replay_readiness(
            canonical, factors, intervals, raw_fingerprint
        )
        readiness = _apply_upstream_a3_readiness(
            readiness,
            upstream_a3_readiness,
        )
''',
        "HTR010B_READINESS_BOUNDARY_MISSING",
    )
    insertion = '''

def _validated_a3_join_contract(
    output: Path,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    joins = _records(output / "htr010a3_corporate_action_join_readiness.json")
    payload = json.loads(
        (output / "htr010a3_readiness.json").read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict):
        raise ValueError("HTR-010A3 readiness payload must be an object")
    if payload.get("production_influence") is not False:
        raise ValueError("HTR-010A3 readiness must have production influence false")
    readiness = payload.get("readiness")
    if not isinstance(readiness, dict):
        raise ValueError("HTR-010A3 readiness decision must be an object")
    denominator = _nonnegative_int(
        readiness.get("denominator_identities"),
        "denominator_identities",
    )
    admitted = _nonnegative_int(
        readiness.get("admitted_identities"),
        "admitted_identities",
    )
    quarantined = _nonnegative_int(
        readiness.get("quarantined_identities"),
        "quarantined_identities",
    )
    if admitted + quarantined != denominator:
        raise ValueError(
            "HTR-010A3 admitted and quarantined identities must equal denominator"
        )
    if len(joins) != denominator:
        raise ValueError(
            "HTR-010A3 join population does not match signed denominator: "
            f"joins={len(joins)} denominator={denominator}"
        )
    observed_admitted = sum(bool(row.get("admitted_to_certified_join")) for row in joins)
    if observed_admitted != admitted:
        raise ValueError(
            "HTR-010A3 admitted join count does not match signed readiness: "
            f"joins={observed_admitted} readiness={admitted}"
        )
    if len(joins) - observed_admitted != quarantined:
        raise ValueError(
            "HTR-010A3 quarantined join count does not match signed readiness"
        )
    state = str(readiness.get("state") or "")
    if state not in {
        "READY_FOR_HTR_010B",
        "CONDITIONALLY_READY_FOR_HTR_010B",
        "NOT_READY_FOR_HTR_010B",
    }:
        raise ValueError(f"unsupported HTR-010A3 readiness state: {state}")
    blockers = readiness.get("blockers", [])
    if not isinstance(blockers, list):
        raise ValueError("HTR-010A3 blockers must be a list")
    return joins, {
        "state": state,
        "blockers": [str(item) for item in blockers],
        "denominator_identities": denominator,
        "admitted_identities": admitted,
        "quarantined_identities": quarantined,
        "report_sha256": str(payload.get("report_sha256") or ""),
    }


def _apply_upstream_a3_readiness(
    readiness: dict[str, Any],
    upstream: dict[str, Any],
) -> dict[str, Any]:
    result = dict(readiness)
    upstream_state = str(upstream["state"])
    upstream_blockers = [str(item) for item in upstream.get("blockers", [])]
    result["upstream_htr010a3_readiness"] = upstream_state
    result["upstream_htr010a3_blockers"] = upstream_blockers
    existing_blockers = [str(item) for item in result.get("blockers", [])]
    prefixed = [f"HTR-010A3: {item}" for item in upstream_blockers]
    if upstream_state == "NOT_READY_FOR_HTR_010B":
        result["state"] = ReplayReadiness.NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value
        result["blockers"] = [
            *existing_blockers,
            *(prefixed or ["HTR-010A3: upstream foundation is not ready"]),
        ]
    elif upstream_state == "CONDITIONALLY_READY_FOR_HTR_010B":
        if result["state"] == ReplayReadiness.READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value:
            result["state"] = (
                ReplayReadiness.CONDITIONALLY_READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value
            )
        result["blockers"] = [*existing_blockers, *prefixed]
    else:
        result["blockers"] = existing_blockers
    return result


def _nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"HTR-010A3 {field} must be a non-negative integer")
    return value
'''
    marker = "\ndef _records(path: Path) -> list[dict[str, Any]]:\n"
    if marker not in text:
        raise RuntimeError("HTR010B_RECORD_HELPER_BOUNDARY_MISSING")
    text = text.replace(marker, insertion + marker, 1)
    ENGINE.write_text(text, encoding="utf-8")

    TEST.write_text(
        '''from __future__ import annotations

import json
from pathlib import Path

import pytest

from alpha.historical_truth.complete_corporate_action_engine import (
    _apply_upstream_a3_readiness,
    _validated_a3_join_contract,
)
from alpha.historical_truth.complete_corporate_action_models import ReplayReadiness


def _write_a3_contract(
    root: Path,
    joins: list[dict[str, object]],
    *,
    denominator: int,
    admitted: int,
    quarantined: int,
    state: str = "NOT_READY_FOR_HTR_010B",
) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "htr010a3_corporate_action_join_readiness.json").write_text(
        json.dumps(joins),
        encoding="utf-8",
    )
    (root / "htr010a3_readiness.json").write_text(
        json.dumps(
            {
                "readiness": {
                    "state": state,
                    "blockers": ["1 unexplained external-era discrepancy"],
                    "denominator_identities": denominator,
                    "admitted_identities": admitted,
                    "quarantined_identities": quarantined,
                },
                "report_sha256": "signed-a3-report",
                "production_influence": False,
            }
        ),
        encoding="utf-8",
    )


def test_dynamic_a3_denominator_accepts_signed_external_era_population(
    tmp_path: Path,
) -> None:
    joins = [
        {"identity_key": "one", "admitted_to_certified_join": True},
        {"identity_key": "two", "admitted_to_certified_join": False},
    ]
    _write_a3_contract(
        tmp_path,
        joins,
        denominator=2,
        admitted=1,
        quarantined=1,
    )

    loaded, readiness = _validated_a3_join_contract(tmp_path)

    assert loaded == joins
    assert readiness["denominator_identities"] == 2
    assert readiness["admitted_identities"] == 1


def test_dynamic_a3_denominator_mismatch_fails_closed(tmp_path: Path) -> None:
    _write_a3_contract(
        tmp_path,
        [{"identity_key": "one", "admitted_to_certified_join": True}],
        denominator=2,
        admitted=1,
        quarantined=1,
    )

    with pytest.raises(ValueError, match="signed denominator"):
        _validated_a3_join_contract(tmp_path)


def test_upstream_not_ready_blocks_adjusted_replay_promotion() -> None:
    result = _apply_upstream_a3_readiness(
        {
            "state": ReplayReadiness.READY_FOR_ADJUSTED_REPLAY_INTEGRATION.value,
            "blockers": [],
        },
        {
            "state": "NOT_READY_FOR_HTR_010B",
            "blockers": ["1 unexplained external-era discrepancy"],
        },
    )

    assert result["state"] == ReplayReadiness.NOT_READY_FOR_ADJUSTED_REPLAY_INTEGRATION
    assert result["blockers"] == [
        "HTR-010A3: 1 unexplained external-era discrepancy"
    ]
    assert result["upstream_htr010a3_readiness"] == "NOT_READY_FOR_HTR_010B"
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
