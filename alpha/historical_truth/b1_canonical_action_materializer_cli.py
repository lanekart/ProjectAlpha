"""CLI for HTR-010B1 canonical action materialization."""

from __future__ import annotations

import argparse
from pathlib import Path

from alpha.historical_truth.b1_canonical_action_materializer import (
    B1CanonicalActionMaterializer,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--identity-artifact", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    report = B1CanonicalActionMaterializer().run(
        source_path=arguments.source,
        identity_path=arguments.identity_artifact,
        output=arguments.output,
    )
    print("HTR-010B1 Canonical Action Materialization")
    print(f"Source rows: {report['source_row_count']}")
    print(f"Materialized events: {report['materialized_event_count']}")
    print(f"Resolved events: {report['resolved_event_count']}")
    print(f"Unresolved events: {report['unresolved_event_count']}")
    print(f"Material rejected: {report['material_rejected_row_count']}")
    print(f"HTR-005 loadable: {report['htr005_contract_loadable']}")
    print(f"Shadow replay safe: {report['shadow_replay_safe']}")
    print(f"Report SHA256: {report['report_sha256']}")
    print("PRODUCTION_INFLUENCE=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
