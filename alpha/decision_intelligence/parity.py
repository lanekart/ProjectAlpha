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
        results = [
            _compare_decisions(legacy_decision, recovered_decision)
            for legacy_decision, recovered_decision in zip(
                legacy.decisions,
                recovered.decisions,
                strict=False,
            )
        ]
        results.extend(_decision_count_mismatches(legacy, recovered))
        identical = _count(results, DecisionParityClassification.IDENTICAL)
        expected = _count(results, DecisionParityClassification.EXPECTED_CHANGE)
        unexpected = _count(results, DecisionParityClassification.UNEXPECTED_CHANGE)
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

    payload: dict[str, object] = {
        "candidates_compared": report.candidates_compared,
        "identical": report.identical,
        "expected_changes": report.expected_changes,
        "unexpected_changes": report.unexpected_changes,
        "parity_percentage": str(report.parity_percentage),
        "passed": report.passed,
    }
    summary_json.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_summary_csv(summary_csv, payload)
    _write_differences_csv(differences_csv, report.candidate_results)
    _write_differences_csv(
        unexpected_csv,
        tuple(
            result
            for result in report.candidate_results
            if result.classification
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


def _compare_decisions(
    legacy: OpportunityDecision,
    recovered: OpportunityDecision,
) -> CandidateDecisionParity:
    legacy_symbol = legacy.candidate.symbol
    recovered_symbol = recovered.candidate.symbol
    differences = _decision_differences(legacy, recovered)
    classification = _classify(
        differences,
        legacy_symbol=legacy_symbol,
        recovered_symbol=recovered_symbol,
    )
    return CandidateDecisionParity(
        legacy_symbol=legacy_symbol,
        recovered_symbol=recovered_symbol,
        classification=classification,
        differences=differences,
    )


def _decision_count_mismatches(
    legacy: InstitutionalDecisionReport,
    recovered: InstitutionalDecisionReport,
) -> list[CandidateDecisionParity]:
    difference = len(legacy.decisions) - len(recovered.decisions)
    if difference == 0:
        return []
    return [
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
        for offset in range(abs(difference))
    ]


def _count(
    results: Sequence[CandidateDecisionParity],
    classification: DecisionParityClassification,
) -> int:
    return sum(result.classification is classification for result in results)


def _decision_differences(
    legacy: OpportunityDecision,
    recovered: OpportunityDecision,
) -> tuple[DecisionFieldDifference, ...]:
    differences: list[DecisionFieldDifference] = []
    _collect_differences(
        "",
        _normalize(asdict(legacy)),
        _normalize(asdict(recovered)),
        differences,
    )
    return tuple(differences)


def _collect_differences(
    prefix: str,
    legacy: Any,
    recovered: Any,
    differences: list[DecisionFieldDifference],
) -> None:
    if isinstance(legacy, dict) and isinstance(recovered, dict):
        for key in sorted(set(legacy) | set(recovered)):
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
            differences.append(_difference(prefix, legacy, recovered))
        return
    if legacy != recovered:
        differences.append(_difference(prefix, legacy, recovered))


def _difference(field: str, legacy: Any, recovered: Any) -> DecisionFieldDifference:
    return DecisionFieldDifference(
        field=field,
        legacy_value=_render(legacy),
        recovered_value=_render(recovered),
    )


def _classify(
    differences: tuple[DecisionFieldDifference, ...],
    *,
    legacy_symbol: str,
    recovered_symbol: str,
) -> DecisionParityClassification:
    if not differences:
        return DecisionParityClassification.IDENTICAL
    if legacy_symbol == recovered_symbol:
        return DecisionParityClassification.UNEXPECTED_CHANGE
    if all(
        _is_identity_propagated_difference(
            difference,
            legacy_symbol=legacy_symbol,
            recovered_symbol=recovered_symbol,
        )
        for difference in differences
    ):
        return DecisionParityClassification.EXPECTED_CHANGE
    return DecisionParityClassification.UNEXPECTED_CHANGE


def _is_identity_propagated_difference(
    difference: DecisionFieldDifference,
    *,
    legacy_symbol: str,
    recovered_symbol: str,
) -> bool:
    if difference.field == "candidate.symbol":
        return (
            difference.legacy_value == legacy_symbol
            and difference.recovered_value == recovered_symbol
        )
    return difference.recovered_value == difference.legacy_value.replace(
        legacy_symbol,
        recovered_symbol,
    )


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
            differences = result.differences or (
                DecisionFieldDifference("", "", ""),
            )
            for difference in differences:
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
