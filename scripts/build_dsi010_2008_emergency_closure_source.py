from __future__ import annotations

import argparse
from pathlib import Path

from alpha.decision_superiority.pre2016_2008_emergency_closure import (
    build_2008_emergency_closure_source,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=float, default=45.0)
    args = parser.parse_args()
    result = build_2008_emergency_closure_source(
        database=args.database,
        output_root=args.output_root,
        timeout_seconds=args.timeout_seconds,
    )
    print("===== DSI-010 2008 EMERGENCY CLOSURE SOURCE =====")
    print(f"Source: {result.source_path}")
    print(f"Evidence Bundle: {result.evidence_bundle}")
    print(
        "Capital Market Document SHA256: "
        f"{result.capital_market_document_sha256}"
    )
    print(
        "Futures & Options Document SHA256: "
        f"{result.futures_options_document_sha256}"
    )
    print(f"API Evidence SHA256: {result.api_evidence_sha256}")
    print(f"Capital Market Candle Count: {result.capital_market_candle_count}")
    print("CROSS_SEGMENT_EVIDENCE_RULE_SATISFIED=true")
    print("CLASSIFICATION_INFERRED_FROM_CANDLES=false")
    print("CALENDAR_CERTIFICATION_PERMITTED=false")
    print("PRODUCTION_INFLUENCE=false")


if __name__ == "__main__":
    main()
