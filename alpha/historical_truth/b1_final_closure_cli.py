"""CLI for HTR-010B1 final governed closure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from alpha.historical_truth.b1_final_closure import B1FinalClosureEngine
from alpha.historical_truth.b1_shadow_replay import (
    FULL_DIAGNOSTIC_REPLAY_SCOPE,
    HTR010B1_SHADOW_CONTRACT_VERSION,
    POPULATION_PARITY_SCOPE,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b1f-certifications", type=Path, required=True)
    parser.add_argument("--b1g-directives", type=Path, required=True)
    parser.add_argument("--validation-results", type=Path, required=True)
    parser.add_argument("--admission-intervals", type=Path, required=True)
    parser.add_argument("--b1a-output", type=Path, required=True)
    parser.add_argument("--b1b-output", type=Path, required=True)
    parser.add_argument("--b1c-output", type=Path, required=True)
    parser.add_argument("--b1d-output", type=Path, required=True)
    parser.add_argument("--b1e-output", type=Path, required=True)
    parser.add_argument("--b1f-output", type=Path, required=True)
    parser.add_argument("--b1g-output", type=Path, required=True)
    parser.add_argument("--raw-replay-summary", type=Path)
    parser.add_argument("--adjusted-replay-summary", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    _validate_shadow_population(
        raw_path=arguments.raw_replay_summary,
        adjusted_path=arguments.adjusted_replay_summary,
    )
    report = B1FinalClosureEngine().run(
        b1f_certifications_path=arguments.b1f_certifications,
        b1g_directives_path=arguments.b1g_directives,
        validation_results_path=arguments.validation_results,
        admission_intervals_path=arguments.admission_intervals,
        upstream_reports={
            "B1A": arguments.b1a_output,
            "B1B": arguments.b1b_output,
            "B1C": arguments.b1c_output,
            "B1D": arguments.b1d_output,
            "B1E": arguments.b1e_output,
            "B1F": arguments.b1f_output,
            "B1G": arguments.b1g_output,
        },
        raw_replay_summary_path=arguments.raw_replay_summary,
        adjusted_replay_summary_path=arguments.adjusted_replay_summary,
    )
    B1FinalClosureEngine.export(report, arguments.output)
    print("HTR-010B1 Final Governed Closure")
    print(f"Bridge cases: {report['input_bridge_case_count']}")
    print(f"Certified bridges: {report['certified_bridge_case_count']}")
    print(f"Governed exclusions: {report['governed_exclusion_count']}")
    print(f"Readiness: {report['final_readiness_decision']}")
    print(f"Report SHA256: {report['report_sha256']}")
    print("PRODUCTION_INFLUENCE=false")
    return 0


def _validate_shadow_population(
    *,
    raw_path: Path | None,
    adjusted_path: Path | None,
) -> None:
    if raw_path is None and adjusted_path is None:
        return
    if raw_path is None or adjusted_path is None:
        raise ValueError("both RAW and ADJUSTED shadow summaries are required")
    payloads: dict[str, dict[str, Any]] = {}
    for label, path in (("RAW", raw_path), ("ADJUSTED", adjusted_path)):
        payload = _mapping(path)
        payloads[label] = payload
        if payload.get("contract_version") != HTR010B1_SHADOW_CONTRACT_VERSION:
            raise ValueError(f"{label} shadow summary uses a stale contract")
        scope = payload.get("analysis_scope")
        if scope not in {FULL_DIAGNOSTIC_REPLAY_SCOPE, POPULATION_PARITY_SCOPE}:
            raise ValueError(f"{label} shadow summary uses an unsupported scope")
        session_count = int(payload.get("session_count", 0))
        eligible_count = int(payload.get("eligible_security_count", 0))
        replay_dates = payload.get("replay_dates")
        if session_count <= 0 or eligible_count <= 0:
            raise ValueError(f"{label} shadow summary has a vacuous replay population")
        if not isinstance(replay_dates, list) or len(replay_dates) != session_count:
            raise ValueError(
                f"{label} shadow session count does not match replay dates"
            )
        if scope == POPULATION_PARITY_SCOPE:
            observation_count = int(payload.get("eligible_observation_count", 0))
            session_counts = payload.get("session_observation_counts")
            if observation_count <= 0:
                raise ValueError(
                    f"{label} population parity summary has no eligible observations"
                )
            valid_session_counts = (
                isinstance(session_counts, list)
                and len(session_counts) == session_count
            )
            if not valid_session_counts:
                raise ValueError(
                    f"{label} population parity counts do not match sessions"
                )
        if payload.get("production_influence") is not False:
            raise ValueError(f"{label} shadow summary must remain diagnostic-only")

    raw = payloads["RAW"]
    adjusted = payloads["ADJUSTED"]
    if raw.get("analysis_scope") != adjusted.get("analysis_scope"):
        raise ValueError("RAW and ADJUSTED shadow scopes differ")
    if raw.get("replay_dates") != adjusted.get("replay_dates"):
        raise ValueError("RAW and ADJUSTED shadow session sets differ")
    if raw.get("eligible_security_count") != adjusted.get("eligible_security_count"):
        raise ValueError("RAW and ADJUSTED eligible security counts differ")
    if raw.get("analysis_scope") == POPULATION_PARITY_SCOPE and raw.get(
        "session_observation_counts"
    ) != adjusted.get("session_observation_counts"):
        raise ValueError("RAW and ADJUSTED session observation counts differ")


def _mapping(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"shadow summary must contain a mapping: {path}")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
