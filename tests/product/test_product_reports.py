from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from alpha.product import (
    ProductJsonSerializer,
    ProductReport,
    ProductReportMetadata,
    ProductReportSection,
    ProductTextRenderer,
)


def make_report() -> ProductReport:
    return ProductReport(
        metadata=ProductReportMetadata(
            kind="recommendation_report",
            title="Recommendation Report",
            observed_on=date(2026, 1, 30),
            version="1",
            attributes={"source": "foundation-001"},
        ),
        sections=(
            ProductReportSection(
                title="Recommendations",
                metrics={
                    "count": 3,
                    "top_score": Decimal("88.50"),
                    "symbols": ("HAL", "BEL", "LT"),
                },
                lines=("HAL remains the top ranked candidate.",),
            ),
        ),
        diagnostics=("deterministic product report",),
    )


def test_product_report_serializes_deterministically() -> None:
    report = make_report()

    assert report.as_dict() == {
        "kind": "recommendation_report",
        "metadata": {
            "kind": "recommendation_report",
            "title": "Recommendation Report",
            "observed_on": "2026-01-30",
            "version": "1",
            "attributes": {"source": "foundation-001"},
        },
        "sections": [
            {
                "title": "Recommendations",
                "lines": ["HAL remains the top ranked candidate."],
                "metrics": {
                    "count": 3,
                    "symbols": ["HAL", "BEL", "LT"],
                    "top_score": "88.50",
                },
            },
        ],
        "diagnostics": ["deterministic product report"],
    }


def test_product_text_renderer_outputs_stable_lines() -> None:
    lines = ProductTextRenderer().render(make_report())

    assert lines[:5] == (
        "Recommendation Report",
        "",
        "Kind       : recommendation_report",
        "Observed On: 2026-01-30",
        "Version    : 1",
    )
    assert "Recommendations" in lines
    assert "- symbols: HAL, BEL, LT" in lines
    assert "- HAL remains the top ranked candidate." in lines


def test_product_json_serializer_sorts_keys() -> None:
    payload = ProductJsonSerializer().serialize(make_report(), indent=None)

    assert payload.startswith('{"diagnostics"')
    assert '"observed_on": "2026-01-30"' in payload
    assert '"top_score": "88.50"' in payload


def test_product_report_rejects_empty_sections() -> None:
    with pytest.raises(
        ValueError,
        match="product report requires at least one section",
    ):
        ProductReport(
            metadata=ProductReportMetadata(
                kind="empty_report",
                title="Empty Report",
                observed_on=date(2026, 1, 30),
            ),
            sections=(),
        )


def test_product_report_metadata_rejects_empty_kind() -> None:
    with pytest.raises(ValueError, match="report kind cannot be empty"):
        ProductReportMetadata(
            kind=" ",
            title="Invalid",
            observed_on=date(2026, 1, 30),
        )
