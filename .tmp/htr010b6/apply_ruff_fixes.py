from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"Ruff patch anchor mismatch: {path}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


module = Path(
    "alpha/benchmark_replay/governed_approval_constraint_frontier.py"
)
replacements = (
    (
        '        ("STRESS_DECISION", "STRESS_FINAL_ACTION", '
        '_STRESS_ACTIONS["STRESS_FINAL_ACTION"]),\n',
        '        (\n'
        '            "STRESS_DECISION",\n'
        '            "STRESS_FINAL_ACTION",\n'
        '            _STRESS_ACTIONS["STRESS_FINAL_ACTION"],\n'
        '        ),\n',
    ),
    (
        '        _progress(progress, 2, total_steps, '
        '"Loading bound B5 candidate and gate ledgers")\n',
        '        _progress(\n'
        '            progress,\n'
        '            2,\n'
        '            total_steps,\n'
        '            "Loading bound B5 candidate and gate ledgers",\n'
        '        )\n',
    ),
    (
        '    if payload.get("governed_approval_constraint_research_enabled") '
        'is not expected_enabled:\n',
        '    if (\n'
        '        payload.get("governed_approval_constraint_research_enabled")\n'
        '        is not expected_enabled\n'
        '    ):\n',
    ),
    (
        '    return _write_text(path, json.dumps(_json_ready(payload), '
        'indent=2, sort_keys=True) + "\\n")\n',
        '    content = json.dumps(_json_ready(payload), indent=2, '
        'sort_keys=True) + "\\n"\n'
        '    return _write_text(path, content)\n',
    ),
    (
        '        return sorted(items, key=lambda item: json.dumps(item, '
        'sort_keys=True)) if isinstance(value, (set, frozenset)) else items\n',
        '        if isinstance(value, (set, frozenset)):\n'
        '            return sorted(\n'
        '                items,\n'
        '                key=lambda item: json.dumps(item, sort_keys=True),\n'
        '            )\n'
        '        return items\n',
    ),
    (
        '    return len(value) == 64 and all(character in '
        '"0123456789abcdef" for character in value)\n',
        '    return len(value) == 64 and all(\n'
        '        character in "0123456789abcdef" for character in value\n'
        '    )\n',
    ),
)
for old, new in replacements:
    replace_once(module, old, new)

replace_once(
    Path("tests/benchmark_replay/test_governed_approval_constraint_frontier.py"),
    '    explanation: str = "Final evidence score is below the stricter '
    'deployment threshold.",\n',
    '    explanation: str = (\n'
    '        "Final evidence score is below the stricter deployment threshold."\n'
    '    ),\n',
)
