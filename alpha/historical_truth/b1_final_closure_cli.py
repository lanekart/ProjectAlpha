"""CLI for HTR-010B1 final governed closure."""

from __future__ import annotations

import argparse
from pathlib import Path

from alpha.historical_truth.b1_final_closure import B1FinalClosureEngine


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


if __name__ == "__main__":
    raise SystemExit(main())
