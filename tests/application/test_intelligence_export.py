from __future__ import annotations

import json
from datetime import date

import pytest

from alpha.application.intelligence import IntelligenceApplicationService
from alpha.application.intelligence_export import IntelligenceExportService


def test_intelligence_export_writes_json_and_text(tmp_path) -> None:
    run = IntelligenceApplicationService().run(observed_on=date(2026, 1, 30))
    service = IntelligenceExportService()

    json_path = tmp_path / "recommendations.json"
    text_path = tmp_path / "recommendations.txt"

    result = service.export(run, json_path=json_path, text_path=text_path)

    assert result.wrote_any
    assert result.json_path == json_path
    assert result.text_path == text_path
    assert not result.manifest.is_empty

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["kind"] == "recommendation_report"
    assert payload["observed_on"] == "2026-01-30"
    assert [item["symbol"] for item in payload["recommendations"]] == [
        "HAL",
        "LT",
        "BEL",
    ]

    text = text_path.read_text(encoding="utf-8")
    assert "Project Alpha Recommendation Report" in text
    assert "Observed On      : 2026-01-30" in text
    assert "HAL" in text
    assert "Raw Allocation Hint :" in text


def test_intelligence_export_rejects_invalid_suffixes(tmp_path) -> None:
    run = IntelligenceApplicationService().run(observed_on=date(2026, 1, 30))
    service = IntelligenceExportService()

    with pytest.raises(ValueError, match="expected .json output path"):
        service.export(
            run,
            json_path=tmp_path / "recommendations.txt",
            text_path=None,
        )

    with pytest.raises(ValueError, match="expected .txt output path"):
        service.export(
            run,
            json_path=None,
            text_path=tmp_path / "recommendations.json",
        )
