from __future__ import annotations

from pathlib import Path

PATCHER = Path("scripts/patch_pre2016_rights_reference_certification.py")


def main() -> None:
    text = PATCHER.read_text(encoding="utf-8")
    old = "'        \"FACTOR_CERTIFIED\",\\n',"
    new = "'    \"FACTOR_CERTIFIED\",\\n',"
    if old not in text:
        raise RuntimeError("RIGHTS_B1_PATCHER_INDENT_BOUNDARY_MISSING")
    PATCHER.write_text(text.replace(old, new, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
