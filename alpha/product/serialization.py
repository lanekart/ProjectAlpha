from __future__ import annotations

import json
from dataclasses import dataclass

from alpha.product.rendering import ProductTextRenderer
from alpha.product.reports import ProductReport


@dataclass(frozen=True, slots=True)
class ProductJsonSerializer:
    """Serialize product reports into deterministic JSON."""

    def serialize(self, report: ProductReport, *, indent: int | None = 2) -> str:
        return json.dumps(
            report.as_dict(),
            indent=indent,
            sort_keys=True,
            ensure_ascii=False,
        )


@dataclass(frozen=True, slots=True)
class ProductTextSerializer:
    """Serialize product reports into deterministic plain text."""

    renderer: ProductTextRenderer = ProductTextRenderer()

    def serialize(self, report: ProductReport) -> str:
        return "\n".join(self.renderer.render(report)) + "\n"


__all__ = ["ProductJsonSerializer", "ProductTextSerializer"]
