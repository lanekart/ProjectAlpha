"""Decision parity validation for recovered security identity migration."""

from __future__ import annotations

import csv
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from alpha.decision_intelligence.identity import RecoveredIdentityDecisionEngine
from alpha.decision_intelligence.models import (
    InstitutionalCandidate,
    InstitutionalDecisionReport,
    OpportunityDecision,
)


class DecisionParityClassification(StrEnum):
    """Candidate-level parity classification."""

    IDENTICAL = "IDENTICAL"
    EXPECTED_CHANGE = "EXPECTED_CHANGE"
    UNEXPECTED_CHANGE = "UNEXPECTED_CHANGE"


@dataclass(frozen=True, slots=True)
class DecisionFieldDifference:
    """One semantic field difference between legacy and recovered decisions."""

    field: str
    legacy_value: str
    recovered_value: str


@dataclass(frozen=True, slots=True)
class CandidateDecisionParity:
    """Candidate-level decision parity result."""

    legacy_symbol: str
    recovered_symbol: str
    classification: DecisionParityClassification
    differences: tuple[DecisionFieldDifference, ...]


@dataclass(frozen=True, slots=True)
class DecisionParityReport:
    """Summary of identity-migration decision parity."""

    candidates_compared: int
    identical: int
    expected_changes: int
    unexpected_changes: int
    parity_percentage: Decimal
    passed: bool
    candidate_results: tuple[CandidateDecisionParity, ...]


class DecisionParityValidator:
    """Compare legacy and recovered decision semantics for the same candidates."""

    def __init__(self, recovered_engine: RecoveredIdentityDecisionEngine) -> None:
        self.recovered_engine = recovered_engine
        self.legacy_engine = recovered_engine.decision_engine

    def validate(
        self,
        candidates: tuple[InstitutionalCandidate, ...],
    ) -> DecisionParityReport:
        legacy_report = self.legacy_engine.evaluate(candidates)
        recovered_candidates = self.recovered_engine.canonicalize_candidates(candidates)
        recovered_report = self.legacy_engine.evaluate(recovered_candidates)
        return self.compare_reports(legacy_report, recovered_report)

    def compare_reports(
        self,
        legacy: InstitutionalDecisionReport,
        recovered: InstitutionalDecisionReport,
    ) -> DecisionParityReport:
        legacy_by_symbol = _decision_index(legacy.decisions)
        recovered_by_position = tuple(recovered.decisions)
        results: list[CandidateDecisionParity] = []

        for index, legacy_decision in enumerate(legacy.decisions):
            recovered_decision = recovered_by_position[index]
            legacy_symbol = legacy_decision.candidate.symbol
            recovered_symbol = recovered_decision.candidate.symbol
            differences = _decision_differences(legacy_decision, recovered_decision)
            classification = _classify(differences)
            results.append(
                CandidateDecisionParity(
                    legacy_symbol=legacy_symbol,
                    recovered_symbol=recovered_symbol,
                    classification=classification,
                    differences=differences,
                )
            )

        if len(legacy.decisions) != len(recovered.decisions):
            missing = abs(len(legacy.decisions) - len(recovered.decisions))
            for offset in range(missing):
                results.append(
                    CandidateDecisionParity(
                        legacy_symbol=f"MISSING:{offset}",
                        recovered_symbol=f"MISSING:{offset}",
                        classification=DecisionParityClassification.UNEXPECTED_CHANGE,
                        differences=(
                            DecisionFieldDifference(
                                field="decision_count",
                                legacy_value=str(len(legacy.decisions)),
                                recovered_value=str(len(recovered.decisions)),
                            ),
                        ),
                    )
                )

        del legacy_by_symbol
        identical = sum(
            item.classification is DecisionParityClassification.IDENTICAL
            for item in results
        )
        expected = sum(
            item.classification is DecisionParityClassification.EXPECTED_CHANGE
            for item in results
        )
        unexpected = sum(
            item.classification is DecisionParityClassification.UNEXPECTED_CHANGE
            for item in results
        )
        compared = len(results)
        parity = (
            Decimal("100.00")
            if compared == 0
            else (
                Decimal(identical + expected) * Decimal("100") / Decimal(compared)
            ).quantize(Decimal("0.01"))
        )
        return DecisionParityReport(
            candidates_compared=compared,
            identical=identical,
            expected_changes=expected,
            unexpected_changes=unexpected,
            parity_percentage=parity,
            passed=unexpected == 0,
            candidate_results=tuple(results),
        )


