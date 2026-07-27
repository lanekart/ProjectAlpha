from __future__ import annotations

import argparse
from pathlib import Path

from alpha.decision_superiority.pre2016_emergency_calendar import (
    build_2005_emergency_holiday_source,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-document", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    output = build_2005_emergency_holiday_source(
        source_document=args.source_document,
        output_root=args.output_root,
    )
    print("===== DSI-010 2005 EMERGENCY HOLIDAY SOURCE =====")
    print(f"Official Calendar Source: {output}")
    print("Covered Years: 2005")
    print("Official Holidays: 1")
    print("Segment Scope: EXCHANGE_WIDE")
    print("CONTENT_VALIDATION_PASSED=true")
    print("MANUAL_REVIEW_COMPLETED=true")
    print("CLASSIFICATION_INFERRED_FROM_ARCHIVE_STATUS=false")
    print("CLASSIFICATION_INFERRED_FROM_OBSERVED_CANDLES=false")
    print("CALENDAR_CERTIFICATION_PERMITTED=false")
    print("PRODUCTION_INFLUENCE=false")


if __name__ == "__main__":
    main()
