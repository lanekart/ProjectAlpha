from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()
CORE = ROOT / "alpha/benchmark_replay/governed_adjusted_stability.py"
TEST = ROOT / "tests/benchmark_replay/test_governed_adjusted_stability.py"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"already applied: {label}")
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one block, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"patched: {label}")


def replace_count(
    path: Path,
    old: str,
    new: str,
    *,
    expected: int,
    label: str,
) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text and old not in text:
        print(f"already applied: {label}")
        return
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} blocks, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")
    print(f"patched: {label}")


replace_once(
    CORE,
    '''    _validate_research_only_flags(payload)
    return payload
''',
    '''    if payload.get("active_replay_integration") is not False:
        raise ValueError("HTR-010B2 active replay integration is not disabled")
    if payload.get("production_influence") is not False:
        raise ValueError("HTR-010B2 production influence is not disabled")
    return payload
''',
    "B2 handoff guardrails",
)

replace_count(
    CORE,
    "        return _json_ready(asdict(self))\n",
    "        return cast(dict[str, object], _json_ready(asdict(self)))\n",
    expected=2,
    label="serializer return types",
)

replace_once(
    CORE,
    '''    if _integer(eligibility.get("eligible_security_days"), "eligible security days") != (
''',
    '''    if _integer(
        eligibility.get("eligible_security_days"),
        "eligible security days",
    ) != (
''',
    "eligible observation wrapping",
)

replace_once(
    CORE,
    '''            raise ValueError(f"{label} manifest window does not match candidate evidence")
''',
    '''            raise ValueError(
                f"{label} manifest window does not match candidate evidence"
            )
''',
    "candidate manifest wrapping",
)

replace_once(
    CORE,
    '''        decision_date = _date_value(reference.get("decision_date"), "trade decision date")
''',
    '''        decision_date = _date_value(
            reference.get("decision_date"),
            "trade decision date",
        )
''',
    "trade decision date wrapping",
)

replace_once(
    TEST,
    '''                    "effective_date": dates[60].isoformat(),
''',
    '''                    "effective_date": dates[min(60, len(dates) - 1)].isoformat(),
''',
    "short-window action fixture",
)