def export_decision_parity(
    report: DecisionParityReport,
    output: Path,
) -> tuple[Path, ...]:
    """Export deterministic parity artifacts."""

    output.mkdir(parents=True, exist_ok=True)
    summary_json = output / "summary.json"
    summary_csv = output / "summary.csv"
    differences_csv = output / "candidate_differences.csv"
    unexpected_csv = output / "unexpected_changes.csv"
    report_md = output / "report.md"

    summary_payload = {
        "candidates_compared": report.candidates_compared,
        "identical": report.identical,
        "expected_changes": report.expected_changes,
        "unexpected_changes": report.unexpected_changes,
        "parity_percentage": str(report.parity_percentage),
        "passed": report.passed,
    }
    summary_json.write_text(
        json.dumps(summary_payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_summary_csv(summary_csv, summary_payload)
    _write_differences_csv(differences_csv, report.candidate_results)
    _write_differences_csv(
        unexpected_csv,
        tuple(
            item
            for item in report.candidate_results
            if item.classification
            is DecisionParityClassification.UNEXPECTED_CHANGE
        ),
    )
    report_md.write_text(_render_report(report), encoding="utf-8")
    return (
        summary_json,
        summary_csv,
        differences_csv,
        unexpected_csv,
        report_md,
    )


def _decision_index(
    decisions: Sequence[OpportunityDecision],
) -> Mapping[str, OpportunityDecision]:
    return {decision.candidate.symbol: decision for decision in decisions}


def _decision_differences(
    legacy: OpportunityDecision,
    recovered: OpportunityDecision,
) -> tuple[DecisionFieldDifference, ...]:
    legacy_payload = _normalize(asdict(legacy))
    recovered_payload = _normalize(asdict(recovered))
    differences: list[DecisionFieldDifference] = []
    _collect_differences("", legacy_payload, recovered_payload, differences)
    return tuple(differences)


def _collect_differences(
    prefix: str,
    legacy: Any,
    recovered: Any,
    differences: list[DecisionFieldDifference],
) -> None:
    if isinstance(legacy, dict) and isinstance(recovered, dict):
        keys = sorted(set(legacy) | set(recovered))
        for key in keys:
            field = f"{prefix}.{key}" if prefix else str(key)
            _collect_differences(
                field,
                legacy.get(key),
                recovered.get(key),
                differences,
            )
        return
    if isinstance(legacy, list) and isinstance(recovered, list):
        if legacy != recovered:
            differences.append(
                DecisionFieldDifference(
                    field=prefix,
                    legacy_value=_render(legacy),
                    recovered_value=_render(recovered),
                )
            )
        return
    if legacy != recovered:
        differences.append(
            DecisionFieldDifference(
                field=prefix,
                legacy_value=_render(legacy),
                recovered_value=_render(recovered),
            )
        )


def _classify(
    differences: tuple[DecisionFieldDifference, ...],
) -> DecisionParityClassification:
    if not differences:
        return DecisionParityClassification.IDENTICAL
    allowed = {"candidate.symbol"}
    if {difference.field for difference in differences} <= allowed:
        return DecisionParityClassification.EXPECTED_CHANGE
    return DecisionParityClassification.UNEXPECTED_CHANGE


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


def _render(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


def _write_summary_csv(path: Path, payload: Mapping[str, object]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(payload))
        writer.writeheader()
        writer.writerow(payload)


def _write_differences_csv(
    path: Path,
    results: Sequence[CandidateDecisionParity],
) -> None:
    columns = (
        "legacy_symbol",
        "recovered_symbol",
        "classification",
        "field",
        "legacy_value",
        "recovered_value",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for result in results:
            if not result.differences:
                writer.writerow(
                    {
                        "legacy_symbol": result.legacy_symbol,
                        "recovered_symbol": result.recovered_symbol,
                        "classification": result.classification.value,
                        "field": "",
                        "legacy_value": "",
                        "recovered_value": "",
                    }
                )
                continue
            for difference in result.differences:
                writer.writerow(
                    {
                        "legacy_symbol": result.legacy_symbol,
                        "recovered_symbol": result.recovered_symbol,
                        "classification": result.classification.value,
                        "field": difference.field,
                        "legacy_value": difference.legacy_value,
                        "recovered_value": difference.recovered_value,
                    }
                )


def _render_report(report: DecisionParityReport) -> str:
    unexpected_fields = [
        difference.field
        for result in report.candidate_results
        if result.classification is DecisionParityClassification.UNEXPECTED_CHANGE
        for difference in result.differences
    ]
    top = ", ".join(unexpected_fields[:5]) or "NONE"
    recommendation = (
        "Recovered identity migration is safe to continue."
        if report.passed
        else "Investigate unexpected differences before retiring legacy identity."
    )
    return (
        "# Decision Parity Validation\n\n"
        f"- Candidates Compared: `{report.candidates_compared}`\n"
        f"- Parity: `{report.parity_percentage}%`\n"
        f"- Identical: `{report.identical}`\n"
        f"- Expected Changes: `{report.expected_changes}`\n"
        f"- Unexpected Changes: `{report.unexpected_changes}`\n"
        f"- Result: `{'PASS' if report.passed else 'FAIL'}`\n"
        f"- Top Unexpected Differences: `{top}`\n"
        f"- Recommendation: {recommendation}\n"
    )
