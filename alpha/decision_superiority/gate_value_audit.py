"""Diagnostic-only gate value audit for DSI-001."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from alpha.decision_superiority.gate_attribution import (
    ATTRIBUTION_SUMMARY_FIELDS,
    BASELINE_FIELDS,
    FIRST_FAILURE_FIELDS,
    ORDERED_MARGINAL_FIELDS,
    REMOVE_ONE_FIELDS,
    RETAIN_ONLY_FIELDS,
    build_attribution_artifacts,
)
from alpha.decision_superiority.gate_pipeline import (
    GatePipelineInput,
    run_gate_pipeline,
)

DSI001_CONTRACT_VERSION = "DSI-001-v1.0.0"
DSI001_READY = "READY_FOR_GOVERNED_DECISION_SUPERIORITY_RESEARCH"
DSI001_BLOCKED_EMPTY = "BLOCKED_BY_EMPTY_GATE_AUDIT_POPULATION"
DSI001_BLOCKED_OUTCOMES = "BLOCKED_BY_INSUFFICIENT_RESOLVED_OUTCOMES"
DSI001_RESEARCH_SCOPE = "GOVERNED_DECISION_SUPERIORITY_DIAGNOSTIC_ONLY"

_GATE_INVENTORY_FIELDS = (
    "gate_code",
    "gate_category",
    "stage",
    "minimum_ordinal",
    "maximum_ordinal",
    "reached_candidate_count",
    "failed_candidate_count",
    "primary_failure_count",
)
_CANDIDATE_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "input_fingerprint",
    "failure_count",
    "failure_codes",
    "unique_blocker",
    "resolved_outcome",
    "won",
    "realized_return_pct",
    "realized_r",
)
_COUNTERFACTUAL_FIELDS = (
    "price_view",
    "observed_on",
    "symbol",
    "gate_code",
    "failure_count",
    "unique_blocker",
    "would_clear_all_observed_failures",
    "resolved_outcome",
    "realized_return_pct",
    "avoided_loss_benefit",
    "profitable_rejection_cost",
    "net_gate_value",
)
_VALUE_FIELDS = (
    "gate_code",
    "blocked_candidate_count",
    "unique_blocked_candidate_count",
    "co_blocked_candidate_count",
    "resolved_outcome_count",
    "positive_outcome_count",
    "negative_outcome_count",
    "flat_outcome_count",
    "average_return_pct",
    "avoided_loss_benefit",
    "profitable_rejection_cost",
    "net_gate_value",
    "conclusion",
)


@dataclass(slots=True)
class GateAccumulator:
    """Typed mutable aggregation state for one observed gate population."""

    blocked: int = 0
    unique: int = 0
    co: int = 0
    resolved: int = 0
    positive: int = 0
    negative: int = 0
    flat: int = 0
    return_sum: Decimal = Decimal("0")
    unique_returns: list[Decimal] = field(default_factory=list)

    def record_block(self, *, unique: bool) -> None:
        """Record one observed gate failure."""

        self.blocked += 1
        if unique:
            self.unique += 1
        else:
            self.co += 1

    def record_resolved_return(
        self,
        *,
        realized_return: Decimal,
        unique: bool,
    ) -> tuple[Decimal, Decimal]:
        """Record one resolved rejected return and return legacy economics."""

        self.resolved += 1
        self.return_sum += realized_return

        avoided = Decimal("0")
        cost = Decimal("0")
        if realized_return > 0:
            self.positive += 1
            cost = realized_return
        elif realized_return < 0:
            self.negative += 1
            avoided = abs(realized_return)
        else:
            self.flat += 1

        if unique:
            self.unique_returns.append(realized_return)

        return avoided, cost


@dataclass(frozen=True, slots=True)
class DSI001Result:
    """Exported DSI-001 result."""

    report: dict[str, Any]
    paths: tuple[Path, ...]


class GovernedGateValueAudit:
    """Measure observed economic value of governed institutional gates."""

    def run(
        self,
        *,
        candidate_gate_forensics: Path,
        gate_event_ledger: Path,
        outcome_coverage_ledger: Path,
        output: Path,
    ) -> DSI001Result:
        candidates = _read_rows(candidate_gate_forensics)
        gate_events = _read_rows(gate_event_ledger)
        outcomes = _read_rows(outcome_coverage_ledger)

        outcome_by_key = {
            _key(row): row
            for row in outcomes
            if _truthy(row.get("completed")) or _truthy(row.get("forward_completed"))
        }
        failures_by_key: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(
            list
        )
        for row in gate_events:
            if str(row.get("outcome", "")).upper() == "FAIL":
                failures_by_key[_key(row)].append(row)

        candidate_rows: list[dict[str, object]] = []
        counterfactual_rows: list[dict[str, object]] = []
        gate_inventory = self._gate_inventory(gate_events)
        gate_stats: dict[str, GateAccumulator] = defaultdict(GateAccumulator)

        for candidate in candidates:
            key = _key(candidate)
            failures = failures_by_key.get(key, [])
            failure_codes = tuple(
                sorted({str(row.get("gate_code", "UNKNOWN")) for row in failures})
            )
            outcome = outcome_by_key.get(key)
            resolved = outcome is not None
            realized_return = _decimal(
                (outcome or {}).get("realized_return_pct")
                or (outcome or {}).get("realized_return_pct", "")
            )
            realized_r = _decimal(
                (outcome or {}).get("realized_r")
                or (outcome or {}).get("realized_r_multiple", "")
            )
            unique = len(failure_codes) == 1
            won = _truthy((outcome or {}).get("won")) or realized_return > 0
            candidate_rows.append(
                {
                    "price_view": candidate.get("price_view", ""),
                    "observed_on": candidate.get("observed_on", ""),
                    "symbol": candidate.get("symbol", ""),
                    "input_fingerprint": candidate.get("input_fingerprint", ""),
                    "failure_count": len(failure_codes),
                    "failure_codes": "|".join(failure_codes),
                    "unique_blocker": unique,
                    "resolved_outcome": resolved,
                    "won": won if resolved else "UNKNOWN",
                    "realized_return_pct": realized_return if resolved else "",
                    "realized_r": realized_r if resolved else "",
                }
            )
            for gate_code in failure_codes:
                stats = gate_stats[gate_code]
                stats.record_block(unique=unique)
                avoided = Decimal("0")
                cost = Decimal("0")
                if resolved:
                    avoided, cost = stats.record_resolved_return(
                        realized_return=realized_return,
                        unique=unique,
                    )
                counterfactual_rows.append(
                    {
                        "price_view": candidate.get("price_view", ""),
                        "observed_on": candidate.get("observed_on", ""),
                        "symbol": candidate.get("symbol", ""),
                        "gate_code": gate_code,
                        "failure_count": len(failure_codes),
                        "unique_blocker": unique,
                        "would_clear_all_observed_failures": unique,
                        "resolved_outcome": resolved,
                        "realized_return_pct": realized_return if resolved else "",
                        "avoided_loss_benefit": avoided if unique else "",
                        "profitable_rejection_cost": cost if unique else "",
                        "net_gate_value": avoided - cost if unique and resolved else "",
                    }
                )

        attribution = build_attribution_artifacts(
            candidates=candidates,
            gate_events=gate_events,
            outcomes_by_key=outcome_by_key,
        )
        value_rows = self._value_rows(gate_stats)
        cooccurrence_rows = self._cooccurrence_rows(failures_by_key)
        resolved_count = sum(
            1 for row in candidate_rows if row["resolved_outcome"] is True
        )
        readiness = (
            DSI001_BLOCKED_EMPTY
            if not candidate_rows
            else DSI001_BLOCKED_OUTCOMES
            if resolved_count == 0
            else DSI001_READY
        )
        profitable_rejections = sum(
            1
            for row in candidate_rows
            if row["resolved_outcome"] is True
            and Decimal(str(row["realized_return_pct"])) > 0
        )
        avoided_losses = sum(
            1
            for row in candidate_rows
            if row["resolved_outcome"] is True
            and Decimal(str(row["realized_return_pct"])) < 0
        )

        output.mkdir(parents=True, exist_ok=True)
        support = {
            "dsi001_gate_inventory.csv": (gate_inventory, _GATE_INVENTORY_FIELDS),
            "dsi001_candidate_gate_failure_ledger.csv": (
                candidate_rows,
                _CANDIDATE_FIELDS,
            ),
            "dsi001_single_gate_counterfactual_ledger.csv": (
                counterfactual_rows,
                _COUNTERFACTUAL_FIELDS,
            ),
            "dsi001_gate_value_summary.csv": (value_rows, _VALUE_FIELDS),
            "dsi001_gate_cooccurrence_matrix.csv": (
                cooccurrence_rows,
                ("left_gate", "right_gate", "candidate_count", "jaccard"),
            ),
            "dsi001_baseline_policy.csv": (
                list(attribution.baseline_rows),
                BASELINE_FIELDS,
            ),
            "dsi001_remove_one_gate.csv": (
                list(attribution.remove_one_rows),
                REMOVE_ONE_FIELDS,
            ),
            "dsi001_retain_only_gate.csv": (
                list(attribution.retain_only_rows),
                RETAIN_ONLY_FIELDS,
            ),
            "dsi001_first_failure_attribution.csv": (
                list(attribution.first_failure_rows),
                FIRST_FAILURE_FIELDS,
            ),
            "dsi001_ordered_marginal_attribution.csv": (
                list(attribution.ordered_marginal_rows),
                ORDERED_MARGINAL_FIELDS,
            ),
            "dsi001_gate_attribution_summary.csv": (
                list(attribution.summary_rows),
                ATTRIBUTION_SUMMARY_FIELDS,
            ),
            "dsi001_gate_order_lineage.csv": (
                list(attribution.gate_order_rows),
                ("gate_code", "governed_order", "minimum_observed_ordinal"),
            ),
        }
        paths: list[Path] = []
        for name, (rows, fields) in support.items():
            path = output / name
            _write_csv(path, rows, fields)
            paths.append(path)

        artifact_hashes = {path.name: _sha256(path) for path in paths}
        report = {
            "contract_version": DSI001_CONTRACT_VERSION,
            "research_scope": DSI001_RESEARCH_SCOPE,
            "readiness_decision": readiness,
            "candidate_count": len(candidate_rows),
            "resolved_outcome_count": resolved_count,
            "gate_count": len(gate_inventory),
            "profitable_rejection_count": profitable_rejections,
            "avoided_loss_count": avoided_losses,
            "gate_value_summary": value_rows,
            "attribution_summary": list(attribution.summary_rows),
            "ordered_gate_lineage": list(attribution.gate_order_rows),
            "artifact_hashes": artifact_hashes,
            "benchmark_relative_evidence": "UNKNOWN",
            "causal_claim_permitted": False,
            "threshold_change_permitted": False,
            "approval_policy_change_permitted": False,
            "portfolio_policy_change_permitted": False,
            "execution_policy_change_permitted": False,
            "recommendation_influence": False,
            "execution_influence": False,
            "active_replay_integration": False,
            "production_influence": False,
        }
        report["report_sha256"] = hashlib.sha256(
            json.dumps(report, sort_keys=True, default=str).encode()
        ).hexdigest()
        certificate = output / "dsi001_gate_value_audit_certificate.json"
        certificate.write_text(
            json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
            encoding="utf-8",
        )
        paths.append(certificate)
        executive = output / "dsi001_executive_report.md"
        executive.write_text(_markdown(report), encoding="utf-8")
        paths.append(executive)
        return DSI001Result(report=report, paths=tuple(paths))

    @staticmethod
    def _gate_inventory(rows: list[dict[str, str]]) -> list[dict[str, object]]:
        grouped: dict[str, dict[str, object]] = {}
        reached: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        failed: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        primary: Counter[str] = Counter()
        for row in rows:
            code = str(row.get("gate_code", "UNKNOWN"))
            ordinal = int(row.get("gate_ordinal") or 0)
            entry = grouped.setdefault(
                code,
                {
                    "gate_code": code,
                    "gate_category": row.get("gate_category", "UNKNOWN"),
                    "stage": row.get("stage", "UNKNOWN"),
                    "minimum_ordinal": ordinal,
                    "maximum_ordinal": ordinal,
                },
            )
            entry["minimum_ordinal"] = min(
                int(str(entry["minimum_ordinal"])),
                ordinal,
            )
            entry["maximum_ordinal"] = max(
                int(str(entry["maximum_ordinal"])),
                ordinal,
            )
            key = _key(row)
            if _truthy(row.get("stage_reached")):
                reached[code].add(key)
            if str(row.get("outcome", "")).upper() == "FAIL":
                failed[code].add(key)
                if _truthy(row.get("primary")):
                    primary[code] += 1
        result: list[dict[str, object]] = []
        for code, entry in sorted(grouped.items()):
            result.append(
                {
                    **entry,
                    "reached_candidate_count": len(reached[code]),
                    "failed_candidate_count": len(failed[code]),
                    "primary_failure_count": primary[code],
                }
            )
        return result

    @staticmethod
    def _value_rows(
        stats_by_gate: dict[str, GateAccumulator],
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for gate, stats in sorted(stats_by_gate.items()):
            average = (
                stats.return_sum / Decimal(stats.resolved)
                if stats.resolved
                else Decimal("0")
            )
            pipeline = run_gate_pipeline(
                GatePipelineInput(
                    gate_code=gate,
                    sample_count=stats.unique,
                    returns_pct=tuple(stats.unique_returns),
                    minimum_required=0,
                )
            )
            economic_value = pipeline.economic_value
            net = economic_value.net_gate_value
            conclusion = (
                "INSUFFICIENT_RESOLVED_OUTCOMES"
                if stats.resolved == 0
                else "GATE_ADDS_MEASURABLE_VALUE"
                if net > 0
                else "GATE_DESTROYS_MEASURABLE_VALUE"
                if net < 0
                else "GATE_VALUE_INCONCLUSIVE"
            )
            rows.append(
                {
                    "gate_code": gate,
                    "blocked_candidate_count": stats.blocked,
                    "unique_blocked_candidate_count": stats.unique,
                    "co_blocked_candidate_count": stats.co,
                    "resolved_outcome_count": stats.resolved,
                    "positive_outcome_count": stats.positive,
                    "negative_outcome_count": stats.negative,
                    "flat_outcome_count": stats.flat,
                    "average_return_pct": average,
                    "avoided_loss_benefit": economic_value.avoided_loss_benefit,
                    "profitable_rejection_cost": (
                        economic_value.profitable_rejection_cost
                    ),
                    "net_gate_value": net,
                    "conclusion": conclusion,
                }
            )
        return rows

    @staticmethod
    def _cooccurrence_rows(
        failures_by_key: dict[tuple[str, str, str], list[dict[str, str]]],
    ) -> list[dict[str, object]]:
        populations: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
        for key, failures in failures_by_key.items():
            for code in {str(row.get("gate_code", "UNKNOWN")) for row in failures}:
                populations[code].add(key)
        rows: list[dict[str, object]] = []
        gates = sorted(populations)
        for left in gates:
            for right in gates:
                intersection = populations[left] & populations[right]
                union = populations[left] | populations[right]
                rows.append(
                    {
                        "left_gate": left,
                        "right_gate": right,
                        "candidate_count": len(intersection),
                        "jaccard": Decimal(len(intersection)) / Decimal(len(union))
                        if union
                        else Decimal("0"),
                    }
                )
        return rows


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(
    path: Path,
    rows: list[dict[str, object]],
    fields: tuple[str, ...],
) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _key(row: dict[str, str]) -> tuple[str, str, str]:
    return (
        str(row.get("price_view", "")),
        str(row.get("observed_on", "")),
        str(row.get("symbol", "")),
    )


def _truthy(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except InvalidOperation:
        return Decimal("0")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _markdown(report: dict[str, Any]) -> str:
    return (
        "# DSI-001 Governed Decision Superiority and Gate Value Audit\n\n"
        f"- Readiness: `{report['readiness_decision']}`\n"
        f"- Candidates audited: {report['candidate_count']}\n"
        f"- Resolved outcomes: {report['resolved_outcome_count']}\n"
        f"- Gates observed: {report['gate_count']}\n"
        f"- Profitable rejections: {report['profitable_rejection_count']}\n"
        f"- Avoided losses: {report['avoided_loss_count']}\n"
        "- Causal claim permitted: `false`\n"
        "- Production influence: `false`\n"
    )
