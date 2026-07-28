from __future__ import annotations

from pathlib import Path

TARGET = Path("alpha/historical_truth/bridge_aware_admission_state_propagation.py")


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    old = '''    implementation_defects = sum(
        str(row.get("validation_outcome") or "")
        == ValidationOutcome.IMPLEMENTATION_DEFECT.value
        for row in validation_results
    )
'''
    new = '''    explicit_implementation_defects = sum(
        str(row.get("validation_outcome") or "")
        == ValidationOutcome.IMPLEMENTATION_DEFECT.value
        for row in validation_results
    )
    implementation_defects = explicit_implementation_defects + unresolved
'''
    if text.count(old) != 2:
        raise RuntimeError("PRE2016_DEFECT_COUNT_BOUNDARIES_MISSING")
    TARGET.write_text(text.replace(old, new), encoding="utf-8")


if __name__ == "__main__":
    main()
