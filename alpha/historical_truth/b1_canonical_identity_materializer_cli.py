"""CLI for HTR-010B1 canonical identity materialization."""

from __future__ import annotations

import argparse
from pathlib import Path

from alpha.historical_truth.b1_canonical_identity_materializer import (
    B1CanonicalIdentityMaterializer,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()

    report = B1CanonicalIdentityMaterializer().run(
        source_path=arguments.source,
        output=arguments.output,
    )
    print("HTR-010B1 Canonical Identity Materialization")
    print(f"Source rows: {report['source_row_count']}")
    print(f"Materialized identities: {report['materialized_identity_count']}")
    print(f"Rejected identities: {report['rejected_identity_count']}")
    print(f"Report SHA256: {report['report_sha256']}")
    print("PRODUCTION_INFLUENCE=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
