from __future__ import annotations

from pathlib import Path

TEST = Path("tests/historical_truth/test_pre2016_composite_factor_closure.py")


def replace_once(text: str, old: str, new: str, code: str) -> str:
    if old not in text:
        raise RuntimeError(code)
    return text.replace(old, new, 1)


def main() -> None:
    text = TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        'write_text("[]\n")',
        'write_text("[]\\n")',
        "PRE2016_EMPTY_JSON_ESCAPE_BOUNDARY_MISSING",
    )
    text = replace_once(
        text,
        '        + "\n"\n    )',
        '        + "\\n"\n    )',
        "PRE2016_CASE_JSON_ESCAPE_BOUNDARY_MISSING",
    )
    TEST.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
