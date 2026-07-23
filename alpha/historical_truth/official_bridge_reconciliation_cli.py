"""CLI for HTR-010B1G official bridge reconciliation."""

from __future__ import annotations

import argparse
from pathlib import Path

from alpha.historical_truth.official_bridge_reconciliation import (
    OfficialBridgeReconciliationEngine,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HTR-010B1G reconciliation")
    parser.add_argument("--bridge-certifications", type=Path, required=True)
    parser.add_argument("--validation-results", type=Path, required=True)
    parser.add_argument("--admission-intervals", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    engine = OfficialBridgeReconciliationEngine()
    report = engine.run(
        bridge_certifications_path=arguments.bridge_certifications,
        validation_results_path=arguments.validation_results,
        admission_intervals_path=arguments.admission_intervals,
    )
    engine.export(report, arguments.output)
    print("HTR-010B1G Official Bridge Reconciliation")
    print(f"Bridge cases: {report['input_bridge_case_count']}")
    print(f"Certified propagation: {report['certified_propagation_count']}")
    print(f"Governed exclusions: {report['governed_exclusion_count']}")
    print(f"Stale downstream cases: {report['stale_downstream_case_count']}")
    print(f"Implementation defects: {report['implementation_defect_count']}")
    print(f"Report SHA256: {report['report_sha256']}")
    print("PRODUCTION_INFLUENCE=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
