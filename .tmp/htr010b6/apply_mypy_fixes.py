from __future__ import annotations

from pathlib import Path

path = Path("alpha/benchmark_replay/governed_approval_constraint_frontier.py")
text = path.read_text(encoding="utf-8")
old = '''def _categorical_specs() -> tuple[ConstraintSpec, ...]:
    rows: list[ConstraintSpec] = []
    for code in RejectionReasonCode:
        remediation_class, action = _BASE_ACTIONS[code.value]
        rows.append(
            ConstraintSpec(
                f"BASE.{code.value}.CATEGORICAL",
                "BASE_GATE",
                code.value,
                "categorical_evidence",
                "SATISFY",
                None,
                "categorical",
                False,
                remediation_class,
                action,
                "alpha/decision_intelligence/engine.py",
                f"RejectionReasonCode.{code.name}",
            )
        )
    for code in StressReasonCode:
        remediation_class, action = _STRESS_ACTIONS[code.value]
        rows.append(
            ConstraintSpec(
                f"STRESS.{code.value}.CATEGORICAL",
                "STRESS_TEST",
                code.value,
                "categorical_evidence",
                "SATISFY",
                None,
                "categorical",
                False,
                remediation_class,
                action,
                "alpha/decision_intelligence/stress.py",
                f"StressReasonCode.{code.name}",
            )
        )
    for stage, code, remediation in (
        (
            "STRESS_DECISION",
            "STRESS_FINAL_ACTION",
            _STRESS_ACTIONS["STRESS_FINAL_ACTION"],
        ),
        ("TRADE_PLAN", "TRADE_PLAN_FINAL_ACTION", _TRADE_PLAN_ACTION),
    ):
        rows.append(
            ConstraintSpec(
                f"{stage}.{code}.CATEGORICAL",
                stage,
                code,
                "categorical_evidence",
                "SATISFY",
                None,
                "categorical",
                False,
                remediation[0],
                remediation[1],
                (
                    "alpha/decision_intelligence/stress.py"
                    if stage == "STRESS_DECISION"
                    else "alpha/decision_intelligence/tradeplan.py"
                ),
                code,
            )
        )
    return tuple(rows)
'''
new = '''def _categorical_specs() -> tuple[ConstraintSpec, ...]:
    rows: list[ConstraintSpec] = []
    for base_code in RejectionReasonCode:
        remediation_class, action = _BASE_ACTIONS[base_code.value]
        rows.append(
            ConstraintSpec(
                f"BASE.{base_code.value}.CATEGORICAL",
                "BASE_GATE",
                base_code.value,
                "categorical_evidence",
                "SATISFY",
                None,
                "categorical",
                False,
                remediation_class,
                action,
                "alpha/decision_intelligence/engine.py",
                f"RejectionReasonCode.{base_code.name}",
            )
        )
    for stress_code in StressReasonCode:
        remediation_class, action = _STRESS_ACTIONS[stress_code.value]
        rows.append(
            ConstraintSpec(
                f"STRESS.{stress_code.value}.CATEGORICAL",
                "STRESS_TEST",
                stress_code.value,
                "categorical_evidence",
                "SATISFY",
                None,
                "categorical",
                False,
                remediation_class,
                action,
                "alpha/decision_intelligence/stress.py",
                f"StressReasonCode.{stress_code.name}",
            )
        )
    for stage, gate_code, remediation in (
        (
            "STRESS_DECISION",
            "STRESS_FINAL_ACTION",
            _STRESS_ACTIONS["STRESS_FINAL_ACTION"],
        ),
        ("TRADE_PLAN", "TRADE_PLAN_FINAL_ACTION", _TRADE_PLAN_ACTION),
    ):
        rows.append(
            ConstraintSpec(
                f"{stage}.{gate_code}.CATEGORICAL",
                stage,
                gate_code,
                "categorical_evidence",
                "SATISFY",
                None,
                "categorical",
                False,
                remediation[0],
                remediation[1],
                (
                    "alpha/decision_intelligence/stress.py"
                    if stage == "STRESS_DECISION"
                    else "alpha/decision_intelligence/tradeplan.py"
                ),
                gate_code,
            )
        )
    return tuple(rows)
'''
if text.count(old) != 1:
    raise SystemExit("MyPy categorical-spec patch anchor mismatch")
path.write_text(text.replace(old, new), encoding="utf-8")
