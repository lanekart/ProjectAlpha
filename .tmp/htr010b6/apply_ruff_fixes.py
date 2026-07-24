from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str, *, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{label} anchor mismatch: {path}: {old!r}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def register_public_surfaces() -> None:
    cli = Path("alpha/application/benchmark_cli.py")
    replace_once(
        cli,
        """from alpha.application.governed_approval_gate_forensics_cli import (
    register_governed_approval_gate_forensics_command,
)
""",
        """from alpha.application.governed_approval_constraint_frontier_cli import (
    register_governed_approval_constraint_frontier_command,
)
from alpha.application.governed_approval_gate_forensics_cli import (
    register_governed_approval_gate_forensics_command,
)
""",
        label="benchmark CLI import",
    )
    replace_once(
        cli,
        "register_governed_approval_gate_forensics_command(benchmark_app)\n",
        "register_governed_approval_gate_forensics_command(benchmark_app)\n"
        "register_governed_approval_constraint_frontier_command(benchmark_app)\n",
        label="benchmark CLI registration",
    )

    package = Path("alpha/benchmark_replay/__init__.py")
    replace_once(
        package,
        "from alpha.benchmark_replay.governed_approval_gate_forensics import (\n",
        """from alpha.benchmark_replay.governed_approval_constraint_frontier import (
    B6_BLOCKED_DEFECT,
    B6_BLOCKED_DIVERGENCE,
    B6_BLOCKED_EMPTY,
    B6_BLOCKED_EVIDENCE,
    B6_READY,
    HTR010B6_CONTRACT_VERSION,
    GovernedApprovalConstraintFrontierEngine,
    GovernedApprovalConstraintFrontierResult,
    export_governed_approval_constraint_frontier,
    validate_governed_approval_constraint_frontier_certificate,
)
from alpha.benchmark_replay.governed_approval_gate_forensics import (
""",
        label="benchmark package import",
    )
    exports = (
        (
            '    "B5_READY",\n',
            '    "B5_READY",\n'
            '    "B6_BLOCKED_DEFECT",\n'
            '    "B6_BLOCKED_DIVERGENCE",\n'
            '    "B6_BLOCKED_EMPTY",\n'
            '    "B6_BLOCKED_EVIDENCE",\n'
            '    "B6_READY",\n',
        ),
        (
            '    "HTR010B5_CONTRACT_VERSION",\n',
            '    "HTR010B5_CONTRACT_VERSION",\n'
            '    "HTR010B6_CONTRACT_VERSION",\n',
        ),
        (
            '    "GovernedApprovalGateForensicsResult",\n',
            '    "GovernedApprovalGateForensicsResult",\n'
            '    "GovernedApprovalConstraintFrontierEngine",\n'
            '    "GovernedApprovalConstraintFrontierResult",\n',
        ),
        (
            '    "export_governed_approval_gate_forensics",\n',
            '    "export_governed_approval_gate_forensics",\n'
            '    "export_governed_approval_constraint_frontier",\n',
        ),
        (
            '    "validate_governed_approval_gate_forensics_certificate",\n',
            '    "validate_governed_approval_gate_forensics_certificate",\n'
            '    "validate_governed_approval_constraint_frontier_certificate",\n',
        ),
    )
    for old, new in exports:
        replace_once(package, old, new, label="benchmark package export")


def apply_ruff_wraps() -> None:
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
        replace_once(module, old, new, label="Ruff source wrap")

    replace_once(
        Path(
            "tests/benchmark_replay/"
            "test_governed_approval_constraint_frontier.py"
        ),
        '    explanation: str = "Final evidence score is below the stricter '
        'deployment threshold.",\n',
        '    explanation: str = (\n'
        '        "Final evidence score is below the stricter deployment threshold."\n'
        '    ),\n',
        label="Ruff test wrap",
    )


register_public_surfaces()
apply_ruff_wraps()
