"""Deterministic tests for the reusable diagnostics foundation."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from alpha.diagnostics import (
    DiagnosticContext,
    DiagnosticEngine,
    DiagnosticRegistry,
    Finding,
    FindingStatus,
    Recommendation,
    ScoreCard,
    ScoreDimension,
    Severity,
    build_scorecard,
    export_findings_csv,
    export_json,
    export_markdown,
)


class ExampleEngine(DiagnosticEngine):
    engine_key = "example"
    engine_version = "1.0.0"

    def __init__(self) -> None:
        self.calls: list[str] = []

    def discover(self, context: DiagnosticContext) -> Mapping[str, object]:
        self.calls.append("discover")
        return {"rows": 10, "parameter_count": len(context.parameters)}

    def validate(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
    ) -> tuple[Finding, ...]:
        del context
        self.calls.append("validate")
        return (
            Finding(
                check_key="rows_present",
                status=FindingStatus.PASS,
                severity=Severity.INFO,
                summary="Rows are present.",
                evidence={"rows": discovery["rows"]},
            ),
        )

    def score(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
        findings: tuple[Finding, ...],
    ) -> ScoreCard:
        del context, discovery, findings
        self.calls.append("score")
        return build_scorecard((ScoreDimension("coverage", 100.0, 1.0),))

    def classify(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
        findings: tuple[Finding, ...],
        scorecard: ScoreCard,
    ) -> str:
        del context, discovery, findings
        self.calls.append("classify")
        return "CERTIFIED" if scorecard.weighted_score == 100.0 else "NOT_CERTIFIED"

    def recommend(
        self,
        context: DiagnosticContext,
        discovery: Mapping[str, object],
        findings: tuple[Finding, ...],
        scorecard: ScoreCard,
        classification: str,
    ) -> tuple[Recommendation, ...]:
        del context, discovery, findings, scorecard, classification
        self.calls.append("recommend")
        return ()


def _context(tmp_path: Path) -> DiagnosticContext:
    return DiagnosticContext(
        engine_key="example",
        as_of=datetime(2026, 7, 20, 12, 0, tzinfo=UTC),
        output_directory=tmp_path,
        parameters={"year": 2026},
    )


def test_lifecycle_order_and_result(tmp_path: Path) -> None:
    engine = ExampleEngine()

    result = engine.run(_context(tmp_path))

    assert engine.calls == ["discover", "validate", "score", "classify", "recommend"]
    assert result.classification == "CERTIFIED"
    assert result.discovery == {"rows": 10, "parameter_count": 1}
    assert result.scorecard.weighted_score == 100.0


def test_context_engine_key_must_match(tmp_path: Path) -> None:
    engine = ExampleEngine()
    context = DiagnosticContext(
        engine_key="wrong",
        as_of=datetime(2026, 7, 20, tzinfo=UTC),
        output_directory=tmp_path,
    )

    with pytest.raises(ValueError, match="does not match"):
        engine.run(context)


def test_scorecard_is_normalized_and_validated() -> None:
    scorecard = build_scorecard(
        (
            ScoreDimension("coverage", 100.0, 3.0),
            ScoreDimension("integrity", 50.0, 1.0),
        )
    )
    assert scorecard.weighted_score == 87.5

    with pytest.raises(ValueError, match="between 0 and 100"):
        build_scorecard((ScoreDimension("invalid", 101.0, 1.0),))


def test_registry_rejects_duplicates_and_bad_factories() -> None:
    registry = DiagnosticRegistry()
    registry.register("example", ExampleEngine)

    assert registry.keys() == ("example",)
    assert isinstance(registry.create("example"), ExampleEngine)

    with pytest.raises(ValueError, match="already registered"):
        registry.register("example", ExampleEngine)

    registry.register("alias", ExampleEngine)
    with pytest.raises(ValueError, match="produced engine"):
        registry.create("alias")


def test_exports_are_deterministic(tmp_path: Path) -> None:
    result = ExampleEngine().run(_context(tmp_path))

    json_path = export_json(result, tmp_path / "result.json")
    csv_path = export_findings_csv(result, tmp_path / "findings.csv")
    markdown_path = export_markdown(result, tmp_path / "report.md")

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["engine_key"] == "example"
    assert payload["generated_at"] == "2026-07-20T12:00:00+00:00"
    assert csv_path.read_text(encoding="utf-8").splitlines()[0] == (
        "check_key,status,severity,summary,details,evidence"
    )
    report = markdown_path.read_text(encoding="utf-8")
    assert "Classification: **CERTIFIED**" in report
    assert "| coverage | 100.00 | 1.00 |" in report
