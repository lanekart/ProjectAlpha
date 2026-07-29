"""Permanent genuine-population acceptance sequence for DSI-011A."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from alpha.research.lab_service import ConversationalResearchLab, LabExecution

GOVERNED_ACCEPTANCE_TIMESTAMP = "2026-07-29T00:00:00+00:00"
ACCEPTANCE_VERSION = "DSI-011A-acceptance-v1.0.0"


@dataclass(frozen=True, slots=True)
class AcceptanceResult:
    root: Path
    experiment_ids: tuple[str, ...]
    completed_runs: int
    summary_path: Path
    comparison_path: Path
    artifact_manifest_path: Path
    artifact_logical_sha256: str


def run_dsi011a_acceptance(
    *,
    database: Path,
    root: Path,
) -> AcceptanceResult:
    """Execute A-I plus pure-technical and retrospective Alpha acceptance."""

    lab = ConversationalResearchLab(
        database=database,
        root=root,
        governed_created_at=GOVERNED_ACCEPTANCE_TIMESTAMP,
    )
    executions: dict[str, LabExecution] = {}

    a = lab.ask(
        "Backtest the retrospective frozen Alpha model using BUY and STRONG BUY "
        "recommendations from 2016 to the latest certified session. Enter at "
        "the next valid session open. Hold for 20 sessions. Use equal weights. "
        "Allow a maximum of 10 positions. Use 1 crore initial capital. Ignore "
        "transaction costs."
    )
    executions["A"] = a
    a_id = _experiment_id(a)

    b = lab.ask(
        "Add price above the 200-DMA, RSI above 50 and volume at least 1.5 "
        "times its 20-session average. Keep every other setting unchanged.",
        parent_experiment_id=a_id,
    )
    executions["B"] = b
    b_id = _experiment_id(b)

    c = lab.ask(
        "Add bullish engulfing as an entry confirmation.",
        parent_experiment_id=b_id,
    )
    executions["C"] = c
    c_id = _experiment_id(c)

    d = lab.ask(
        "Remove bullish engulfing and keep the indicator filters.",
        parent_experiment_id=c_id,
    )
    executions["D"] = d
    if not _same_strategy_definition(b, d):
        raise RuntimeError(
            "Experiment D does not restore Experiment B strategy definition"
        )

    e = lab.ask(
        "Compare 5% stop, 8% stop, 10% stop, 2 ATR stop and "
        "STOP-STRUCTURAL-10D. Use the same 20-session maximum holding period.",
        parent_experiment_id=b_id,
    )
    executions["E"] = e
    e_id = _experiment_id(e)

    f = lab.ask(
        "Using the 8% stop version, compare 10% target, 20% target, 2R target, "
        "3R target and no fixed target. Keep the 20-session time exit.",
        parent_experiment_id=f"{e_id}-S002",
    )
    executions["F"] = f

    g = lab.ask(
        "Compare no candle confirmation, bullish engulfing, hammer, "
        "inside-bar breakout, and close in the top 20% of the candle range.",
        parent_experiment_id=b_id,
    )
    executions["G"] = g

    h = lab.ask(
        "Take Alpha BUY and STRONG BUY recommendations only when price is "
        "above the 200-DMA, RSI is above 50, volume is at least 1.5 times its "
        "20-session average, and the candle closes in the top 20% of its "
        "range. Enter next session open. Use an 8% stop. Take half at 2R. "
        "Trail the balance with a 10% trailing stop. Exit any remaining "
        "position after 40 sessions. Maximum 10 positions. Equal weight. "
        "No transaction costs.",
        parent_experiment_id=b_id,
    )
    executions["H"] = h
    h_id = _experiment_id(h)

    pure = lab.ask(
        "From 2016 to the latest certified session, buy when RSI(14) crosses "
        "above 30, price is above the 200-DMA, and volume is at least 1.5 "
        "times its 20-session average. Enter at the next valid session open. "
        "Use an 8% stop. Use a 20% target. Exit after 40 sessions if neither "
        "is reached. Maximum 10 equal-weight positions. Initial capital "
        "1 crore. No transaction costs."
    )
    executions["PURE_TECHNICAL"] = pure

    retrospective = lab.ask(
        "Backtest the retrospective frozen Alpha model. Take BUY and STRONG "
        "BUY recommendations. Enter at the next valid session open. Use "
        "STOP-STRUCTURAL-10D. Exit after a maximum of 20 sessions. Maximum "
        "10 equal-weight positions. Initial capital 1 crore. No transaction "
        "costs."
    )
    executions["RETROSPECTIVE_ALPHA"] = retrospective

    comparison = lab.compare((a_id, b_id, c_id, h_id))
    comparison_path = root / "acceptance_comparison.json"
    _write_json(comparison_path, comparison)
    experiment_payload = {
        label: _execution_payload(execution) for label, execution in executions.items()
    }
    summary_path = root / "acceptance_summary.json"
    _write_json(
        summary_path,
        {
            "acceptance_version": ACCEPTANCE_VERSION,
            "governed_created_at": GOVERNED_ACCEPTANCE_TIMESTAMP,
            "experiments": experiment_payload,
            "comparison_experiments": [a_id, b_id, c_id, h_id],
            "production_influence": False,
        },
    )
    manifest_path = root / "acceptance_artifact_manifest.json"
    manifest, logical_hash = _artifact_manifest(root, manifest_path)
    _write_json(
        manifest_path,
        {
            "acceptance_version": ACCEPTANCE_VERSION,
            "artifact_logical_sha256": logical_hash,
            "artifacts": manifest,
            "production_influence": False,
        },
    )
    all_ids = tuple(str(item["experiment_id"]) for item in experiment_payload.values())
    completed = sum(
        int(bool(item["completed"])) for item in experiment_payload.values()
    )
    return AcceptanceResult(
        root=root,
        experiment_ids=all_ids,
        completed_runs=completed,
        summary_path=summary_path,
        comparison_path=comparison_path,
        artifact_manifest_path=manifest_path,
        artifact_logical_sha256=logical_hash,
    )


def _experiment_id(execution: LabExecution) -> str:
    spec = execution.compilation.specification
    if spec is None:
        raise RuntimeError(
            "DSI-011A acceptance compilation failed: "
            + "; ".join(item.message for item in execution.compilation.issues)
        )
    return spec.experiment_id


def _execution_payload(execution: LabExecution) -> dict[str, object]:
    experiment_id = _experiment_id(execution)
    specification = execution.compilation.specification
    if specification is None:
        raise RuntimeError("accepted experiment has no compiled specification")
    payload: dict[str, object] = {
        "experiment_id": experiment_id,
        "completed": execution.completed,
        "planned_children": execution.compilation.planned_children,
        "specification_sha256": specification.specification_sha256,
        "output": f"runs/{experiment_id}",
    }
    if execution.result is not None:
        payload["summary"] = execution.result.summary()
    elif execution.compilation.planned_children:
        children = sorted(
            execution.output.parent.glob(f"{experiment_id}-S*/summary.json")
        )
        payload["children"] = [
            json.loads(path.read_text(encoding="utf-8")) for path in children
        ]
        payload["completed"] = bool(children)
    else:
        payload["blockers"] = list(execution.contract.blockers)
    return payload


def _same_strategy_definition(
    left: LabExecution,
    right: LabExecution,
) -> bool:
    left_spec = left.compilation.specification
    right_spec = right.compilation.specification
    if left_spec is None or right_spec is None:
        return False
    ignored = {
        "experiment_id",
        "experiment_name",
        "parent_experiment_id",
        "research_session_id",
    }
    left_payload = {
        key: value for key, value in left_spec.as_dict().items() if key not in ignored
    }
    right_payload = {
        key: value for key, value in right_spec.as_dict().items() if key not in ignored
    }
    return left_payload == right_payload


def _artifact_manifest(
    root: Path,
    manifest_path: Path,
) -> tuple[list[dict[str, str]], str]:
    rows: list[dict[str, str]] = []
    aggregate = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path == manifest_path:
            continue
        relative = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append({"path": relative, "sha256": digest})
        aggregate.update(relative.encode())
        aggregate.update(b"\0")
        aggregate.update(digest.encode())
        aggregate.update(b"\n")
    return rows, aggregate.hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


__all__ = [
    "ACCEPTANCE_VERSION",
    "GOVERNED_ACCEPTANCE_TIMESTAMP",
    "AcceptanceResult",
    "run_dsi011a_acceptance",
]
